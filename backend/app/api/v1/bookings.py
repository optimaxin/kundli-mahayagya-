from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ValidationFailed
from app.core.permissions import request_context, require_staff
from app.models import AdminUser
from app.schemas.booking import (
    BookingDetailOut,
    BookingReservationOut,
    BookingSummaryOut,
    CancelOut,
    CancelRequest,
    FamilyMemberOut,
)
from app.schemas.common import ApiResponse, Pagination, ok, pagination_params
from app.schemas.scanner import ManualCheckinIn
from app.services.admin_service import AdminService
from app.services.cancellation_service import CancellationService
from app.services.checkin_service import CheckinService
from app.utils import validators
from app.utils.identifiers import is_valid_booking_number, normalize_booking_number

router = APIRouter(prefix="/bookings", tags=["bookings"])
family_router = APIRouter(prefix="/family-members", tags=["family-members"])


def _bn(booking_number: str) -> str:
    bn = normalize_booking_number(booking_number)
    if not is_valid_booking_number(bn):
        raise ValidationFailed("Invalid booking number format", code="INVALID_BOOKING_NUMBER")
    return bn


@router.get("", responses={200: {"model": ApiResponse[list[BookingSummaryOut]]}})
def search_bookings(
    request: Request,
    page: Pagination = Depends(pagination_params),
    q: str | None = Query(None, max_length=60, description="Booking-number prefix, mobile prefix or name"),
    event_date: date | None = Query(None, description="Only bookings with a reservation on this date"),
    slot: Literal["MORNING", "AFTERNOON"] | None = None,
    expand: bool = Query(False, description="Include members, reservations and full mobile (audited)"),
    booking_number: str | None = Query(None, max_length=20),
    mobile: str | None = Query(None, max_length=16, description="Primary or secondary mobile (audited search)"),
    status: Literal["CONFIRMED", "CANCELLED"] | None = None,
    session_id: int | None = Query(None, ge=1),
    city: str | None = Query(None, max_length=100),
    sort: Literal["created_at", "booking_number", "member_count", "coordinator_name"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    user: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Search family bookings (ADMIN, SUPERVISOR). Mobile searches are audit-logged."""
    norm_mobile = None
    if mobile:
        try:
            norm_mobile = validators.normalize_mobile(mobile)
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
    total, items = AdminService(db).search_bookings(
        page=page,
        booking_number=normalize_booking_number(booking_number) if booking_number else None,
        mobile=norm_mobile,
        status=status,
        session_id=session_id,
        city=city,
        sort=sort,
        descending=order == "desc",
        ctx=request_context(request, user),
        q=q.strip() if q and q.strip() else None,
        event_date=event_date,
        slot=slot,
        expand=expand,
    )
    return ok(items, page.meta(total))


@router.get("/{booking_number}", response_model=ApiResponse[BookingDetailOut])
def get_booking(
    booking_number: str, request: Request, user: AdminUser = Depends(require_staff), db: Session = Depends(get_db)
) -> dict:
    """Full booking details incl. contact data (ADMIN, SUPERVISOR). Access is audit-logged."""
    return ok(AdminService(db).booking_detail(_bn(booking_number), request_context(request, user)))


@router.get("/{booking_number}/members", response_model=ApiResponse[list[FamilyMemberOut]])
def get_booking_members(
    booking_number: str, _: AdminUser = Depends(require_staff), db: Session = Depends(get_db)
) -> dict:
    return ok(AdminService(db).booking_members(_bn(booking_number)))


@router.get("/{booking_number}/sessions", response_model=ApiResponse[list[BookingReservationOut]])
def get_booking_sessions(
    booking_number: str, _: AdminUser = Depends(require_staff), db: Session = Depends(get_db)
) -> dict:
    """Reserved sessions with their Kund assignment and check-in counts."""
    return ok(AdminService(db).booking_reservations(_bn(booking_number)))


@router.post("/{booking_number}/cancel", response_model=ApiResponse[CancelOut])
def cancel_booking(
    booking_number: str,
    body: CancelRequest,
    request: Request,
    user: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Cancel all (or selected) sessions of a booking. Idempotent: repeating the
    request releases nothing further and returns ``already_cancelled=true``."""
    result = CancellationService(db).cancel(
        _bn(booking_number), reason=body.reason, session_ids=body.session_ids, ctx=request_context(request, user)
    )
    return ok(result)


@router.post("/{booking_number}/checkin")
def manual_checkin(
    booking_number: str,
    body: ManualCheckinIn,
    request: Request,
    user: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Organiser marks members of a reservation as entered (help desk / correction).
    Each member gets an individual check-in row. Entries cannot be undone (attendance
    is append-only). Audited."""
    return ok(CheckinService(db).manual_checkin(
        _bn(booking_number), body.session_id, body.member_numbers, user, request_context(request, user)
    ))


@family_router.get("", response_model=ApiResponse[list[FamilyMemberOut]])
def list_family_members(
    booking_number: str = Query(..., max_length=20),
    _: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Family members of a booking (ADMIN, SUPERVISOR)."""
    return ok(AdminService(db).booking_members(_bn(booking_number)))
