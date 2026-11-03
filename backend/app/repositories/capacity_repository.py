from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Booking, BookingSession, Kund, KundSessionCapacity
from app.models.enums import ReservationStatus


@dataclass(frozen=True)
class KundSlot:
    kund_id: int
    kund_number: int
    capacity: int
    reserved_count: int


class CapacityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_best_fit_for_update(self, session_id: int, family_size: int) -> KundSlot | None:
        """Best-fit: the active Kund with the FEWEST free seats that still fits the
        whole family (ties -> lowest Kund number). The chosen row is locked.

        Uses the partial expression index ix_ksc_best_fit.
        Deliberately NOT ``SKIP LOCKED``: a Kund that is momentarily locked by
        another transaction must not be mistaken for a full Kund. The caller
        already holds the session lock, so this lock never waits on another
        allocator; it only defends against out-of-band writers.
        """
        ksc = KundSessionCapacity
        free = ksc.capacity - ksc.reserved_count
        stmt = (
            select(ksc.kund_id, Kund.kund_number, ksc.capacity, ksc.reserved_count)
            .join(Kund, Kund.id == ksc.kund_id)
            .where(
                ksc.session_id == session_id,
                ksc.reserved_count < ksc.capacity,
                free >= family_size,
                Kund.is_active.is_(True),
                ksc.is_blocked.is_(False),
            )
            .order_by(free.asc(), ksc.kund_id.asc())
            .limit(1)
            .with_for_update(of=ksc)
        )
        row = self.db.execute(stmt).first()
        if row is None:
            return None
        return KundSlot(kund_id=row[0], kund_number=row[1], capacity=row[2], reserved_count=row[3])

    def kund_allocations(
        self,
        session_id: int,
        *,
        offset: int,
        limit: int,
        only_occupied: bool = False,
        kund_number: int | None = None,
    ) -> tuple[int, list[dict[str, object]]]:
        ksc = KundSessionCapacity
        base = select(ksc, Kund.kund_number, Kund.is_active).join(Kund, Kund.id == ksc.kund_id).where(
            ksc.session_id == session_id
        )
        if only_occupied:
            base = base.where(ksc.reserved_count > 0)
        if kund_number is not None:
            base = base.where(Kund.kund_number == kund_number)
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.db.execute(base.order_by(Kund.kund_number).offset(offset).limit(limit)).all()
        kund_ids = [r[0].kund_id for r in rows]
        families: dict[int, list[dict[str, object]]] = {k: [] for k in kund_ids}
        if kund_ids:
            fam_rows = self.db.execute(
                select(BookingSession.kund_id, Booking.booking_number, BookingSession.member_count,
                       Booking.coordinator_name)
                .join(Booking, Booking.id == BookingSession.booking_id)
                .where(
                    BookingSession.session_id == session_id,
                    BookingSession.kund_id.in_(kund_ids),
                    BookingSession.status == ReservationStatus.CONFIRMED.value,
                )
                .order_by(BookingSession.kund_id, BookingSession.id)
            )
            for kid, bn, mc, cn in fam_rows:
                families[kid].append({"booking_number": bn, "member_count": mc, "coordinator_name": cn})
        items = [
            {
                "kund_number": r[1],
                "kund_active": r[2],
                "blocked": r[0].is_blocked,
                "capacity": r[0].capacity,
                "reserved_count": r[0].reserved_count,
                "remaining": r[0].capacity - r[0].reserved_count,
                "families": families[r[0].kund_id],
            }
            for r in rows
        ]
        return total, items

    def reconciliation_mismatches(self, limit: int = 100) -> list[dict[str, int]]:
        """Capacity rows whose reserved_count != SUM(member_count) of CONFIRMED reservations."""
        ksc = KundSessionCapacity
        active = (
            select(
                BookingSession.session_id,
                BookingSession.kund_id,
                func.sum(BookingSession.member_count).label("active_members"),
            )
            .where(BookingSession.status == ReservationStatus.CONFIRMED.value)
            .group_by(BookingSession.session_id, BookingSession.kund_id)
            .subquery()
        )
        actual = func.coalesce(active.c.active_members, 0)
        stmt = (
            select(ksc.session_id, ksc.kund_id, ksc.reserved_count, actual)
            .outerjoin(active, (active.c.session_id == ksc.session_id) & (active.c.kund_id == ksc.kund_id))
            .where(ksc.reserved_count != actual)
            .limit(limit)
        )
        return [
            {"session_id": s, "kund_id": k, "reserved_count": r, "active_members": int(a)}
            for s, k, r, a in self.db.execute(stmt)
        ]
