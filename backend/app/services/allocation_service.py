"""Kund allocation engine.

Algorithm (per selected session, all inside ONE database transaction):

1. Lock the selected ``event_sessions`` rows in ascending id order
   (``SELECT ... FOR NO KEY UPDATE``). Allocation and cancellation both take
   these locks in the same global order, so

   * Kund selection in a session is serialised -> the best-fit choice is
     computed on fresh data and two families can never both claim the last
     seats of a Kund;
   * lock acquisition order is consistent -> no deadlock cycles between
     multi-session bookings.

2. For each session (ascending), pick the BEST-FIT Kund: the active Kund
   with the fewest free seats that still holds the whole family (ties ->
   lowest Kund number), locking that capacity row.
   Example: Kund 101 has 6/8 and the family has 2 -> Kund 101 is chosen.
   If no partially-filled Kund fits, the fewest-free-seat Kund is an empty
   one (8 free). If nothing fits -> CapacityUnavailable.

3. Insert the reservation. The database trigger adds member_count to
   reserved_count; the CHECK (reserved_count <= capacity) is a final,
   independent guard against overbooking.

4. If ANY session cannot be allocated, the exception aborts the whole
   transaction: no partial multi-session booking is ever committed.

Lock waits are bounded by ``lock_timeout``; deadlocks / lock timeouts /
serialization failures are retried by :func:`app.core.database.run_transaction`.
We do not use ``SKIP LOCKED`` because a temporarily locked Kund would be
misread as a full one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import CapacityUnavailable, ValidationFailed
from app.repositories.booking_repository import BookingRepository
from app.repositories.capacity_repository import CapacityRepository
from app.repositories.session_repository import SessionRepository
from app.services import session_service


@dataclass(frozen=True)
class Allocation:
    session_id: int
    kund_id: int
    kund_number: int
    booking_session_id: int
    seats_before: int  # reserved_count of the Kund before this family was added


class AllocationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.capacity = CapacityRepository(db)
        self.bookings = BookingRepository(db)

    def allocate_family(self, *, booking_id: int, family_size: int, session_ids: Sequence[int]) -> list[Allocation]:
        if not 1 <= family_size <= 8:
            raise ValidationFailed("Family size must be between 1 and 8")
        ordered = sorted(set(session_ids))
        locked = self.sessions.lock_for_allocation(ordered)
        found = {s.id for s in locked}
        missing = [sid for sid in ordered if sid not in found]
        if missing:
            raise ValidationFailed("Invalid session selection", code="INVALID_SESSION", details={"invalid_sessions": missing})
        # Re-validate under the lock (an admin may have closed a session meanwhile).
        blocked = {s.id: r for s in locked if (r := session_service.booking_block_reason(s))}
        if blocked:
            raise ValidationFailed(
                "One or more selected sessions are not open for booking",
                code="SESSION_NOT_BOOKABLE",
                details={"sessions": [{"session_id": k, "reason": v} for k, v in blocked.items()]},
            )

        allocations: list[Allocation] = []
        for sid in ordered:
            slot = self.capacity.find_best_fit_for_update(sid, family_size)
            if slot is None:
                raise CapacityUnavailable(
                    f"No Kund has {family_size} free place(s) together in session {sid}",
                    details={"unavailable_sessions": [sid]},
                )
            bs_id = self.bookings.insert_reservation(
                booking_id=booking_id, session_id=sid, kund_id=slot.kund_id, member_count=family_size
            )
            allocations.append(
                Allocation(
                    session_id=sid,
                    kund_id=slot.kund_id,
                    kund_number=slot.kund_number,
                    booking_session_id=bs_id,
                    seats_before=slot.reserved_count,
                )
            )
        return allocations
