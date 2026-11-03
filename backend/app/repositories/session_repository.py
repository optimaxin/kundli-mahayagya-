from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import EventSession, Kund, KundSessionCapacity


@dataclass(frozen=True)
class SessionCapacityStats:
    session_id: int
    total_capacity: int
    reserved: int
    kunds_empty: int
    kunds_full: int
    largest_free_block: int
    kunds_blocked: int = 0
    free_places: int = 0

    @property
    def remaining(self) -> int:
        """Bookable places left (free seats in active, unblocked Kunds)."""
        return self.free_places


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, session_id: int) -> EventSession | None:
        return self.db.get(EventSession, session_id)

    def get_many(self, ids: Sequence[int]) -> list[EventSession]:
        if not ids:
            return []
        return list(self.db.scalars(select(EventSession).where(EventSession.id.in_(ids)).order_by(EventSession.id)))

    def list_all(self) -> list[EventSession]:
        return list(self.db.scalars(select(EventSession).order_by(EventSession.id)))

    def lock_for_allocation(self, ids: Sequence[int]) -> list[EventSession]:
        """Row-lock the sessions in ascending id order (FOR NO KEY UPDATE).

        Every capacity-changing transaction (allocation and cancellation) takes
        these locks in the same order, which serialises Kund selection per
        session (exact best-fit, no lost updates) and cannot deadlock. FOR NO
        KEY UPDATE does not conflict with the FOR KEY SHARE locks taken by
        foreign-key checks, so unrelated inserts are not blocked.
        """
        stmt = (
            select(EventSession)
            .where(EventSession.id.in_(sorted(set(ids))))
            .order_by(EventSession.id)
            .with_for_update(key_share=True)
        )
        return list(self.db.scalars(stmt).all())

    def capacity_stats(self, session_ids: Sequence[int] | None = None) -> dict[int, SessionCapacityStats]:
        ksc = KundSessionCapacity
        free = ksc.capacity - ksc.reserved_count
        usable = Kund.is_active.is_(True) & ksc.is_blocked.is_(False)
        stmt = (
            select(
                ksc.session_id,
                func.sum(case((usable, ksc.capacity), else_=ksc.reserved_count)),
                func.sum(ksc.reserved_count),
                func.count().filter(ksc.reserved_count == 0, usable),
                func.count().filter(ksc.reserved_count >= ksc.capacity),
                func.coalesce(func.max(case((usable, free), else_=0)), 0),
                func.count().filter(~usable),
                func.coalesce(func.sum(case((usable, free), else_=0)), 0),
            )
            .join(Kund, Kund.id == ksc.kund_id)
            .group_by(ksc.session_id)
        )
        if session_ids:
            stmt = stmt.where(ksc.session_id.in_(session_ids))
        out: dict[int, SessionCapacityStats] = {}
        for sid, cap, reserved, empty, full, largest, blocked, free_places in self.db.execute(stmt):
            out[sid] = SessionCapacityStats(
                session_id=sid,
                total_capacity=int(cap or 0),
                reserved=int(reserved or 0),
                kunds_empty=int(empty or 0),
                kunds_full=int(full or 0),
                largest_free_block=int(largest or 0),
                kunds_blocked=int(blocked or 0),
                free_places=int(free_places or 0),
            )
        return out
