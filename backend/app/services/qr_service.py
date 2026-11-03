"""Family QR passes.

* One opaque random token per family (>= 32 bytes CSPRNG entropy).
* Only SHA-256(token) is stored; the raw token is shown once.
* The QR encodes ``<prefix><token>`` -- no personal data, no database ids.
* Exactly one ACTIVE pass per booking (partial unique index); regeneration
  revokes the previous pass atomically.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import segno
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import get_settings
from app.core.database import run_transaction
from app.core.errors import NotFound
from app.models import Booking, QrPass
from app.models.enums import BookingStatus, ReservationStatus
from app.repositories.booking_repository import BookingRepository
from app.repositories.misc_repositories import QrRepository
from app.services import session_service
from app.services.audit_service import RequestContext, audit
from app.utils.identifiers import mask_mobile


@dataclass(frozen=True)
class IssuedPass:
    token: str
    qr_payload: str
    expires_at: datetime
    pass_id: int


class PassLookup:
    """Result of resolving a scanned/submitted token."""

    def __init__(self, qr_pass: QrPass | None, booking: Booking | None) -> None:
        self.qr_pass = qr_pass
        self.booking = booking

    @property
    def found(self) -> bool:
        return self.qr_pass is not None and self.booking is not None

    @property
    def usable(self) -> bool:
        return bool(self.found and self.qr_pass.is_active and self.qr_pass.expires_at > clock.now())  # type: ignore[union-attr]


def pass_expiry() -> datetime:
    return session_service.last_event_day_end() + timedelta(days=get_settings().QR_PASS_VALID_DAYS_AFTER_EVENT)


class QrService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = QrRepository(db)
        self.bookings = BookingRepository(db)

    # ------------------------------------------------------------ issuing
    def issue(self, booking_id: int, *, actor_id=None, revoke_reason: str = "REGENERATED") -> IssuedPass:  # type: ignore[no-untyped-def]
        """Create a new active pass (revoking any existing one). Runs in the caller's transaction."""
        self.repo.deactivate_for_booking(booking_id, actor_id=actor_id, reason=revoke_reason)
        token = security.generate_qr_token()
        expires = pass_expiry()
        pass_id = self.repo.insert(
            booking_id=booking_id, token_hash=security.hash_token(token), expires_at=expires, actor_id=actor_id
        )
        return IssuedPass(token=token, qr_payload=security.qr_payload_for(token), expires_at=expires, pass_id=pass_id)

    def regenerate(self, booking_number: str, ctx: RequestContext) -> tuple[Booking, IssuedPass]:
        def work(db: Session) -> tuple[Booking, IssuedPass]:
            booking = self.bookings.get_by_number(booking_number, for_update=True)
            if booking is None:
                raise NotFound("Booking not found")
            if booking.status != BookingStatus.CONFIRMED.value:
                raise NotFound("Booking is not active", code="BOOKING_CANCELLED", status_code=409)
            issued = self.issue(booking.id, actor_id=ctx.actor_id)
            audit(
                db, ctx, action="QR_REGENERATED", entity_type="booking", entity_id=booking.booking_number,
                new={"pass_id": issued.pass_id},
            )
            return booking, issued

        return run_transaction(self.db, work, label="qr_regenerate")

    def revoke(self, booking_number: str, reason: str, ctx: RequestContext) -> int:
        def work(db: Session) -> int:
            booking = self.bookings.get_by_number(booking_number, for_update=True)
            if booking is None:
                raise NotFound("Booking not found")
            n = self.repo.deactivate_for_booking(booking.id, actor_id=ctx.actor_id, reason=reason)
            audit(
                db, ctx, action="QR_REVOKED", entity_type="booking", entity_id=booking.booking_number,
                new={"revoked_passes": n, "reason": reason},
            )
            return n

        return run_transaction(self.db, work, label="qr_revoke")

    # ---------------------------------------------------------- resolving
    def lookup(self, token_or_payload: str) -> PassLookup:
        token = security.token_from_qr_payload(token_or_payload)
        if not 20 <= len(token) <= 200:
            return PassLookup(None, None)
        qr = self.repo.by_hash(security.hash_token(token))
        if qr is None:
            return PassLookup(None, None)
        return PassLookup(qr, self.bookings.get(qr.booking_id))

    def pass_details(self, token_or_payload: str) -> dict[str, object]:
        """Family pass view for the holder of the token."""
        found = self.lookup(token_or_payload)
        if not found.usable:
            # Same error for unknown / revoked / expired tokens (no oracle).
            raise NotFound("Pass not found or no longer valid", code="INVALID_QR")
        booking = found.booking
        assert booking is not None and found.qr_pass is not None
        reservations = self.bookings.reservations_detailed(booking.id)
        token = security.token_from_qr_payload(token_or_payload)
        return {
            "booking_number": booking.booking_number,
            "booking_status": booking.status,
            "coordinator_name": booking.coordinator_name,
            "primary_mobile_masked": mask_mobile(booking.primary_mobile),
            "city": booking.city,
            "pass_active": found.qr_pass.is_active,
            "expires_at": found.qr_pass.expires_at,
            "qr_payload": security.qr_payload_for(token),
            "created_at": booking.created_at,
            "member_count": booking.member_count,
            # Names only: the pass may be shared within the family, so no ages/contacts here.
            "members": [{"member_number": m.member_number, "full_name": m.full_name} for m in booking.members],
            "reservations": [
                {
                    "session_id": r["session_id"],
                    "event_date": r["event_date"],
                    "slot": r["slot"],
                    "start_time": r["start_time"],
                    "end_time": r["end_time"],
                    "kund_number": r["kund_number"],
                    "status": r["status"],
                    "checked_in_count": r["checked_in_count"],
                    "first_checked_in_at": r["first_checked_in_at"],
                }
                for r in reservations
            ],
        }

    def status_lookup(self, booking_number: str, mobile: str) -> dict[str, object]:
        booking = self.bookings.get_by_number(booking_number)
        # Constant response for "not found" and "mobile mismatch" (no enumeration oracle).
        if booking is None or not security.constant_time_equals(booking.primary_mobile, mobile):
            raise NotFound("No booking matches these details")
        active = self.repo.active_for_booking(booking.id)
        confirmed = sum(1 for s in booking.sessions if s.status == ReservationStatus.CONFIRMED.value)
        return {
            "booking_number": booking.booking_number,
            "booking_status": booking.status,
            "pass_active": bool(active and active.expires_at > clock.now()),
            "member_count": booking.member_count,
            "confirmed_sessions": confirmed,
        }

    # -------------------------------------------------------------- image
    @staticmethod
    def render(token_or_payload: str, fmt: Literal["png", "svg"] = "png", scale: int = 8) -> bytes:
        payload = security.qr_payload_for(security.token_from_qr_payload(token_or_payload))
        qr = segno.make(payload, error="m", micro=False)
        buf = io.BytesIO()
        qr.save(buf, kind=fmt, scale=scale, border=4)
        return buf.getvalue()
