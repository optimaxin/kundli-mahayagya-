"""Idempotent seeding of the 16 sessions, 2,151 Kunds and 34,416 capacity rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EventSession, Kund, KundSessionCapacity
from app.models.enums import SessionSlot


@dataclass
class SeedReport:
    sessions: int
    kunds: int
    capacity_rows: int
    capacity_not_eight: int
    reserved_not_zero: int

    @property
    def expected_ok(self) -> bool:
        s = get_settings()
        sessions = s.EVENT_DAYS * 2
        return (
            self.sessions == sessions
            and self.kunds == s.TOTAL_KUNDS
            and self.capacity_rows == sessions * s.TOTAL_KUNDS
            and self.capacity_not_eight == 0
        )


def seed_sessions(db: Session) -> int:
    s = get_settings()
    rows = []
    for day in range(s.EVENT_DAYS):
        d = s.EVENT_START_DATE + timedelta(days=day)
        rows.append((day * 2 + 1, d, SessionSlot.MORNING.value, s.MORNING_START, s.MORNING_END))
        rows.append((day * 2 + 2, d, SessionSlot.AFTERNOON.value, s.AFTERNOON_START, s.AFTERNOON_END))
    for sid, d, slot, start, end in rows:
        db.execute(
            text(
                "INSERT INTO event_sessions (id, event_date, slot, start_time, end_time) "
                "VALUES (:id, :d, :slot, :st, :et) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": sid, "d": d, "slot": slot, "st": start, "et": end},
        )
    created = _ensure_capacity_rows(db)
    return created


def seed_kunds(db: Session) -> int:
    s = get_settings()
    db.execute(
        text(
            "INSERT INTO kunds (id, kund_number) "
            "SELECT g, g FROM generate_series(1, :n) AS g ON CONFLICT (id) DO NOTHING"
        ),
        {"n": s.TOTAL_KUNDS},
    )
    return _ensure_capacity_rows(db)


def _ensure_capacity_rows(db: Session) -> int:
    result = db.execute(
        text(
            "INSERT INTO kund_session_capacity (session_id, kund_id, capacity, reserved_count) "
            "SELECT s.id, k.id, :cap, 0 FROM event_sessions s CROSS JOIN kunds k "
            "ON CONFLICT (session_id, kund_id) DO NOTHING"
        ),
        {"cap": get_settings().MAX_MEMBERS_PER_KUND},
    )
    return int(result.rowcount or 0)


def seed_all(db: Session) -> SeedReport:
    seed_sessions(db)
    seed_kunds(db)
    db.commit()
    return verify_seed(db)


def verify_seed(db: Session) -> SeedReport:
    return SeedReport(
        sessions=db.scalar(select(func.count()).select_from(EventSession)) or 0,
        kunds=db.scalar(select(func.count()).select_from(Kund)) or 0,
        capacity_rows=db.scalar(select(func.count()).select_from(KundSessionCapacity)) or 0,
        capacity_not_eight=db.scalar(
            select(func.count()).select_from(KundSessionCapacity).where(KundSessionCapacity.capacity != 8)
        )
        or 0,
        reserved_not_zero=db.scalar(
            select(func.count()).select_from(KundSessionCapacity).where(KundSessionCapacity.reserved_count != 0)
        )
        or 0,
    )
