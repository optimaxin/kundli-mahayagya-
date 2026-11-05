"""Excel reporting (openpyxl, streaming write-only workbooks).

Sheets: Dashboard, Family Bookings, Family Members, Session Attendance,
Kund Allocation, Cancellations, No Shows.

* DAILY reports cover the sessions of one event date; FINAL covers all.
* No-shows are computed ONLY for sessions whose scheduled end time has
  passed; other sessions are listed as "not completed".
* Reports are read-only views; nothing is deleted. Excel exports are not
  backups (see docs/operations-runbook.md for pg_dump based backups).
* Cell values that start with = + - @ are prefixed with ' to prevent
  spreadsheet formula injection from user-entered text.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.errors import NotFound, ValidationFailed
from app.models import (
    AdminUser,
    AttendanceCheckin,
    Booking,
    BookingSession,
    CancellationEvent,
    EventSession,
    FamilyMember,
    Kund,
    KundSessionCapacity,
    ReportJob,
)
from app.models.enums import ReportStatus, ReportType, ReservationStatus
from app.services import session_service
from app.services.audit_service import RequestContext, audit

logger = logging.getLogger("app.reports")

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="8B2500")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_STREAM = {"yield_per": 2000}

# Layout shown on passes: 11 zones x 5 sectors (sectors 1-4 = 39 kunds, sector 5 = the rest of the zone).
_ZONES = ["Brahma", "Vishnu", "Shiva", "Surya", "Ganesha", "Durga", "Lakshmi", "Saraswati", "Hanuman", "Indra", "Agni"]
_PER_ZONE = 196


def zone_sector(kund_number: int) -> tuple[str, int]:
    """Same mapping as the frontend (src/lib/db.js): returns ("Brahma", 1..5)."""
    z = min(len(_ZONES) - 1, (kund_number - 1) // _PER_ZONE)
    o = (kund_number - 1) % _PER_ZONE
    return _ZONES[z], (5 if o >= 156 else o // 39 + 1)


def _safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    if isinstance(value, datetime):
        return value.astimezone(clock.event_tz()).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class _Sheet:
    def __init__(self, wb: Workbook, title: str, headers: list[str], widths: list[int] | None = None) -> None:
        self.ws = wb.create_sheet(title)
        for i, w in enumerate(widths or [], start=1):
            self.ws.column_dimensions[chr(64 + i) if i <= 26 else "A"].width = w
        self.ws.freeze_panes = "A2"
        cells = []
        for h in headers:
            c = WriteOnlyCell(self.ws, value=h)
            c.font = _HEADER_FONT
            c.fill = _HEADER_FILL
            cells.append(c)
        self.ws.append(cells)
        self.rows = 0

    def add(self, values: list[Any]) -> None:
        self.ws.append([_safe(v) for v in values])
        self.rows += 1


class ReportingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------- scoping
    def _sessions_in_scope(self, report_type: str, report_date: date | None) -> list[EventSession]:
        stmt = select(EventSession).order_by(EventSession.id)
        if report_type == ReportType.DAILY.value:
            if report_date is None:
                raise ValidationFailed("report_date is required for DAILY reports")
            stmt = stmt.where(EventSession.event_date == report_date)
        sessions = list(self.db.scalars(stmt))
        if not sessions:
            raise ValidationFailed("No event sessions on the requested date")
        return sessions

    # ------------------------------------------------------- summary data
    def session_summary(self, sessions: list[EventSession]) -> list[dict[str, Any]]:
        ids = [s.id for s in sessions]
        db = self.db
        cap = dict(
            (sid, (int(c), int(r)))
            for sid, c, r in db.execute(
                select(KundSessionCapacity.session_id, func.sum(KundSessionCapacity.capacity),
                       func.sum(KundSessionCapacity.reserved_count))
                .where(KundSessionCapacity.session_id.in_(ids))
                .group_by(KundSessionCapacity.session_id)
            )
        )
        res: dict[tuple[int, str], tuple[int, int]] = {}
        for sid, status, fams, mems in db.execute(
            select(BookingSession.session_id, BookingSession.status, func.count(), func.sum(BookingSession.member_count))
            .where(BookingSession.session_id.in_(ids))
            .group_by(BookingSession.session_id, BookingSession.status)
        ):
            res[(sid, status)] = (int(fams), int(mems or 0))
        checked = dict(
            db.execute(
                select(BookingSession.session_id, func.count())
                .join(AttendanceCheckin, AttendanceCheckin.booking_session_id == BookingSession.id)
                .where(BookingSession.session_id.in_(ids), BookingSession.status == ReservationStatus.CONFIRMED.value)
                .group_by(BookingSession.session_id)
            ).all()
        )
        kunds_used = dict(
            db.execute(
                select(KundSessionCapacity.session_id, func.count())
                .where(KundSessionCapacity.session_id.in_(ids), KundSessionCapacity.reserved_count > 0)
                .group_by(KundSessionCapacity.session_id)
            ).all()
        )
        out = []
        for s in sessions:
            capacity, reserved = cap.get(s.id, (0, 0))
            conf_f, conf_m = res.get((s.id, "CONFIRMED"), (0, 0))
            canc_f, canc_m = res.get((s.id, "CANCELLED"), (0, 0))
            ci = int(checked.get(s.id, 0))
            completed = session_service.is_completed(s)
            out.append(
                {
                    "session_id": s.id,
                    "event_date": s.event_date,
                    "slot": s.slot,
                    "time": f"{s.start_time:%H:%M}-{s.end_time:%H:%M}",
                    "confirmed_families": conf_f,
                    "registered_members": conf_m,
                    "capacity": capacity,
                    "reserved": reserved,
                    "remaining": capacity - reserved,
                    "kunds_in_use": int(kunds_used.get(s.id, 0)),
                    "utilisation_percent": round(100 * reserved / capacity, 2) if capacity else 0.0,
                    "checkins": ci,
                    "completed": completed,
                    "no_shows": (conf_m - ci) if completed else None,
                    "cancelled_families": canc_f,
                    "cancelled_members": canc_m,
                }
            )
        return out

    # ---------------------------------------------------------- workbook
    def build_workbook(self, path: Path, report_type: str, report_date: date | None) -> dict[str, Any]:
        sessions = self._sessions_in_scope(report_type, report_date)
        ids = [s.id for s in sessions]
        by_id = {s.id: s for s in sessions}
        summary = self.session_summary(sessions)
        wb = Workbook(write_only=True)
        db = self.db
        in_scope_bookings = select(BookingSession.booking_id).where(BookingSession.session_id.in_(ids))

        # 1. Dashboard
        dash = _Sheet(wb, "Dashboard", ["Metric", "Value"], [42, 30])
        totals = {
            "Report type": report_type,
            "Report date": report_date.isoformat() if report_date else "All event days",
            "Generated at (IST)": clock.now(),
            "Total family bookings": db.scalar(
                select(func.count()).select_from(Booking).where(Booking.id.in_(in_scope_bookings))
            ),
            "Confirmed family bookings": db.scalar(
                select(func.count()).select_from(Booking)
                .where(Booking.id.in_(in_scope_bookings), Booking.status == "CONFIRMED")
            ),
            "Total unique registered members": db.scalar(
                select(func.count()).select_from(FamilyMember).where(FamilyMember.booking_id.in_(in_scope_bookings))
            ),
            "Attendee-session reservations (confirmed)": sum(r["registered_members"] for r in summary),
            "Actual check-ins": sum(r["checkins"] for r in summary),
            "No-shows (completed sessions only)": sum(r["no_shows"] or 0 for r in summary),
            "Sessions not yet completed": sum(1 for r in summary if not r["completed"]),
            "Total capacity": sum(r["capacity"] for r in summary),
            "Remaining capacity": sum(r["remaining"] for r in summary),
            "Cancelled family reservations": sum(r["cancelled_families"] for r in summary),
            "Cancelled attendee places": sum(r["cancelled_members"] for r in summary),
        }
        for k, v in totals.items():
            dash.add([k, v])
        dash.add([])
        dash.add(["Session-wise", ""])
        dash.ws.append(
            [
                "Session", "Date", "Slot", "Time (IST)", "Families", "Members reserved", "Capacity", "Remaining",
                "Kunds in use", "Utilisation %", "Check-ins", "No-shows", "Cancelled families", "Cancelled members",
            ]
        )
        for r in summary:
            dash.add(
                [
                    r["session_id"], r["event_date"], r["slot"], r["time"], r["confirmed_families"],
                    r["registered_members"],
                    r["capacity"], r["remaining"], r["kunds_in_use"], r["utilisation_percent"], r["checkins"],
                    r["no_shows"] if r["completed"] else "Session not completed",
                    r["cancelled_families"], r["cancelled_members"],
                ]
            )

        # 2. Family Bookings
        fb = _Sheet(
            wb, "Family Bookings",
            ["Booking number", "Status", "Coordinator", "Primary mobile", "Secondary mobile", "Email", "Address",
             "City", "State", "Pincode", "Gotra", "Sankalp purpose", "Members", "Sessions (session:kund:status)",
             "Created at", "Cancelled at"],
            [16, 11, 24, 14, 14, 26, 30, 14, 16, 9, 14, 30, 8, 40, 20, 20],
        )
        alloc: dict[int, list[str]] = {}
        for bid, sid, kn, st in db.execute(
            select(BookingSession.booking_id, BookingSession.session_id, Kund.kund_number, BookingSession.status)
            .join(Kund, Kund.id == BookingSession.kund_id)
            .where(BookingSession.session_id.in_(ids))
            .order_by(BookingSession.booking_id, BookingSession.session_id)
            .execution_options(**_STREAM)
        ):
            alloc.setdefault(bid, []).append(f"{sid}:K{kn}({zone_sector(kn)[0]}-S{zone_sector(kn)[1]}):{st[0]}")
        for b in db.scalars(
            select(Booking).where(Booking.id.in_(in_scope_bookings)).order_by(Booking.id).execution_options(**_STREAM)
        ):
            fb.add(
                [b.booking_number, b.status, b.coordinator_name, b.primary_mobile, b.secondary_mobile, b.email,
                 b.address, b.city, b.state, b.pincode, b.gotra, b.sankalp_purpose, b.member_count,
                 ", ".join(alloc.get(b.id, [])), b.created_at, b.cancelled_at]
            )

        # 3. Family Members
        fm = _Sheet(wb, "Family Members",
                    ["Booking number", "Member #", "Full name", "Age", "Gender", "Relationship", "Booking status"],
                    [16, 9, 30, 6, 9, 14, 14])
        for bn, mn, name, age, gender, rel, st in db.execute(
            select(Booking.booking_number, FamilyMember.member_number, FamilyMember.full_name, FamilyMember.age,
                   FamilyMember.gender, FamilyMember.relationship_, Booking.status)
            .join(Booking, Booking.id == FamilyMember.booking_id)
            .where(Booking.id.in_(in_scope_bookings))
            .order_by(Booking.id, FamilyMember.member_number)
            .execution_options(**_STREAM)
        ):
            fm.add([bn, mn, name, age, gender, rel, st])

        # 4. Session Attendance (one row per member per reservation)
        sa = _Sheet(
            wb, "Session Attendance",
            ["Session", "Date", "Slot", "Booking number", "Zone", "Sector", "Kund", "Member #", "Full name",
             "Reservation status", "Checked in", "Checked in at", "Source", "Scanned by", "Scanner email"],
            [8, 11, 9, 16, 12, 7, 7, 9, 28, 12, 10, 20, 12, 24, 28],
        )
        for sid, bn, kn, mn, name, rst, at, src, scan_name, scan_email in db.execute(
            select(BookingSession.session_id, Booking.booking_number, Kund.kund_number, FamilyMember.member_number,
                   FamilyMember.full_name, BookingSession.status, AttendanceCheckin.checked_in_at,
                   AttendanceCheckin.source, AdminUser.full_name, AdminUser.email)
            .join(Booking, Booking.id == BookingSession.booking_id)
            .join(Kund, Kund.id == BookingSession.kund_id)
            .join(FamilyMember, FamilyMember.booking_id == BookingSession.booking_id)
            .outerjoin(
                AttendanceCheckin,
                (AttendanceCheckin.booking_session_id == BookingSession.id)
                & (AttendanceCheckin.member_id == FamilyMember.id),
            )
            .outerjoin(AdminUser, AdminUser.id == AttendanceCheckin.scanner_id)
            .where(BookingSession.session_id.in_(ids))
            .order_by(BookingSession.session_id, Kund.kund_number, Booking.id, FamilyMember.member_number)
            .execution_options(**_STREAM)
        ):
            s = by_id[sid]
            zn, sec = zone_sector(kn)
            sa.add([sid, s.event_date, s.slot, bn, zn, sec, kn, mn, name, rst, "YES" if at else "NO", at, src,
                    scan_name if at else None, scan_email if at else None])

        # 5. Kund Allocation
        ka = _Sheet(
            wb, "Kund Allocation",
            ["Session", "Date", "Slot", "Zone", "Sector", "Kund", "Kund active", "Capacity", "Reserved", "Remaining", "Utilisation %",
             "Families (booking:members)"],
            [8, 11, 9, 12, 7, 7, 10, 9, 9, 10, 12, 50],
        )
        fams: dict[tuple[int, int], list[str]] = {}
        for sid, kid, bn, mc in db.execute(
            select(BookingSession.session_id, BookingSession.kund_id, Booking.booking_number, BookingSession.member_count)
            .join(Booking, Booking.id == BookingSession.booking_id)
            .where(BookingSession.session_id.in_(ids), BookingSession.status == "CONFIRMED")
            .execution_options(**_STREAM)
        ):
            fams.setdefault((sid, kid), []).append(f"{bn}:{mc}")
        for ksc, kn, active in db.execute(
            select(KundSessionCapacity, Kund.kund_number, Kund.is_active)
            .join(Kund, Kund.id == KundSessionCapacity.kund_id)
            .where(KundSessionCapacity.session_id.in_(ids))
            .order_by(KundSessionCapacity.session_id, Kund.kund_number)
            .execution_options(**_STREAM)
        ):
            s = by_id[ksc.session_id]
            ka.add(
                [ksc.session_id, s.event_date, s.slot, *zone_sector(kn), kn, "YES" if active else "NO", ksc.capacity,
                 ksc.reserved_count, ksc.capacity - ksc.reserved_count,
                 round(100 * ksc.reserved_count / ksc.capacity, 1), ", ".join(fams.get((ksc.session_id, ksc.kund_id), []))]
            )

        # 6. Cancellations
        cx = _Sheet(
            wb, "Cancellations",
            ["Booking number", "Session", "Date", "Slot", "Kund", "Released members", "Reason", "Cancelled at",
             "Actor id"],
            [16, 8, 11, 9, 7, 10, 40, 20, 38],
        )
        for ev, bn, kn in db.execute(
            select(CancellationEvent, Booking.booking_number, Kund.kund_number)
            .join(Booking, Booking.id == CancellationEvent.booking_id)
            .join(Kund, Kund.id == CancellationEvent.kund_id)
            .where(CancellationEvent.session_id.in_(ids))
            .order_by(CancellationEvent.id)
            .execution_options(**_STREAM)
        ):
            s = by_id[ev.session_id]
            cx.add([bn, ev.session_id, s.event_date, s.slot, kn, ev.released_member_count, ev.reason,
                    ev.created_at, ev.actor_id])

        # 7. No Shows (completed sessions only)
        ns = _Sheet(
            wb, "No Shows",
            ["Session", "Date", "Slot", "Booking number", "Kund", "Member #", "Full name", "Coordinator",
             "Coordinator mobile"],
            [8, 11, 9, 16, 7, 9, 28, 24, 16],
        )
        completed_ids = [s.id for s in sessions if session_service.is_completed(s)]
        for s in sessions:
            if s.id not in completed_ids:
                ns.add([s.id, s.event_date, s.slot, "Session not completed - no-shows not calculated"])
        if completed_ids:
            for sid, bn, kn, mn, name, coord, mob in db.execute(
                select(BookingSession.session_id, Booking.booking_number, Kund.kund_number, FamilyMember.member_number,
                       FamilyMember.full_name, Booking.coordinator_name, Booking.primary_mobile)
                .join(Booking, Booking.id == BookingSession.booking_id)
                .join(Kund, Kund.id == BookingSession.kund_id)
                .join(FamilyMember, FamilyMember.booking_id == BookingSession.booking_id)
                .outerjoin(
                    AttendanceCheckin,
                    (AttendanceCheckin.booking_session_id == BookingSession.id)
                    & (AttendanceCheckin.member_id == FamilyMember.id),
                )
                .where(
                    BookingSession.session_id.in_(completed_ids),
                    BookingSession.status == ReservationStatus.CONFIRMED.value,
                    AttendanceCheckin.id.is_(None),
                )
                .order_by(BookingSession.session_id, Kund.kund_number, Booking.id, FamilyMember.member_number)
                .execution_options(**_STREAM)
            ):
                s = by_id[sid]
                ns.add([sid, s.event_date, s.slot, bn, kn, mn, name, coord, mob])

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        wb.save(tmp)
        os.replace(tmp, path)
        return {
            "sessions": summary,
            "totals": {k: (v.isoformat() if isinstance(v, datetime | date) else v) for k, v in totals.items()},
            "row_counts": {
                "family_bookings": fb.rows, "family_members": fm.rows, "session_attendance": sa.rows,
                "kund_allocation": ka.rows, "cancellations": cx.rows, "no_shows": ns.rows,
            },
        }

    # --------------------------------------------------------------- jobs
    def create_job(self, report_type: str, report_date: date | None, ctx: RequestContext) -> ReportJob:
        self._sessions_in_scope(report_type, report_date)  # validate early
        job = ReportJob(
            id=uuid.uuid4(), report_type=report_type, report_date=report_date,
            status=ReportStatus.PENDING.value, requested_by=ctx.actor_id,
        )
        self.db.add(job)
        audit(self.db, ctx, action="REPORT_REQUESTED", entity_type="report_job", entity_id=str(job.id),
              new={"report_type": report_type, "report_date": report_date.isoformat() if report_date else None})
        self.db.commit()
        return job

    def get_job(self, job_id: uuid.UUID) -> ReportJob:
        job = self.db.get(ReportJob, job_id)
        if job is None:
            raise NotFound("Report job not found")
        return job

    def job_file(self, job: ReportJob) -> Path:
        if job.status != ReportStatus.COMPLETED.value or not job.file_name:
            raise NotFound("Report is not ready", code="REPORT_NOT_READY", status_code=409)
        path = storage_path(job)
        if not path.is_file():
            legacy = Path(get_settings().REPORTS_DIR) / job.file_name  # jobs created before storage_path()
            if not legacy.is_file():
                raise NotFound("Report file is no longer available. Please generate it again.",
                               code="REPORT_EXPIRED", status_code=410)
            path = legacy
        return path


def storage_path(job: ReportJob) -> Path:
    """Where the workbook is stored on disk (unique per job)."""
    return Path(get_settings().REPORTS_DIR) / f"{job.id.hex}.xlsx"


def download_name(job: ReportJob) -> str:
    """Human-friendly file name, e.g. Mahayagya_Registration_Report_20261105.xlsx."""
    if job.report_type == ReportType.DAILY.value and job.report_date:
        return f"Mahayagya_Daily_Report_{job.report_date:%Y%m%d}.xlsx"
    return f"Mahayagya_Registration_Report_{clock.now().astimezone(clock.event_tz()):%Y%m%d}.xlsx"


def run_report_job(job_id: uuid.UUID) -> None:
    """Background worker entry point (own DB session)."""
    with get_sessionmaker()() as db:
        job = db.get(ReportJob, job_id)
        if job is None:
            return
        job.status = ReportStatus.RUNNING.value
        job.started_at = clock.now()
        db.commit()
        file_name = download_name(job)
        try:
            summary = ReportingService(db).build_workbook(storage_path(job), job.report_type, job.report_date)
            db.rollback()
            job = db.get(ReportJob, job_id)
            assert job is not None
            job.status = ReportStatus.COMPLETED.value
            job.file_name = file_name
            job.summary = jsonable_encoder(summary)
            job.completed_at = clock.now()
            db.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("report_failed", extra={"job_id": str(job_id)})
            db.rollback()
            job = db.get(ReportJob, job_id)
            if job is not None:
                job.status = ReportStatus.FAILED.value
                job.error = type(exc).__name__
                job.completed_at = clock.now()
                db.commit()
