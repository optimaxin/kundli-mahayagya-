"""Read models for the admin dashboard, booking search and operational views."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import (
    AdminUser,
    AttendanceCheckin,
    Booking,
    BookingSession,
    CancellationEvent,
    FamilyMember,
    Kund,
    KundSessionCapacity,
)
from app.models.enums import BookingStatus, ReservationStatus
from app.repositories.booking_repository import BookingRepository
from app.repositories.capacity_repository import CapacityRepository
from app.repositories.misc_repositories import QrRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.common import Pagination
from app.services import session_service
from app.services.audit_service import RequestContext, audit
from app.services.views import member_dict
from app.utils.identifiers import mask_mobile


class AdminService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------- dashboard
    def dashboard(self) -> dict[str, Any]:
        db = self.db
        booking_counts = dict(db.execute(select(Booking.status, func.count()).group_by(Booking.status)).all())
        members_total = db.scalar(select(func.count()).select_from(FamilyMember)) or 0
        members_confirmed = (
            db.scalar(
                select(func.count())
                .select_from(FamilyMember)
                .join(Booking, Booking.id == FamilyMember.booking_id)
                .where(Booking.status == BookingStatus.CONFIRMED.value)
            )
            or 0
        )
        res_counts = dict(
            db.execute(
                select(BookingSession.status, func.coalesce(func.sum(BookingSession.member_count), 0)).group_by(
                    BookingSession.status
                )
            ).all()
        )
        res_rows = dict(db.execute(select(BookingSession.status, func.count()).group_by(BookingSession.status)).all())
        checkins = db.scalar(select(func.count()).select_from(AttendanceCheckin)) or 0
        stats = SessionRepository(db).capacity_stats()
        total_capacity = sum(s.total_capacity for s in stats.values())
        reserved = sum(s.reserved for s in stats.values())
        return {
            "total_registrations": sum(booking_counts.values()),
            "total_family_bookings": sum(booking_counts.values()),
            "confirmed_bookings": booking_counts.get(BookingStatus.CONFIRMED.value, 0),
            "cancelled_bookings": booking_counts.get(BookingStatus.CANCELLED.value, 0),
            "total_registered_members": members_total,
            "members_in_confirmed_bookings": members_confirmed,
            "confirmed_family_session_reservations": res_rows.get(ReservationStatus.CONFIRMED.value, 0),
            "cancelled_family_session_reservations": res_rows.get(ReservationStatus.CANCELLED.value, 0),
            "confirmed_attendee_session_reservations": int(res_counts.get(ReservationStatus.CONFIRMED.value, 0)),
            "total_checkins": checkins,
            "capacity": {
                "total_attendee_session_capacity": total_capacity,
                "reserved": reserved,
                "remaining": total_capacity - reserved,
                "utilisation_percent": round(100 * reserved / total_capacity, 2) if total_capacity else 0.0,
            },
        }

    # ------------------------------------------------------------ sessions
    def session_availability(self) -> list[dict[str, Any]]:
        repo = SessionRepository(self.db)
        stats = repo.capacity_stats()
        out = []
        for s in repo.list_all():
            st = stats.get(s.id)
            out.append(
                {
                    "id": s.id,
                    "event_date": s.event_date,
                    "slot": s.slot,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "status": s.status,
                    "is_active": s.is_active,
                    "total_capacity": st.total_capacity if st else 0,
                    "reserved": st.reserved if st else 0,
                    "remaining": st.remaining if st else 0,
                    "kunds_empty": st.kunds_empty if st else 0,
                    "kunds_full": st.kunds_full if st else 0,
                    "kunds_blocked": st.kunds_blocked if st else 0,
                    "largest_family_bookable": min(8, st.largest_free_block) if st else 0,
                    "booking_open": session_service.booking_block_reason(s) is None,
                }
            )
        return out

    def session_detail(self, session_id: int) -> dict[str, Any]:
        sessions = {s["id"]: s for s in self.session_availability()}
        if session_id not in sessions:
            raise NotFound("Session not found")
        detail = sessions[session_id]
        s = SessionRepository(self.db).get(session_id)
        assert s is not None
        db = self.db
        detail["confirmed_families"] = (
            db.scalar(
                select(func.count())
                .select_from(BookingSession)
                .where(BookingSession.session_id == session_id, BookingSession.status == "CONFIRMED")
            )
            or 0
        )
        detail["checked_in_members"] = (
            db.scalar(
                select(func.count())
                .select_from(AttendanceCheckin)
                .join(BookingSession, BookingSession.id == AttendanceCheckin.booking_session_id)
                .where(BookingSession.session_id == session_id)
            )
            or 0
        )
        detail["completed"] = session_service.is_completed(s)
        detail["no_shows"] = (
            detail["reserved"] - detail["checked_in_members"] if detail["completed"] else None
        )
        return detail

    def kund_allocations(
        self, session_id: int, page: Pagination, only_occupied: bool, kund_number: int | None = None
    ) -> tuple[int, list[Any]]:
        if SessionRepository(self.db).get(session_id) is None:
            raise NotFound("Session not found")
        return CapacityRepository(self.db).kund_allocations(
            session_id, offset=page.offset, limit=page.page_size, only_occupied=only_occupied,
            kund_number=kund_number,
        )

    def kund_detail(self, kund_number: int) -> dict[str, Any]:
        kund = self.db.scalars(select(Kund).where(Kund.kund_number == kund_number)).first()
        if kund is None:
            raise NotFound("Kund not found")
        repo = CapacityRepository(self.db)
        sessions = []
        for s in SessionRepository(self.db).list_all():
            _, items = repo.kund_allocations(s.id, offset=0, limit=1, kund_number=kund_number)
            if items:
                sessions.append({"session_id": s.id, "event_date": s.event_date, "slot": s.slot, **items[0]})
        return {"kund_number": kund.kund_number, "is_active": kund.is_active, "sessions": sessions}

    # ------------------------------------------------------------ bookings
    def search_bookings(
        self,
        *,
        page: Pagination,
        booking_number: str | None,
        mobile: str | None,
        status: str | None,
        session_id: int | None,
        city: str | None,
        sort: str,
        descending: bool,
        ctx: RequestContext,
        q: str | None = None,
        event_date: date | None = None,
        slot: str | None = None,
        expand: bool = False,
    ) -> tuple[int, list[dict[str, Any]]]:
        repo = BookingRepository(self.db)
        stmt = repo.search_query(
            booking_number=booking_number, mobile=mobile, status=status, session_id=session_id, city=city,
            q=q, event_date=event_date, slot=slot,
        )
        total, rows = repo.search(stmt, sort=sort, descending=descending, offset=page.offset, limit=page.page_size)
        searched_mobile = mobile or (q if q and q.strip().isdigit() else None)
        if searched_mobile or expand:
            # Searching by phone number and listing full contact details are audited, privileged actions.
            audit(
                self.db, ctx,
                action="BOOKING_SEARCH_BY_MOBILE" if searched_mobile else "BOOKING_LIST_DETAILS",
                entity_type="booking", entity_id=None,
                new={"mobile_masked": mask_mobile(searched_mobile) if searched_mobile else None, "results": total,
                     "returned": len(rows)},
            )
            self.db.commit()
        if expand:
            ids = [b.id for b, _ in rows]
            members = repo.members_for_bookings(ids)
            reservations = repo.reservations_for_bookings(ids)
            return total, [
                {
                    "booking_number": b.booking_number,
                    "coordinator_name": b.coordinator_name,
                    "primary_mobile": b.primary_mobile,
                    "city": b.city,
                    "state": b.state,
                    "member_count": b.member_count,
                    "status": b.status,
                    "created_at": b.created_at,
                    "members": [member_dict(m) for m in members.get(b.id, [])],
                    "reservations": reservations.get(b.id, []),
                }
                for b, _ in rows
            ]
        items = [
            {
                "booking_number": b.booking_number,
                "coordinator_name": b.coordinator_name,
                "primary_mobile_masked": mask_mobile(b.primary_mobile),
                "city": b.city,
                "state": b.state,
                "member_count": b.member_count,
                "status": b.status,
                "session_count": n,
                "created_at": b.created_at,
            }
            for b, n in rows
        ]
        return total, items

    def booking_detail(self, booking_number: str, ctx: RequestContext) -> dict[str, Any]:
        repo = BookingRepository(self.db)
        booking = repo.get_by_number(booking_number)
        if booking is None:
            raise NotFound("Booking not found")
        qr = QrRepository(self.db).active_for_booking(booking.id)
        audit(
            self.db, ctx, action="BOOKING_VIEWED", entity_type="booking", entity_id=booking.booking_number
        )
        self.db.commit()
        return {
            "booking_number": booking.booking_number,
            "status": booking.status,
            "coordinator_name": booking.coordinator_name,
            "primary_mobile": booking.primary_mobile,
            "secondary_mobile": booking.secondary_mobile,
            "email": booking.email,
            "address": booking.address,
            "city": booking.city,
            "state": booking.state,
            "pincode": booking.pincode,
            "gotra": booking.gotra,
            "sankalp_purpose": booking.sankalp_purpose,
            "member_count": booking.member_count,
            "members": [member_dict(m) for m in repo.members(booking.id)],
            "reservations": repo.reservations_detailed(booking.id),
            "qr_pass_active": qr is not None,
            "qr_pass_expires_at": qr.expires_at if qr else None,
            "created_at": booking.created_at,
            "cancelled_at": booking.cancelled_at,
        }

    def booking_members(self, booking_number: str) -> list[dict[str, Any]]:
        repo = BookingRepository(self.db)
        booking = repo.get_by_number(booking_number)
        if booking is None:
            raise NotFound("Booking not found")
        return [
            {"booking_number": booking.booking_number, "booking_status": booking.status, **member_dict(m)}
            for m in repo.members(booking.id)
        ]

    def booking_reservations(self, booking_number: str) -> list[dict[str, Any]]:
        repo = BookingRepository(self.db)
        booking = repo.get_by_number(booking_number)
        if booking is None:
            raise NotFound("Booking not found")
        return repo.reservations_detailed(booking.id)

    # ------------------------------------------------------------ checkins
    def list_checkins(
        self, *, page: Pagination, session_id: int | None, booking_number: str | None
    ) -> tuple[int, list[dict[str, Any]]]:
        stmt = (
            select(AttendanceCheckin, Booking.booking_number, BookingSession.session_id, Kund.kund_number,
                   FamilyMember.member_number, FamilyMember.full_name, Booking.coordinator_name,
                   AdminUser.full_name)
            .join(Booking, Booking.id == AttendanceCheckin.booking_id)
            .join(BookingSession, BookingSession.id == AttendanceCheckin.booking_session_id)
            .join(Kund, Kund.id == BookingSession.kund_id)
            .join(FamilyMember, FamilyMember.id == AttendanceCheckin.member_id)
            .outerjoin(AdminUser, AdminUser.id == AttendanceCheckin.scanner_id)
        )
        if session_id:
            stmt = stmt.where(BookingSession.session_id == session_id)
        if booking_number:
            stmt = stmt.where(Booking.booking_number == booking_number)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.execute(
            stmt.order_by(AttendanceCheckin.checked_in_at.desc(), AttendanceCheckin.id.desc())
            .offset(page.offset)
            .limit(page.page_size)
        ).all()
        return total, [
            {
                "event_id": c.event_id,
                "booking_number": bn,
                "session_id": sid,
                "member_number": mn,
                "full_name": name,
                "kund_number": kn,
                "checked_in_at": c.checked_in_at,
                "source": c.source,
                "scanner_id": c.scanner_id,
                "coordinator_name": coord,
                "scanner_name": scanner or ("Offline sync" if c.source == "OFFLINE_SYNC" else None),
            }
            for c, bn, sid, kn, mn, name, coord, scanner in rows
        ]

    # ----------------------------------------------------------- integrity
    def integrity_report(self) -> dict[str, Any]:
        db = self.db
        mismatches = CapacityRepository(db).reconciliation_mismatches()
        member_mismatch = db.execute(
            select(Booking.booking_number, Booking.member_count, func.count(FamilyMember.id))
            .outerjoin(FamilyMember, FamilyMember.booking_id == Booking.id)
            .group_by(Booking.id)
            .having(func.count(FamilyMember.id) != Booking.member_count)
            .limit(100)
        ).all()
        reservation_mismatch = db.execute(
            select(Booking.booking_number)
            .join(BookingSession, BookingSession.booking_id == Booking.id)
            .where(BookingSession.member_count != Booking.member_count)
            .limit(100)
        ).all()
        over = db.execute(
            select(func.count())
            .select_from(KundSessionCapacity)
            .where(KundSessionCapacity.reserved_count > KundSessionCapacity.capacity)
        ).scalar()
        cancelled_without_event = db.execute(
            select(func.count())
            .select_from(BookingSession)
            .outerjoin(CancellationEvent, CancellationEvent.booking_session_id == BookingSession.id)
            .where(BookingSession.status == "CANCELLED", CancellationEvent.id.is_(None))
        ).scalar()
        return {
            "capacity_mismatches": mismatches,
            "booking_member_count_mismatches": [
                {"booking_number": bn, "member_count": mc, "member_rows": n} for bn, mc, n in member_mismatch
            ],
            "reservation_member_count_mismatches": [r[0] for r in reservation_mismatch],
            "cancelled_reservations_without_event": int(cancelled_without_event or 0),
            "overbooked_kunds": int(over or 0),
            "ok": not mismatches and not member_mismatch and not reservation_mismatch and not cancelled_without_event,
        }
