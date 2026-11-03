"""Organiser dashboard read models (shape matches the React admin console) and
per-session Kund blocking."""

from __future__ import annotations

import threading
import time
from datetime import time as dtime
from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import run_transaction
from app.core.errors import Conflict, NotFound
from app.models import (
    AdminUser,
    AttendanceCheckin,
    Booking,
    BookingSession,
    FamilyMember,
    Kund,
    KundSessionCapacity,
)
from app.models.enums import BookingStatus, ReservationStatus
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import RequestContext, audit

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: float, fn: Any) -> Any:
    if ttl <= 0:
        return fn()
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now + ttl, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


class DashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------- analytics
    def analytics(self) -> dict[str, Any]:
        return _cached("analytics", get_settings().ANALYTICS_CACHE_SECONDS, self._analytics)

    def _analytics(self) -> dict[str, Any]:
        db = self.db
        confirmed = Booking.status == BookingStatus.CONFIRMED.value
        sessions = SessionRepository(db).list_all()
        stats = SessionRepository(db).capacity_stats()
        partial = dict(
            db.execute(
                select(KundSessionCapacity.session_id, func.count())
                .where(KundSessionCapacity.reserved_count > 0,
                       KundSessionCapacity.reserved_count < KundSessionCapacity.capacity)
                .group_by(KundSessionCapacity.session_id)
            ).all()
        )
        attended = dict(
            db.execute(
                select(BookingSession.session_id, func.count())
                .join(AttendanceCheckin, AttendanceCheckin.booking_session_id == BookingSession.id)
                .where(BookingSession.status == ReservationStatus.CONFIRMED.value)
                .group_by(BookingSession.session_id)
            ).all()
        )
        days: dict[str, dict[str, Any]] = {}
        for s in sessions:
            st = stats.get(s.id)
            row = days.setdefault(s.event_date.isoformat(), {"date": s.event_date.isoformat()})
            row[s.slot.lower()] = {
                "session_id": s.id,
                "used": st.reserved if st else 0,
                "capacity": st.total_capacity if st else 0,
                "left": st.remaining if st else 0,
                "full": st.kunds_full if st else 0,
                "partial": int(partial.get(s.id, 0)),
                "blocked": st.kunds_blocked if st else 0,
                "empty": st.kunds_empty if st else 0,
                "attended": int(attended.get(s.id, 0)),
            }

        families = db.scalar(select(func.count()).select_from(Booking).where(confirmed)) or 0
        people = db.scalar(select(func.coalesce(func.sum(Booking.member_count), 0)).where(confirmed)) or 0
        entered = sum(int(v) for v in attended.values())
        seats_total = sum(st.total_capacity for st in stats.values())
        seats_used = sum(st.reserved for st in stats.values())

        member_q = select(FamilyMember).join(Booking, Booking.id == FamilyMember.booking_id).where(confirmed)
        member_sub = member_q.subquery()
        age = member_sub.c.age
        bucket = case(
            (age <= 12, "0-12"), (age <= 30, "13-30"), (age <= 50, "31-50"), (age <= 70, "51-70"), else_="70+"
        )
        ages = {"0-12": 0, "13-30": 0, "31-50": 0, "51-70": 0, "70+": 0}
        for k, n in db.execute(
            select(bucket, func.count()).where(age.is_not(None)).group_by(bucket)
        ):
            ages[k] = int(n)
        gender = {"male": 0, "female": 0, "other": 0}
        for g, n in db.execute(
            select(member_sub.c.gender, func.count()).where(member_sub.c.gender.is_not(None))
            .group_by(member_sub.c.gender)
        ):
            gender[g] = int(n)
        rel = [
            [r, int(n)]
            for r, n in db.execute(
                select(member_sub.c.relationship, func.count())
                .where(member_sub.c.relationship.is_not(None))
                .group_by(member_sub.c.relationship)
                .order_by(func.count().desc())
                .limit(6)
            )
        ]
        sizes = [0] * 9
        for size, n in db.execute(
            select(Booking.member_count, func.count()).where(confirmed).group_by(Booking.member_count)
        ):
            sizes[int(size)] = int(n)
        cities = [
            [c, int(n)]
            for c, n in db.execute(
                select(Booking.city, func.sum(Booking.member_count))
                .where(confirmed)
                .group_by(Booking.city)
                .order_by(func.sum(Booking.member_count).desc())
                .limit(6)
            )
        ]
        tz = get_settings().EVENT_TIMEZONE
        local_day = func.date(func.timezone(tz, Booking.created_at))
        today = clock.today_local()
        start = today - timedelta(days=13)
        per_day = {
            d.isoformat(): int(n)
            for d, n in db.execute(
                select(local_day, func.count())
                .where(Booking.created_at >= clock.local_datetime(start, dtime(0, 0)))
                .group_by(local_day)
            )
        }
        trend = [
            {"date": (start + timedelta(days=i)).isoformat(), "n": per_day.get((start + timedelta(days=i)).isoformat(), 0)}
            for i in range(14)
        ]
        who = func.coalesce(
            AdminUser.full_name,
            case((AttendanceCheckin.source == "OFFLINE_SYNC", "Offline sync"), else_="Manual"),
        )
        staff = [
            [name, int(n)]
            for name, n in db.execute(
                select(who, func.count())
                .select_from(AttendanceCheckin)
                .outerjoin(AdminUser, AdminUser.id == AttendanceCheckin.scanner_id)
                .group_by(who)
                .order_by(func.count().desc())
                .limit(10)
            )
        ]
        return {
            "days": [days[k] for k in sorted(days)],
            "families": int(families),
            "people": int(people),
            "entered": entered,
            "seatsTotal": seats_total,
            "seatsUsed": seats_used,
            "ages": ages,
            "gender": gender,
            "sizes": sizes,
            "cities": cities,
            "trend": trend,
            "staff": staff,
            "rel": rel,
            "avgFamily": (people / families) if families else 0,
            "generated_at": clock.now().isoformat(),
        }

    # ------------------------------------------------------------ kund map
    def kund_map(self, session_id: int) -> dict[str, Any]:
        if SessionRepository(self.db).get(session_id) is None:
            raise NotFound("Session not found")
        occ: dict[int, int] = {}
        blocked: list[int] = []
        inactive: list[int] = []
        for kn, reserved, is_blocked, active in self.db.execute(
            select(Kund.kund_number, KundSessionCapacity.reserved_count, KundSessionCapacity.is_blocked, Kund.is_active)
            .join(Kund, Kund.id == KundSessionCapacity.kund_id)
            .where(KundSessionCapacity.session_id == session_id)
            .where((KundSessionCapacity.reserved_count > 0) | KundSessionCapacity.is_blocked | ~Kund.is_active)
        ):
            if reserved:
                occ[kn] = reserved
            if is_blocked:
                blocked.append(kn)
            if not active:
                inactive.append(kn)
        return {"session_id": session_id, "seats": get_settings().MAX_MEMBERS_PER_KUND,
                "occ": occ, "blocked": sorted(blocked), "inactive": sorted(inactive)}

    def set_block(self, session_id: int, kund_number: int, blocked: bool, ctx: RequestContext) -> dict[str, Any]:
        def work(db: Session) -> dict[str, Any]:
            # Same lock as allocation, so a block and an allocation never interleave.
            if not SessionRepository(db).lock_for_allocation([session_id]):
                raise NotFound("Session not found")
            kund = db.scalars(select(Kund).where(Kund.kund_number == kund_number)).first()
            if kund is None:
                raise NotFound("Kund not found")
            row = db.get(KundSessionCapacity, (session_id, kund.id), with_for_update=True)
            assert row is not None
            if blocked and row.reserved_count > 0:
                raise Conflict("Only an empty Kund can be blocked", code="KUND_NOT_EMPTY")
            previous = row.is_blocked
            db.execute(
                update(KundSessionCapacity)
                .where(KundSessionCapacity.session_id == session_id, KundSessionCapacity.kund_id == kund.id)
                .values(is_blocked=blocked)
                .execution_options(synchronize_session=False)
            )
            audit(db, ctx, action="KUND_BLOCKED" if blocked else "KUND_UNBLOCKED", entity_type="kund_session",
                  entity_id=f"{session_id}:{kund_number}", previous={"blocked": previous}, new={"blocked": blocked})
            return {"session_id": session_id, "kund_number": kund_number, "blocked": blocked}

        result = run_transaction(self.db, work, label="kund_block")
        clear_cache()
        return result
