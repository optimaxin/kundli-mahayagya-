"""Transactional cancellation that releases capacity exactly once.

Guarantees (each enforced in more than one place):

* The booking row is locked FOR UPDATE, so concurrent cancellations of the
  same booking are serialised; the second one sees the reservations already
  CANCELLED and becomes a no-op (``already_cancelled=True``).
* ``UPDATE ... WHERE status='CONFIRMED'`` transitions each reservation at most
  once; the DB trigger releases capacity only on that transition.
* ``cancellation_events`` has UNIQUE(booking_session_id).
* History is preserved: nothing is deleted; cancellation events and audit
  logs are append-only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import run_transaction
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import Kund
from app.models.enums import BookingStatus, ReservationStatus
from app.repositories.booking_repository import BookingRepository
from app.repositories.misc_repositories import QrRepository
from app.repositories.session_repository import SessionRepository
from app.services import session_service
from app.services.audit_service import RequestContext, audit


class CancellationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def cancel(
        self,
        booking_number: str,
        *,
        reason: str,
        session_ids: Sequence[int] | None,
        ctx: RequestContext,
    ) -> dict[str, Any]:
        def work(db: Session) -> dict[str, Any]:
            bookings = BookingRepository(db)
            booking = bookings.get_by_number(booking_number, for_update=True)
            if booking is None:
                raise NotFound("Booking not found")

            reservations = bookings.reservations_for_update(booking.id, session_ids)
            if session_ids:
                unknown = sorted(set(session_ids) - {r.session_id for r in reservations})
                if unknown:
                    raise ValidationFailed(
                        "The booking has no reservation for some of the given sessions",
                        code="INVALID_SESSION",
                        details={"sessions": unknown},
                    )
            targets = [r for r in reservations if r.status == ReservationStatus.CONFIRMED.value]
            if not targets:
                return {
                    "booking_number": booking.booking_number,
                    "booking_status": booking.status,
                    "already_cancelled": True,
                    "cancelled": [],
                    "released_capacity": 0,
                    "remaining_confirmed_sessions": bookings.count_confirmed_reservations(booking.id),
                }

            # Same global lock order as allocation.
            sessions = {s.id: s for s in SessionRepository(db).lock_for_allocation([t.session_id for t in targets])}
            completed = [sid for sid, s in sessions.items() if session_service.is_completed(s)]
            if completed:
                raise Conflict(
                    "Reservations for completed sessions cannot be cancelled",
                    code="SESSION_COMPLETED",
                    details={"sessions": sorted(completed)},
                )
            if bookings.count_checkins([t.id for t in targets]):
                raise Conflict(
                    "A reservation with recorded check-ins cannot be cancelled",
                    code="RESERVATION_HAS_CHECKINS",
                )

            cancelled: list[dict[str, Any]] = []
            for bs in sorted(targets, key=lambda r: r.session_id):
                if not bookings.cancel_reservation(bs):
                    continue  # already cancelled by someone else -> release nothing
                bookings.add_cancellation_event(
                    booking_session_id=bs.id,
                    booking_id=booking.id,
                    session_id=bs.session_id,
                    kund_id=bs.kund_id,
                    released_member_count=bs.member_count,
                    actor_id=ctx.actor_id,
                    reason=reason,
                )
                kund = db.get(Kund, bs.kund_id)
                cancelled.append(
                    {
                        "session_id": bs.session_id,
                        "kund_number": kund.kund_number if kund else bs.kund_id,
                        "released_member_count": bs.member_count,
                    }
                )

            remaining = bookings.count_confirmed_reservations(booking.id)
            previous_status = booking.status
            new_status = previous_status
            if remaining == 0 and previous_status != BookingStatus.CANCELLED.value:
                bookings.mark_booking_cancelled(booking.id)
                QrRepository(db).deactivate_for_booking(booking.id, actor_id=ctx.actor_id, reason="BOOKING_CANCELLED")
                new_status = BookingStatus.CANCELLED.value

            audit(
                db, ctx, action="BOOKING_CANCELLED" if remaining == 0 else "RESERVATIONS_CANCELLED",
                entity_type="booking", entity_id=booking.booking_number,
                previous={"status": previous_status, "sessions": [t.session_id for t in targets]},
                new={"status": new_status, "cancelled": cancelled, "reason": reason},
            )
            return {
                "booking_number": booking.booking_number,
                "booking_status": new_status,
                "already_cancelled": not cancelled,
                "cancelled": cancelled,
                "released_capacity": sum(c["released_member_count"] for c in cancelled),
                "remaining_confirmed_sessions": remaining,
            }

        return run_transaction(self.db, work, label="cancellation")
