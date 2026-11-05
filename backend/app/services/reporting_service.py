"""Excel reporting: one streaming pass per worksheet, written with the in-house streaming writer.

Sheets: Dashboard, Family Bookings, Family Members, Session Attendance,
Kund Allocation, Cancellations, No Shows.

* DAILY reports cover the sessions of one event date; FINAL covers all.
* No-shows are computed ONLY for sessions whose scheduled end time has
  passed; other sessions are listed as "not completed".
* Reports are read-only views; nothing is deleted. Excel exports are not
  backups (see docs/operations-runbook.md for pg_dump based backups).
* Cell values that start with = + - @ are prefixed with ' to prevent
  spreadsheet formula injection from user-entered text (done by the writer).

Performance notes (measured, see docs/report-performance.md)
* The workbook writer is the dominant cost on a CPU-starved host, so it is a purpose-built streaming
  writer (app/services/xlsx_stream.py), ~15x cheaper than openpyxl for the same sheets.
* Queries select plain columns (no ORM entities) and aggregate "families per Kund" and
  "sessions per booking" inside PostgreSQL, so Python only moves rows.
* Every stage is timed by :class:`StageTimer`; timings contain stage names, seconds and row counts only.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
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
from app.services.xlsx_stream import SheetWriter, XlsxStream

logger = logging.getLogger("app.reports")

# Rows fetched per round trip (server-side cursor). Larger batches mean fewer network round trips to a
# remote database; 10k rows of the widest report query is only a few MB.
_STREAM = {"yield_per": 10_000}

# Layout shown on passes: 11 zones x 5 sectors (sectors 1-4 = 39 kunds, sector 5 = the rest of the zone).
_ZONES = ["Brahma", "Vishnu", "Shiva", "Surya", "Ganesha", "Durga", "Lakshmi", "Saraswati", "Hanuman", "Indra", "Agni"]
_PER_ZONE = 196


def zone_sector(kund_number: int) -> tuple[str, int]:
    """Same mapping as the frontend (src/lib/db.js): returns ("Brahma", 1..5)."""
    z = min(len(_ZONES) - 1, (kund_number - 1) // _PER_ZONE)
    o = (kund_number - 1) % _PER_ZONE
    return _ZONES[z], (5 if o >= 156 else o // 39 + 1)
# A job that is still PENDING/RUNNING after this long is considered abandoned (e.g. the instance was
# restarted mid-run) and is reported as FAILED instead of "preparing" forever.
JOB_TIMEOUT = timedelta(minutes=15)
# Finished report files are removed after this long: disks on small hosts are ephemeral and tiny.
FILE_RETENTION = timedelta(hours=1)


_now = time.perf_counter


class StageTimer:
    """Wall-clock time per stage plus row counts. Records ONLY stage names, seconds and counts:
    never row contents, so it cannot leak personal data into logs."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self._section: str | None = None
        self._section_start = 0.0
        self._on_end: Any = None

    def on_end(self, callback: Any) -> None:
        """Run ``callback`` when the current section ends (used to publish per-sheet counters once)."""
        self._on_end = callback

    def add(self, key: str, seconds: float) -> None:
        self.seconds[key] = self.seconds.get(key, 0.0) + seconds

    @contextmanager
    def stage(self, key: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add(key, time.perf_counter() - t0)

    def begin(self, section: str) -> None:
        """Start a worksheet section; its total wall time is recorded as '<section>.total'."""
        self.end()
        self._section, self._section_start = section, time.perf_counter()

    def end(self) -> None:
        if self._section:
            self.add(f"{self._section}.total", time.perf_counter() - self._section_start)
            self._section = None
            if self._on_end is not None:
                self._on_end()
                self._on_end = None

    def rows(self, key: str, db: Session, stmt: Any) -> Iterator[Any]:
        """Run a query and iterate its rows, attributing time spent waiting on the database to '<key>.db'.

        Time is accumulated in a local and recorded once: per-row bookkeeping would itself cost real CPU on
        a throttled host and distort the measurement."""
        clock_ = time.perf_counter
        t0 = clock_()
        result = db.execute(stmt)
        waited = clock_() - t0
        it = iter(result)
        try:
            while True:
                t0 = clock_()
                try:
                    row = next(it)
                except StopIteration:
                    waited += clock_() - t0
                    return
                waited += clock_() - t0
                yield row
        finally:
            self.add(f"{key}.db", waited)

    def report(self) -> dict[str, Any]:
        return {"seconds": {k: round(v, 3) for k, v in sorted(self.seconds.items())}, "rows": dict(self.counts)}


class _Sheet:
    """A worksheet plus its timing bookkeeping."""

    def __init__(self, book: XlsxStream, title: str, headers: list[str], widths: list[int],
                 timer: StageTimer, key: str) -> None:
        self.timer, self.key = timer, key
        self.write_s = 0.0
        timer.begin(key)
        self.writer: SheetWriter = book.sheet(title, headers, widths)
        self._append = self.writer.append
        timer.on_end(self._record)

    def add(self, values: list[Any]) -> None:
        t0 = _now()
        self._append(values)
        self.write_s += _now() - t0

    def _record(self) -> None:
        self.timer.add(f"{self.key}.write", self.write_s)

    @property
    def rows(self) -> int:
        return self.writer.rows


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
        cap = {
            sid: (int(c), int(r), int(used))
            for sid, c, r, used in db.execute(
                select(KundSessionCapacity.session_id, func.sum(KundSessionCapacity.capacity),
                       func.sum(KundSessionCapacity.reserved_count),
                       func.count().filter(KundSessionCapacity.reserved_count > 0))
                .where(KundSessionCapacity.session_id.in_(ids))
                .group_by(KundSessionCapacity.session_id)
            )
        }
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
        out = []
        for s in sessions:
            capacity, reserved, kunds_used = cap.get(s.id, (0, 0, 0))
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
                    "kunds_in_use": kunds_used,
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
    def build_workbook(self, path: Path, report_type: str, report_date: date | None,
                       timer: StageTimer | None = None) -> dict[str, Any]:
        """Write the 7-sheet workbook to ``path`` (atomically) and return a summary of what it contains."""
        timer = timer or StageTimer()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            result = self._write(tmp, report_type, report_date, timer)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return result

    def _write(self, tmp: Path, report_type: str, report_date: date | None, timer: StageTimer) -> dict[str, Any]:
        db = self.db
        # Every report query is read to the end through a server-side cursor (yield_per). With PostgreSQL's
        # default cursor_tuple_fraction (0.1) the planner then prefers "fast first rows" nested-loop plans:
        # measured 5.4 s instead of 0.8 s for the No Shows query at event scale. SET LOCAL is transaction
        # scoped, so it is safe behind the Supabase transaction pooler and does not leak to other requests.
        db.execute(text("SET LOCAL cursor_tuple_fraction = 1.0"))
        with timer.stage("scope.db"):
            sessions = self._sessions_in_scope(report_type, report_date)
        ids = [s.id for s in sessions]
        where_dates = {s.id: (s.event_date, s.slot) for s in sessions}
        timer.begin("dashboard")
        with timer.stage("dashboard.db"):
            summary = self.session_summary(sessions)
            in_scope = select(BookingSession.booking_id).where(BookingSession.session_id.in_(ids))
            n_bookings, n_confirmed, n_unique, n_members = db.execute(
                select(
                    select(func.count()).select_from(Booking).where(Booking.id.in_(in_scope)).scalar_subquery(),
                    select(func.count()).select_from(Booking)
                    .where(Booking.id.in_(in_scope), Booking.status == "CONFIRMED").scalar_subquery(),
                    select(func.count(func.distinct(Booking.primary_mobile)))
                    .where(Booking.id.in_(in_scope), Booking.status == "CONFIRMED").scalar_subquery(),
                    select(func.count()).select_from(FamilyMember)
                    .where(FamilyMember.booking_id.in_(in_scope)).scalar_subquery(),
                )
            ).one()

        totals = {
            "Report type": report_type,
            "Report date": report_date.isoformat() if report_date else "All event days",
            "Generated at (IST)": clock.now(),
            "Total family bookings": n_bookings,
            "Confirmed family bookings": n_confirmed,
            "Unique families (distinct primary mobile, confirmed)": n_unique,
            "Total unique registered members": n_members,
            "Family-session reservations (confirmed)": sum(r["confirmed_families"] for r in summary),
            "Attendee-session reservations (confirmed)": sum(r["registered_members"] for r in summary),
            "Actual check-ins": sum(r["checkins"] for r in summary),
            "No-shows (completed sessions only)": sum(r["no_shows"] or 0 for r in summary),
            "Sessions not yet completed": sum(1 for r in summary if not r["completed"]),
            "Total capacity": sum(r["capacity"] for r in summary),
            "Remaining capacity": sum(r["remaining"] for r in summary),
            "Cancelled family reservations": sum(r["cancelled_families"] for r in summary),
            "Cancelled attendee places": sum(r["cancelled_members"] for r in summary),
        }
        counts: dict[str, int] = {}
        with XlsxStream(tmp, tz=clock.event_tz()) as book:
            # 1. Dashboard
            dash = _Sheet(book, "Dashboard", ["Metric", "Value"], [52, 30], timer, "dashboard")
            for k, v in totals.items():
                dash.add([k, v])
            dash.add([])
            dash.add(["Session-wise", ""])
            dash.add(
                [
                    "Session", "Date", "Slot", "Time (IST)", "Families", "Members reserved", "Capacity", "Remaining",
                    "Kunds in use", "Utilisation %", "Check-ins", "No-shows", "Cancelled families",
                    "Cancelled members",
                ]
            )
            for r in summary:
                dash.add(
                    [
                        r["session_id"], r["event_date"], r["slot"], r["time"], r["confirmed_families"],
                        r["registered_members"], r["capacity"], r["remaining"], r["kunds_in_use"],
                        r["utilisation_percent"], r["checkins"],
                        r["no_shows"] if r["completed"] else "Session not completed",
                        r["cancelled_families"], r["cancelled_members"],
                    ]
                )

            # 2. Family Bookings (sessions per booking aggregated by PostgreSQL)
            fb = _Sheet(
                book, "Family Bookings",
                ["Booking number", "Status", "Coordinator", "Primary mobile", "Secondary mobile", "Email", "Address",
                 "City", "State", "Pincode", "Gotra", "Sankalp purpose", "Members", "Sessions (session:kund:status)",
                 "Created at", "Cancelled at"],
                [16, 11, 24, 14, 14, 26, 30, 14, 16, 9, 14, 30, 8, 40, 20, 20], timer, "family_bookings",
            )
            sessions_per_booking = (
                select(
                    BookingSession.booking_id.label("booking_id"),
                    func.string_agg(
                        func.concat(BookingSession.session_id, ":K", Kund.kund_number, ":",
                                    func.left(BookingSession.status, 1)),
                        aggregate_order_by(literal_column("', '"), BookingSession.session_id),
                    ).label("sessions"),
                )
                .join(Kund, Kund.id == BookingSession.kund_id)
                .where(BookingSession.session_id.in_(ids))
                .group_by(BookingSession.booking_id)
                .subquery()
            )
            for row in timer.rows(
                "family_bookings", db,
                select(Booking.booking_number, Booking.status, Booking.coordinator_name, Booking.primary_mobile,
                       Booking.secondary_mobile, Booking.email, Booking.address, Booking.city, Booking.state,
                       Booking.pincode, Booking.gotra, Booking.sankalp_purpose, Booking.member_count,
                       func.coalesce(sessions_per_booking.c.sessions, ""), Booking.created_at, Booking.cancelled_at)
                .outerjoin(sessions_per_booking, sessions_per_booking.c.booking_id == Booking.id)
                .where(Booking.id.in_(in_scope))
                .order_by(Booking.id)
                .execution_options(**_STREAM),
            ):
                fb.add(row)

            # 3. Family Members
            fm = _Sheet(book, "Family Members",
                        ["Booking number", "Member #", "Full name", "Age", "Gender", "Relationship", "Booking status"],
                        [16, 9, 30, 6, 9, 14, 14], timer, "family_members")
            for row in timer.rows(
                "family_members", db,
                select(Booking.booking_number, FamilyMember.member_number, FamilyMember.full_name, FamilyMember.age,
                       FamilyMember.gender, FamilyMember.relationship_, Booking.status)
                .join(Booking, Booking.id == FamilyMember.booking_id)
                .where(Booking.id.in_(in_scope))
                .order_by(Booking.id, FamilyMember.member_number)
                .execution_options(**_STREAM),
            ):
                fm.add(row)

            # 4. Session Attendance (one row per member per reservation)
            sa = _Sheet(
                book, "Session Attendance",
                ["Session", "Date", "Slot", "Booking number", "Zone", "Sector", "Kund", "Member #", "Full name",
                 "Reservation status", "Checked in", "Checked in at", "Source", "Scanned by", "Scanner email"],
                [8, 11, 9, 16, 12, 7, 7, 9, 28, 12, 10, 20, 12, 24, 28], timer, "session_attendance",
            )
            for sid, bn, kn, mn, name, rst, at, src, scan_name, scan_email in timer.rows(
                "session_attendance", db,
                select(BookingSession.session_id, Booking.booking_number, Kund.kund_number,
                       FamilyMember.member_number, FamilyMember.full_name, BookingSession.status,
                       AttendanceCheckin.checked_in_at, AttendanceCheckin.source, AdminUser.full_name, AdminUser.email)
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
                .execution_options(**_STREAM),
            ):
                d, slot = where_dates[sid]
                sa.add([sid, d, slot, bn, *zone_sector(kn), kn, mn, name, rst, "YES" if at else "NO", at, src,
                        scan_name if at else None, scan_email if at else None])

            # 5. Kund Allocation: one row per Kund per session (empty Kunds included), families aggregated in SQL
            ka = _Sheet(
                book, "Kund Allocation",
                ["Session", "Date", "Slot", "Zone", "Sector", "Kund", "Kund active", "Capacity", "Reserved", "Remaining",
                 "Utilisation %", "Families (booking:members)"],
                [8, 11, 9, 12, 7, 7, 10, 9, 9, 10, 12, 50], timer, "kund_allocation",
            )
            families = (
                select(
                    BookingSession.session_id.label("session_id"),
                    BookingSession.kund_id.label("kund_id"),
                    func.string_agg(
                        func.concat(Booking.booking_number, ":", BookingSession.member_count),
                        aggregate_order_by(literal_column("', '"), BookingSession.id),
                    ).label("families"),
                )
                .join(Booking, Booking.id == BookingSession.booking_id)
                .where(BookingSession.session_id.in_(ids), BookingSession.status == "CONFIRMED")
                .group_by(BookingSession.session_id, BookingSession.kund_id)
                .subquery()
            )
            for sid, kn, active, cap, reserved, fams in timer.rows(
                "kund_allocation", db,
                select(KundSessionCapacity.session_id, Kund.kund_number, Kund.is_active, KundSessionCapacity.capacity,
                       KundSessionCapacity.reserved_count, func.coalesce(families.c.families, ""))
                .join(Kund, Kund.id == KundSessionCapacity.kund_id)
                .outerjoin(families, (families.c.session_id == KundSessionCapacity.session_id)
                           & (families.c.kund_id == KundSessionCapacity.kund_id))
                .where(KundSessionCapacity.session_id.in_(ids))
                .order_by(KundSessionCapacity.session_id, Kund.kund_number)
                .execution_options(**_STREAM),
            ):
                d, slot = where_dates[sid]
                ka.add([sid, d, slot, *zone_sector(kn), kn, "YES" if active else "NO", cap, reserved, cap - reserved,
                        round(100 * reserved / cap, 1), fams])

            # 6. Cancellations
            cx = _Sheet(
                book, "Cancellations",
                ["Booking number", "Session", "Date", "Slot", "Kund", "Released members", "Reason", "Cancelled at",
                 "Actor id"],
                [16, 8, 11, 9, 7, 10, 40, 20, 38], timer, "cancellations",
            )
            for bn, sid, kn, released, reason, at, actor in timer.rows(
                "cancellations", db,
                select(Booking.booking_number, CancellationEvent.session_id, Kund.kund_number,
                       CancellationEvent.released_member_count, CancellationEvent.reason,
                       CancellationEvent.created_at, CancellationEvent.actor_id)
                .join(Booking, Booking.id == CancellationEvent.booking_id)
                .join(Kund, Kund.id == CancellationEvent.kund_id)
                .where(CancellationEvent.session_id.in_(ids))
                .order_by(CancellationEvent.id)
                .execution_options(**_STREAM),
            ):
                d, slot = where_dates[sid]
                cx.add([bn, sid, d, slot, kn, released, reason, at, actor])

            # 7. No Shows (completed sessions only)
            ns = _Sheet(
                book, "No Shows",
                ["Session", "Date", "Slot", "Booking number", "Kund", "Member #", "Full name", "Coordinator",
                 "Coordinator mobile"],
                [8, 11, 9, 16, 7, 9, 28, 24, 16], timer, "no_shows",
            )
            completed_ids = [s.id for s in sessions if session_service.is_completed(s)]
            for s in sessions:
                if s.id not in completed_ids:
                    ns.add([s.id, s.event_date, s.slot, "Session not completed - no-shows not calculated"])
            if completed_ids:
                for sid, bn, kn, mn, name, coord, mob in timer.rows(
                    "no_shows", db,
                    select(BookingSession.session_id, Booking.booking_number, Kund.kund_number,
                           FamilyMember.member_number, FamilyMember.full_name, Booking.coordinator_name,
                           Booking.primary_mobile)
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
                    .execution_options(**_STREAM),
                ):
                    d, slot = where_dates[sid]
                    ns.add([sid, d, slot, bn, kn, mn, name, coord, mob])

            timer.end()
            counts = {"family_bookings": fb.rows, "family_members": fm.rows, "session_attendance": sa.rows,
                      "kund_allocation": ka.rows, "cancellations": cx.rows, "no_shows": ns.rows}
            timer.counts = counts
            with timer.stage("finalize"):  # last sheet trailer + workbook parts are written on leaving the block
                pass
        return {
            "sessions": summary,
            "totals": {k: (v.isoformat() if isinstance(v, datetime | date) else v) for k, v in totals.items()},
            "row_counts": counts,
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
        _delete_old_files()
        return job

    def get_job(self, job_id: uuid.UUID) -> ReportJob:
        job = self.db.get(ReportJob, job_id)
        if job is None:
            raise NotFound("Report job not found")
        if (job.status in (ReportStatus.PENDING.value, ReportStatus.RUNNING.value)
                and clock.now() - job.created_at > JOB_TIMEOUT):
            # The worker died (restart/deploy) or is hopelessly slow: stop reporting "preparing".
            job.status = ReportStatus.FAILED.value
            job.error = "ABANDONED"
            job.completed_at = clock.now()
            self.db.commit()
            logger.warning("report_abandoned", extra={"job_id": str(job.id)})
        return job

    def job_file(self, job: ReportJob) -> Path:
        if job.status != ReportStatus.COMPLETED.value or not job.file_name:
            raise NotFound("Report is not ready", code="REPORT_NOT_READY", status_code=409)
        path = storage_path(job)
        if not path.is_file():
            # Report files live on the instance's ephemeral disk: after a restart or the retention window
            # the file is gone and the report has to be generated again.
            raise NotFound("Report file is no longer available. Please generate it again.",
                           code="REPORT_EXPIRED", status_code=410)
        return path


def storage_path(job: ReportJob) -> Path:
    """Where the workbook is stored on disk (unique per job)."""
    return Path(get_settings().REPORTS_DIR) / f"{job.id.hex}.xlsx"


def download_name(job: ReportJob) -> str:
    """Human-friendly file name, e.g. Mahayagya_Registration_Report_20261105.xlsx."""
    if job.report_type == ReportType.DAILY.value and job.report_date:
        return f"Mahayagya_Daily_Report_{job.report_date:%Y%m%d}.xlsx"
    return f"Mahayagya_Registration_Report_{clock.now().astimezone(clock.event_tz()):%Y%m%d}.xlsx"


def _delete_old_files() -> None:
    """Remove finished/abandoned report files older than FILE_RETENTION (best effort)."""
    directory = Path(get_settings().REPORTS_DIR)
    if not directory.is_dir():
        return
    cutoff = time.time() - FILE_RETENTION.total_seconds()
    for f in directory.glob("*.xlsx"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            continue
    for f in directory.glob("*.tmp"):  # leftovers of a crashed run
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            continue


def run_report_job(job_id: uuid.UUID, request_id: str | None = None) -> None:
    """Background worker entry point (own DB session). Logs one structured line with the stage timings."""
    t_start = time.perf_counter()
    timer = StageTimer()
    with get_sessionmaker()() as db:
        t0 = time.perf_counter()
        job = db.get(ReportJob, job_id)  # pool checkout + first round trip
        timer.add("connect", time.perf_counter() - t0)
        if job is None:
            return
        queue_s = (clock.now() - job.created_at).total_seconds()
        job.status = ReportStatus.RUNNING.value
        job.started_at = clock.now()
        db.commit()
        report_type, report_date = job.report_type, job.report_date
        file_name = download_name(job)
        try:
            summary = ReportingService(db).build_workbook(storage_path(job), report_type, report_date, timer)
            db.rollback()
            size = storage_path(job).stat().st_size
            total_s = time.perf_counter() - t_start
            report = timer.report()
            summary["timings"] = {"total_s": round(total_s, 3), "queue_s": round(queue_s, 3),
                                  "size_bytes": size, **report}
            job = db.get(ReportJob, job_id)
            assert job is not None
            job.status = ReportStatus.COMPLETED.value
            job.file_name = file_name
            job.summary = jsonable_encoder(summary)
            job.completed_at = clock.now()
            db.commit()
            logger.info(
                "report_generated",
                extra={"request_id": request_id, "job_id": str(job_id), "report_type": report_type, "status": "ok",
                       "total_s": round(total_s, 3), "queue_s": round(queue_s, 3), "size_bytes": size,
                       "stages_s": report["seconds"], "rows": report["rows"]},
            )
        except Exception as exc:
            total_s = time.perf_counter() - t_start
            logger.exception(
                "report_failed",
                extra={"request_id": request_id, "job_id": str(job_id), "report_type": report_type,
                       "status": "failed", "error_type": type(exc).__name__, "total_s": round(total_s, 3),
                       "stages_s": timer.report()["seconds"]},
            )
            db.rollback()
            job = db.get(ReportJob, job_id)
            if job is not None:
                job.status = ReportStatus.FAILED.value
                job.error = type(exc).__name__
                job.completed_at = clock.now()
                db.commit()
