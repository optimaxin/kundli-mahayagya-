"""Scanner workflow: scan family pass -> roster -> per-member check-in.

Security rules implemented here:
* For SCANNER accounts the session is ALWAYS derived from the account
  (``admin_users.assigned_session_id``); a client-supplied session is refused
  at the API layer. ADMIN/SUPERVISOR (trusted staff, e.g. the admin console's
  scanner tab) must name the session explicitly; every check-in records who
  made it.
* The pass is re-validated on every check-in call (no client-side trust).
* A pass can be presented as the QR payload (normal) or, as a fallback when a
  camera fails, as the printed booking number. The fallback still requires the
  booking to hold an active pass, is rate-limited per scanner, and the roster
  shown lets the volunteer verify names against photo ID.
* The member must belong to the booking (also enforced by a composite FK).
* Duplicate check-ins are prevented by UNIQUE(booking_session_id, member_id);
  concurrent scans of the same member resolve to exactly one success.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.database import run_transaction
from app.core.errors import Conflict, NotFound
from app.models import (
    AdminUser,
    AttendanceCheckin,
    Booking,
    BookingSession,
    EventSession,
    FamilyMember,
    Kund,
)
from app.models.enums import BookingStatus, CheckinResult, CheckinSource, ReservationStatus, Role
from app.repositories.booking_repository import BookingRepository
from app.repositories.misc_repositories import QrRepository
from app.repositories.session_repository import SessionRepository
from app.services import session_service
from app.services.audit_service import RequestContext, audit
from app.services.qr_service import QrService
from app.utils.identifiers import mask_mobile, normalize_booking_number


@dataclass
class _Resolved:
    session: EventSession
    booking: Booking
    reservation: BookingSession
    kund_number: int


def _session_out(s: EventSession) -> dict[str, Any]:
    return {
        "session_id": s.id,
        "event_date": s.event_date,
        "slot": s.slot,
        "start_time": s.start_time,
        "end_time": s.end_time,
    }


class CheckinService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------ resolve
    def _target_session(self, user: AdminUser, session_id: int | None) -> EventSession | dict[str, Any]:
        sid = user.assigned_session_id if user.role == Role.SCANNER.value else session_id
        if sid is None:
            return {"status": CheckinResult.INVALID_SESSION, "reason": "SCANNER_UNASSIGNED",
                    "message": "This scanner is not assigned to a session"}
        session = SessionRepository(self.db).get(sid)
        if session is None or not session.is_active or session.status == "CANCELLED":
            return {"status": CheckinResult.INVALID_SESSION, "reason": "SESSION_INACTIVE",
                    "message": "The session is not active"}
        return session

    def _booked_sessions(self, booking_id: int) -> list[dict[str, Any]]:
        return [
            {"session_id": r["session_id"], "event_date": r["event_date"], "slot": r["slot"], "status": r["status"]}
            for r in BookingRepository(self.db).reservations_detailed(booking_id)
        ]

    def _resolve(
        self, user: AdminUser, *, qr_payload: str | None, booking_number: str | None, session_id: int | None
    ) -> _Resolved | dict[str, Any]:
        session = self._target_session(user, session_id)
        if isinstance(session, dict):
            return session
        so = _session_out(session)

        booking: Booking | None
        if qr_payload is not None:
            found = QrService(self.db).lookup(qr_payload)
            booking = found.booking if found.found else None
            if booking is None:
                return {"status": CheckinResult.INVALID_QR, "reason": "UNKNOWN_PASS",
                        "message": "QR code is not recognised", "session": so}
            pass_usable = found.usable
        else:
            booking = BookingRepository(self.db).get_by_number(normalize_booking_number(booking_number or ""))
            if booking is None:
                return {"status": CheckinResult.INVALID_QR, "reason": "UNKNOWN_PASS",
                        "message": "Pass ID is not recognised", "session": so}
            active = QrRepository(self.db).active_for_booking(booking.id)
            pass_usable = bool(active and active.expires_at > clock.now())

        base = {"session": so, "booking_number": booking.booking_number, "coordinator_name": booking.coordinator_name,
                "member_count": booking.member_count}
        if booking.status == BookingStatus.CANCELLED.value:
            return {**base, "status": CheckinResult.BOOKING_CANCELLED, "reason": "BOOKING_CANCELLED",
                    "message": "This booking has been cancelled"}
        if not pass_usable:
            return {**base, "status": CheckinResult.INVALID_QR, "reason": "PASS_REVOKED",
                    "message": "This pass has been revoked or has expired"}

        reservation = BookingRepository(self.db).reservation_for_session(booking.id, session.id)
        if reservation is None:
            return {**base, "status": CheckinResult.INVALID_SESSION, "reason": "NO_RESERVATION",
                    "message": "This family has no reservation for the current session",
                    "booked_sessions": self._booked_sessions(booking.id)}
        if reservation.status != ReservationStatus.CONFIRMED.value:
            return {**base, "status": CheckinResult.BOOKING_CANCELLED, "reason": "RESERVATION_CANCELLED",
                    "message": "This family's reservation for the current session was cancelled"}
        if not session_service.checkin_window_open(session):
            completed = session_service.is_completed(session)
            return {**base, "status": CheckinResult.INVALID_SESSION,
                    "reason": "SESSION_OVER" if completed else "SESSION_NOT_OPEN",
                    "message": "The session is over" if completed else "Check-in is not open yet for this session",
                    "booked_sessions": self._booked_sessions(booking.id)}
        kund = self.db.get(Kund, reservation.kund_id)
        return _Resolved(session=session, booking=booking, reservation=reservation,
                         kund_number=kund.kund_number if kund else 0)

    def _roster(self, booking_id: int, reservation_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(FamilyMember.member_number, FamilyMember.full_name, FamilyMember.age, FamilyMember.gender,
                   AttendanceCheckin.checked_in_at)
            .outerjoin(
                AttendanceCheckin,
                (AttendanceCheckin.member_id == FamilyMember.id)
                & (AttendanceCheckin.booking_session_id == reservation_id),
            )
            .where(FamilyMember.booking_id == booking_id)
            .order_by(FamilyMember.member_number)
        )
        return [
            {"member_number": n, "full_name": name, "age": age, "gender": gender,
             "checked_in": at is not None, "checked_in_at": at}
            for n, name, age, gender, at in self.db.execute(stmt)
        ]

    # --------------------------------------------------------------- scan
    def scan(
        self, user: AdminUser, qr_payload: str | None = None, *, booking_number: str | None = None,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        try:
            r = self._resolve(user, qr_payload=qr_payload, booking_number=booking_number, session_id=session_id)
            if isinstance(r, dict):
                return r
            roster = self._roster(r.booking.id, r.reservation.id)
            done = sum(1 for m in roster if m["checked_in"])
            return {
                "status": CheckinResult.VALID,
                "reason": "ALL_CHECKED_IN" if done == len(roster) else None,
                "message": "Pass valid. Select each family member as they enter.",
                "session": _session_out(r.session),
                "booking_number": r.booking.booking_number,
                "coordinator_name": r.booking.coordinator_name,
                "primary_mobile_masked": mask_mobile(r.booking.primary_mobile),
                "kund_number": r.kund_number,
                "member_count": r.booking.member_count,
                "checked_in_count": done,
                "roster": roster,
            }
        finally:
            self.db.rollback()  # read-only; release the snapshot

    # ------------------------------------------------------------ checkin
    def checkin(
        self,
        user: AdminUser,
        qr_payload: str | None,
        member_number: int,
        event_id: uuid.UUID | None = None,
        *,
        booking_number: str | None = None,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        event_id = event_id or uuid.uuid4()

        def work(db: Session) -> dict[str, Any]:
            r = self._resolve(user, qr_payload=qr_payload, booking_number=booking_number, session_id=session_id)
            if isinstance(r, dict):
                return r
            member = db.scalars(
                select(FamilyMember).where(
                    FamilyMember.booking_id == r.booking.id, FamilyMember.member_number == member_number
                )
            ).first()
            base = {
                "booking_number": r.booking.booking_number,
                "kund_number": r.kund_number,
                "member_count": r.booking.member_count,
            }
            if member is None:
                return {**base, "status": CheckinResult.INVALID_MEMBER, "reason": "INVALID_MEMBER",
                        "message": "This member does not belong to the scanned family", "member_number": member_number}
            now = clock.now()
            inserted = db.execute(
                pg_insert(AttendanceCheckin)
                .values(
                    event_id=event_id,
                    booking_session_id=r.reservation.id,
                    booking_id=r.booking.id,
                    member_id=member.id,
                    scanner_id=user.id,
                    source=CheckinSource.ONLINE.value,
                    checked_in_at=now,
                )
                .on_conflict_do_nothing()
                .returning(AttendanceCheckin.id)
            ).scalar_one_or_none()

            existing = None
            if inserted is None:
                existing = db.scalars(
                    select(AttendanceCheckin).where(
                        AttendanceCheckin.booking_session_id == r.reservation.id,
                        AttendanceCheckin.member_id == member.id,
                    )
                ).first()
                if existing is None:
                    raise Conflict("event_id was already used for a different check-in", code="EVENT_ID_REUSED")
            roster = self._roster(r.booking.id, r.reservation.id)
            common = {
                **base,
                "member_number": member.member_number,
                "full_name": member.full_name,
                "checked_in_count": sum(1 for m in roster if m["checked_in"]),
            }
            if inserted is not None or (existing is not None and existing.event_id == event_id):
                return {
                    **common,
                    "status": CheckinResult.CHECKIN_SUCCESS,
                    "message": f"Member {member.member_number} checked in",
                    "checked_in_at": existing.checked_in_at if existing else now,
                    "event_id": existing.event_id if existing else event_id,
                }
            assert existing is not None
            return {
                **common,
                "status": CheckinResult.ALREADY_CHECKED_IN,
                "message": f"Member {member.member_number} was already checked in for this session",
                "checked_in_at": existing.checked_in_at,
                "event_id": existing.event_id,
            }

        return run_transaction(self.db, work, label="checkin")

    # ----------------------------------------------------- manual (staff)
    def manual_checkin(
        self, booking_number: str, session_id: int, member_numbers: list[int] | None, staff: AdminUser,
        ctx: RequestContext,
    ) -> dict[str, Any]:
        """Organiser marks members present without a scan (help desk / correction). Audited."""

        def work(db: Session) -> dict[str, Any]:
            repo = BookingRepository(db)
            booking = repo.get_by_number(booking_number)
            if booking is None:
                raise NotFound("Booking not found")
            reservation = repo.reservation_for_session(booking.id, session_id)
            if reservation is None:
                raise NotFound("The booking has no reservation for this session", code="INVALID_SESSION")
            if (reservation.status != ReservationStatus.CONFIRMED.value
                    or booking.status != BookingStatus.CONFIRMED.value):
                raise Conflict("The reservation is cancelled", code="BOOKING_CANCELLED")
            session = SessionRepository(db).get(session_id)
            assert session is not None
            settings_open = session_service.starts_at(session) - _checkin_lead()
            if clock.now() < settings_open:
                raise Conflict("Entry cannot be marked before the session's check-in window opens",
                               code="SESSION_NOT_OPEN")
            members = repo.members(booking.id)
            wanted = {m.member_number for m in members} if not member_numbers else set(member_numbers)
            unknown = wanted - {m.member_number for m in members}
            if unknown:
                raise NotFound("Unknown member number(s)", code="INVALID_MEMBER", details={"members": sorted(unknown)})
            newly: list[int] = []
            now = clock.now()
            for m in members:
                if m.member_number not in wanted:
                    continue
                inserted = db.execute(
                    pg_insert(AttendanceCheckin)
                    .values(event_id=uuid.uuid4(), booking_session_id=reservation.id, booking_id=booking.id,
                            member_id=m.id, scanner_id=staff.id, source=CheckinSource.ONLINE.value,
                            checked_in_at=now)
                    .on_conflict_do_nothing()
                    .returning(AttendanceCheckin.id)
                ).scalar_one_or_none()
                if inserted is not None:
                    newly.append(m.member_number)
            audit(db, ctx, action="MANUAL_CHECKIN", entity_type="booking", entity_id=booking.booking_number,
                  new={"session_id": session_id, "members": newly})
            roster = self._roster(booking.id, reservation.id)
            return {
                "booking_number": booking.booking_number,
                "session_id": session_id,
                "checked_in": newly,
                "already_checked_in": sorted(wanted - set(newly)),
                "checked_in_count": sum(1 for x in roster if x["checked_in"]),
                "member_count": booking.member_count,
            }

        return run_transaction(self.db, work, label="manual_checkin")

    # ------------------------------------------------------------- helpers
    def recent(self, user: AdminUser, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(AttendanceCheckin.checked_in_at, AttendanceCheckin.event_id, Booking.booking_number,
                   Booking.coordinator_name, Booking.member_count, BookingSession.session_id, Kund.kund_number,
                   FamilyMember.member_number, FamilyMember.full_name)
            .join(Booking, Booking.id == AttendanceCheckin.booking_id)
            .join(BookingSession, BookingSession.id == AttendanceCheckin.booking_session_id)
            .join(Kund, Kund.id == BookingSession.kund_id)
            .join(FamilyMember, FamilyMember.id == AttendanceCheckin.member_id)
            .where(AttendanceCheckin.scanner_id == user.id)
            .order_by(AttendanceCheckin.checked_in_at.desc(), AttendanceCheckin.id.desc())
            .limit(min(max(limit, 1), 50))
        ).all()
        return [
            {"checked_in_at": at, "event_id": eid, "booking_number": bn, "coordinator_name": cn,
             "member_count": mc, "session_id": sid, "kund_number": kn, "member_number": mn, "full_name": name}
            for at, eid, bn, cn, mc, sid, kn, mn, name in rows
        ]

    def scanner_me(self, scanner: AdminUser) -> dict[str, Any]:
        session = SessionRepository(self.db).get(scanner.assigned_session_id) if scanner.assigned_session_id else None
        return {
            "user_id": scanner.id,
            "full_name": scanner.full_name,
            "role": scanner.role,
            "session": _session_out(session) if session else None,
            "checkin_window_open": bool(session and session_service.checkin_window_open(session)),
        }


def _checkin_lead():  # type: ignore[no-untyped-def]
    from datetime import timedelta

    from app.core.config import get_settings

    return timedelta(minutes=get_settings().CHECKIN_OPENS_MINUTES_BEFORE)
