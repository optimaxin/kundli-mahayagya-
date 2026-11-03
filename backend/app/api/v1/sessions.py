from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db, run_transaction
from app.core.errors import NotFound
from app.core.permissions import request_context, require_admin, require_staff
from app.core.rate_limit import rate_limit
from app.models import AdminUser, EventSession
from app.schemas.booking import SessionAvailabilityOut
from app.schemas.common import ApiResponse, Pagination, ok, pagination_params
from app.services.admin_service import AdminService
from app.services.audit_service import audit
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/sessions", tags=["sessions"])
kund_router = APIRouter(prefix="/kunds", tags=["kunds"])


@router.get(
    "",
    response_model=ApiResponse[list[SessionAvailabilityOut]],
    dependencies=[Depends(rate_limit("public-read", "RATE_LIMIT_PUBLIC_READ"))],
)
def list_sessions(db: Session = Depends(get_db)) -> dict:
    """Public: the 16 sessions with remaining capacity (no personal data).

    ``largest_family_bookable`` is the largest family that still fits in a
    single Kund -- use it in the UI to disable sessions a family cannot book.
    """
    return ok(AdminService(db).session_availability())


@router.get("/{session_id}")
def get_session(session_id: int, _: AdminUser = Depends(require_staff), db: Session = Depends(get_db)) -> dict:
    """Session detail incl. confirmed families, check-ins and (after completion) no-shows."""
    return ok(AdminService(db).session_detail(session_id))


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["SCHEDULED", "CLOSED", "COMPLETED", "CANCELLED"] | None = None
    is_active: bool | None = None


@router.patch("/{session_id}")
def update_session(
    session_id: int,
    body: SessionUpdate,
    request: Request,
    user: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """ADMIN: open/close booking for a session. Capacity cannot be edited via the API."""

    def work(tx: Session) -> dict:
        s = tx.get(EventSession, session_id, with_for_update={"key_share": True})
        if s is None:
            raise NotFound("Session not found")
        previous = {"status": s.status, "is_active": s.is_active}
        if body.status is not None:
            s.status = body.status
        if body.is_active is not None:
            s.is_active = body.is_active
        audit(tx, request_context(request, user), action="SESSION_UPDATED", entity_type="event_session",
              entity_id=session_id, previous=previous, new={"status": s.status, "is_active": s.is_active})
        return {"id": s.id, "status": s.status, "is_active": s.is_active}

    return ok(run_transaction(db, work, label="session_update"))


@router.get("/{session_id}/kunds")
def session_kund_allocation(
    session_id: int,
    page: Pagination = Depends(pagination_params),
    only_occupied: bool = Query(False),
    kund_number: int | None = Query(None, ge=1),
    _: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Kund-wise allocation for one session (capacity, reserved, families)."""
    total, items = AdminService(db).kund_allocations(session_id, page, only_occupied, kund_number)
    return ok(items, page.meta(total))


@router.get("/{session_id}/kund-map")
def session_kund_map(session_id: int, _: AdminUser = Depends(require_staff), db: Session = Depends(get_db)) -> dict:
    """Compact map of all 2,151 Kunds for one session: occ {kund: reserved} (non-empty only),
    blocked and inactive Kund numbers."""
    return ok(DashboardService(db).kund_map(session_id))


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocked: bool


@router.post("/{session_id}/kunds/{kund_number}/block")
def block_kund(
    session_id: int,
    kund_number: int,
    body: BlockIn,
    request: Request,
    user: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Block / unblock an EMPTY Kund for one session (excluded from allocation). Audited."""
    return ok(DashboardService(db).set_block(session_id, kund_number, body.blocked, request_context(request, user)))


@kund_router.get("/{kund_number}")
def get_kund(kund_number: int, _: AdminUser = Depends(require_staff), db: Session = Depends(get_db)) -> dict:
    """One Kund across all 16 sessions."""
    return ok(AdminService(db).kund_detail(kund_number))
