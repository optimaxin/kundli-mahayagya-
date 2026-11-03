from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, case, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import clock
from app.models import (
    AdminUser,
    AttendanceCheckin,
    Booking,
    BookingSession,
    CancellationEvent,
    EventSession,
    FamilyMember,
    Kund,
)
from app.models.enums import BookingStatus, ReservationStatus

SORTABLE_BOOKING_FIELDS = {
    "created_at": Booking.created_at,
    "booking_number": Booking.booking_number,
    "member_count": Booking.member_count,
    "coordinator_name": Booking.coordinator_name,
}


class BookingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------- creation
    def try_insert_booking(self, values: dict[str, Any]) -> int | None:
        """Insert a booking; returns None if the booking_number collided."""
        stmt = (
            pg_insert(Booking)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[Booking.booking_number])
            .returning(Booking.id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def insert_members(self, booking_id: int, members: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert members in order (member_number 1..n). Each dict: full_name, age, gender, relationship, mobile."""
        rows = [
            {
                "booking_id": booking_id,
                "member_number": i + 1,
                "full_name": m["full_name"],
                "age": m.get("age"),
                "gender": m.get("gender"),
                "relationship": m.get("relationship"),
                "mobile": m.get("mobile"),
            }
            for i, m in enumerate(members)
        ]
        self.db.execute(insert(FamilyMember.__table__), rows)
        return [{k: r[k] for k in ("member_number", "full_name", "age", "gender", "relationship")} for r in rows]

    def insert_reservation(self, *, booking_id: int, session_id: int, kund_id: int, member_count: int) -> int:
        # The AFTER INSERT trigger increments kund_session_capacity.reserved_count;
        # the CHECK constraint there makes overbooking impossible.
        return self.db.execute(
            insert(BookingSession)
            .values(
                booking_id=booking_id,
                session_id=session_id,
                kund_id=kund_id,
                member_count=member_count,
                status=ReservationStatus.CONFIRMED.value,
            )
            .returning(BookingSession.id)
        ).scalar_one()

    def lock_mobile(self, mobile: str) -> None:
        """Transaction-scoped advisory lock serialising registrations per mobile number."""
        self.db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"mobile:{mobile}"})

    def confirmed_sessions_for_mobile(self, mobile: str, session_ids: Sequence[int]) -> list[int]:
        stmt = (
            select(BookingSession.session_id)
            .join(Booking, Booking.id == BookingSession.booking_id)
            .where(
                Booking.primary_mobile == mobile,
                BookingSession.session_id.in_(session_ids),
                BookingSession.status == ReservationStatus.CONFIRMED.value,
            )
            .distinct()
        )
        return sorted(self.db.scalars(stmt))

    def confirmed_dates_for_mobile(self, mobile: str, dates: Sequence[date]) -> list[date]:
        """Dates on which this mobile already holds a confirmed reservation (either slot)."""
        stmt = (
            select(EventSession.event_date)
            .join(BookingSession, BookingSession.session_id == EventSession.id)
            .join(Booking, Booking.id == BookingSession.booking_id)
            .where(
                Booking.primary_mobile == mobile,
                EventSession.event_date.in_(dates),
                BookingSession.status == ReservationStatus.CONFIRMED.value,
            )
            .distinct()
        )
        return sorted(self.db.scalars(stmt))

    # ------------------------------------------------------------ queries
    def get_by_number(self, booking_number: str, *, for_update: bool = False) -> Booking | None:
        stmt = (
            select(Booking)
            .where(Booking.booking_number == booking_number)
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.scalars(stmt).first()

    def get(self, booking_id: int) -> Booking | None:
        return self.db.get(Booking, booking_id)

    def members_for_bookings(self, booking_ids: Sequence[int]) -> dict[int, list[FamilyMember]]:
        out: dict[int, list[FamilyMember]] = {}
        if booking_ids:
            for m in self.db.scalars(
                select(FamilyMember)
                .where(FamilyMember.booking_id.in_(booking_ids))
                .order_by(FamilyMember.booking_id, FamilyMember.member_number)
            ):
                out.setdefault(m.booking_id, []).append(m)
        return out

    def members(self, booking_id: int) -> list[FamilyMember]:
        return list(
            self.db.scalars(
                select(FamilyMember).where(FamilyMember.booking_id == booking_id).order_by(FamilyMember.member_number)
            )
        )

    def reservations_detailed(self, booking_id: int) -> list[dict[str, Any]]:
        return self.reservations_for_bookings([booking_id]).get(booking_id, [])

    def reservations_for_bookings(self, booking_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
        if not booking_ids:
            return {}
        checked = (
            select(
                AttendanceCheckin.booking_session_id,
                func.count().label("n"),
                func.min(AttendanceCheckin.checked_in_at).label("first_at"),
                func.max(
                    func.coalesce(
                        AdminUser.full_name,
                        case((AttendanceCheckin.source == "OFFLINE_SYNC", "Offline sync"), else_=None),
                    )
                ).label("by"),
            )
            .outerjoin(AdminUser, AdminUser.id == AttendanceCheckin.scanner_id)
            .where(AttendanceCheckin.booking_id.in_(booking_ids))
            .group_by(AttendanceCheckin.booking_session_id)
            .subquery()
        )
        stmt = (
            select(
                BookingSession,
                EventSession,
                Kund.kund_number,
                func.coalesce(checked.c.n, 0),
                checked.c.first_at,
                checked.c.by,
            )
            .join(EventSession, EventSession.id == BookingSession.session_id)
            .join(Kund, Kund.id == BookingSession.kund_id)
            .outerjoin(checked, checked.c.booking_session_id == BookingSession.id)
            .where(BookingSession.booking_id.in_(booking_ids))
            .order_by(BookingSession.booking_id, BookingSession.session_id)
        )
        out: dict[int, list[dict[str, Any]]] = {}
        for bs, es, kund_number, n, first_at, by in self.db.execute(stmt):
            out.setdefault(bs.booking_id, []).append(
                {
                    "booking_session_id": bs.id,
                    "session_id": es.id,
                    "event_date": es.event_date,
                    "slot": es.slot,
                    "start_time": es.start_time,
                    "end_time": es.end_time,
                    "kund_number": kund_number,
                    "member_count": bs.member_count,
                    "status": bs.status,
                    "created_at": bs.created_at,
                    "cancelled_at": bs.cancelled_at,
                    "checked_in_count": int(n),
                    "first_checked_in_at": first_at,
                    "checked_in_by": by,
                }
            )
        return out

    def reservations_for_update(self, booking_id: int, session_ids: Sequence[int] | None) -> list[BookingSession]:
        stmt = select(BookingSession).where(BookingSession.booking_id == booking_id)
        if session_ids:
            stmt = stmt.where(BookingSession.session_id.in_(session_ids))
        return list(self.db.scalars(stmt.order_by(BookingSession.session_id).with_for_update()))

    def reservation_for_session(self, booking_id: int, session_id: int) -> BookingSession | None:
        return self.db.scalars(
            select(BookingSession).where(
                BookingSession.booking_id == booking_id, BookingSession.session_id == session_id
            )
        ).first()

    def count_checkins(self, booking_session_ids: Sequence[int]) -> int:
        if not booking_session_ids:
            return 0
        return (
            self.db.scalar(
                select(func.count())
                .select_from(AttendanceCheckin)
                .where(AttendanceCheckin.booking_session_id.in_(booking_session_ids))
            )
            or 0
        )

    def cancel_reservation(self, bs: BookingSession) -> bool:
        """CONFIRMED -> CANCELLED exactly once. The trigger releases capacity."""
        result = self.db.execute(
            update(BookingSession)
            .where(BookingSession.id == bs.id, BookingSession.status == ReservationStatus.CONFIRMED.value)
            .values(status=ReservationStatus.CANCELLED.value, cancelled_at=clock.now())
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def add_cancellation_event(self, **values: Any) -> None:
        self.db.execute(insert(CancellationEvent).values(**values))

    def count_confirmed_reservations(self, booking_id: int) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(BookingSession)
                .where(
                    BookingSession.booking_id == booking_id,
                    BookingSession.status == ReservationStatus.CONFIRMED.value,
                )
            )
            or 0
        )

    def mark_booking_cancelled(self, booking_id: int) -> None:
        self.db.execute(
            update(Booking)
            .where(Booking.id == booking_id)
            .values(status=BookingStatus.CANCELLED.value, cancelled_at=clock.now(), updated_at=func.now())
            .execution_options(synchronize_session=False)
        )

    # ------------------------------------------------------------- search
    def search_query(
        self,
        *,
        booking_number: str | None = None,
        mobile: str | None = None,
        status: str | None = None,
        session_id: int | None = None,
        city: str | None = None,
        q: str | None = None,
        event_date: date | None = None,
        slot: str | None = None,
    ) -> Select[tuple[Booking]]:
        stmt = select(Booking)
        if q:
            term = q.strip()
            if term.upper().startswith("MY26"):
                stmt = stmt.where(Booking.booking_number.like(term.upper().replace("%", "") + "%"))
            elif term.isdigit():
                like = term + "%"
                stmt = stmt.where(Booking.primary_mobile.like(like) | Booking.secondary_mobile.like(like))
            else:
                pattern = "%" + term.replace("\\", "").replace("%", "").replace("_", "") + "%"
                stmt = stmt.where(
                    Booking.coordinator_name.ilike(pattern)
                    | Booking.id.in_(select(FamilyMember.booking_id).where(FamilyMember.full_name.ilike(pattern)))
                )
        if event_date or slot:
            sess = select(EventSession.id)
            if event_date:
                sess = sess.where(EventSession.event_date == event_date)
            if slot:
                sess = sess.where(EventSession.slot == slot)
            stmt = stmt.where(
                Booking.id.in_(select(BookingSession.booking_id).where(BookingSession.session_id.in_(sess)))
            )
        if booking_number:
            stmt = stmt.where(Booking.booking_number == booking_number)
        if mobile:
            stmt = stmt.where((Booking.primary_mobile == mobile) | (Booking.secondary_mobile == mobile))
        if status:
            stmt = stmt.where(Booking.status == status)
        if city:
            stmt = stmt.where(func.lower(Booking.city) == city.lower())
        if session_id:
            stmt = stmt.where(
                Booking.id.in_(select(BookingSession.booking_id).where(BookingSession.session_id == session_id))
            )
        return stmt

    def search(
        self, stmt: Select[tuple[Booking]], *, sort: str, descending: bool, offset: int, limit: int
    ) -> tuple[int, list[tuple[Booking, int]]]:
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = SORTABLE_BOOKING_FIELDS.get(sort, Booking.created_at)
        ordered = stmt.order_by(col.desc() if descending else col.asc(), Booking.id.desc())
        bookings = list(self.db.scalars(ordered.offset(offset).limit(limit)))
        counts: dict[int, int] = {}
        if bookings:
            counts = dict(
                self.db.execute(
                    select(BookingSession.booking_id, func.count())
                    .where(BookingSession.booking_id.in_([b.id for b in bookings]))
                    .group_by(BookingSession.booking_id)
                ).all()
            )
        return total, [(b, counts.get(b.id, 0)) for b in bookings]
