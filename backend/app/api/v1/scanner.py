from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ValidationFailed
from app.core.permissions import require_roles, require_staff
from app.core.rate_limit import check_rate
from app.models import AdminUser
from app.models.enums import Role
from app.schemas.common import ApiResponse, Pagination, ok, pagination_params
from app.schemas.scanner import CheckinIn, CheckinResultOut, ScanIn, ScannerMeOut, ScanResultOut, _PassRef
from app.services.admin_service import AdminService
from app.services.checkin_service import CheckinService

router = APIRouter(prefix="/scanner", tags=["scanner"])
checkins_router = APIRouter(prefix="/checkins", tags=["checkins"])
require_gate_user = require_roles(Role.SCANNER, Role.ADMIN, Role.SUPERVISOR)


def _check_request(user: AdminUser, body: _PassRef) -> None:
    """SCANNERs never choose a session; staff must name one. Rate-limit per user."""
    if user.role == Role.SCANNER.value and body.session_id is not None:
        raise ValidationFailed(
            "Scanner accounts cannot choose a session; it comes from the account", code="SESSION_NOT_ALLOWED"
        )
    if user.role != Role.SCANNER.value and body.session_id is None:
        raise ValidationFailed("session_id is required for ADMIN/SUPERVISOR scanning", code="SESSION_REQUIRED")
    check_rate("scanner", str(user.id), "RATE_LIMIT_SCANNER")
    if body.booking_number is not None:
        check_rate("scanner-manual", str(user.id), "RATE_LIMIT_SCANNER_MANUAL")


@router.get("/me", response_model=ApiResponse[ScannerMeOut])
def scanner_me(user: AdminUser = Depends(require_gate_user), db: Session = Depends(get_db)) -> dict:
    """The scanner's assigned session (derived server-side from the account)."""
    return ok(CheckinService(db).scanner_me(user))


@router.post("/scan", response_model=ApiResponse[ScanResultOut])
def scan(body: ScanIn, user: AdminUser = Depends(require_gate_user), db: Session = Depends(get_db)) -> dict:
    """Scan a family pass. Returns the roster + Kund for the session.

    Business outcomes are returned with HTTP 200 and a ``status`` (+ ``reason``)
    so scanner apps can render them uniformly.
    """
    _check_request(user, body)
    return ok(CheckinService(db).scan(user, body.qr_payload, booking_number=body.booking_number,
                                      session_id=body.session_id))


@router.post("/checkin", response_model=ApiResponse[CheckinResultOut])
def checkin(body: CheckinIn, user: AdminUser = Depends(require_gate_user), db: Session = Depends(get_db)) -> dict:
    """Check in ONE family member (by member number).

    Statuses: CHECKIN_SUCCESS, ALREADY_CHECKED_IN, INVALID_QR, INVALID_SESSION,
    INVALID_MEMBER, BOOKING_CANCELLED. Supplying the same ``event_id`` again
    (e.g. after a network retry) is idempotent.
    """
    _check_request(user, body)
    return ok(CheckinService(db).checkin(user, body.qr_payload, body.member_number, body.event_id,
                                         booking_number=body.booking_number, session_id=body.session_id))


@router.get("/recent")
def recent(
    limit: int = Query(8, ge=1, le=50), user: AdminUser = Depends(require_gate_user), db: Session = Depends(get_db)
) -> dict:
    """The current user's own most recent check-ins (member rows, newest first)."""
    return ok(CheckinService(db).recent(user, limit))


@checkins_router.get("")
def list_checkins(
    page: Pagination = Depends(pagination_params),
    session_id: int | None = None,
    booking_number: str | None = None,
    _: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Recorded member check-ins (ADMIN, SUPERVISOR), newest first."""
    total, items = AdminService(db).list_checkins(
        page=page, session_id=session_id, booking_number=booking_number.upper() if booking_number else None
    )
    return ok(items, page.meta(total))
