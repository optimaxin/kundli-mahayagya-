from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import request_context, require_admin, require_staff
from app.models import AdminUser
from app.models.enums import Role
from app.repositories.misc_repositories import AuditRepository, IdempotencyRepository, UserRepository
from app.schemas.auth import StaffPasswordReset, StaffUserCreate, StaffUserOut, StaffUserUpdate
from app.schemas.common import ApiResponse, Pagination, ok, pagination_params
from app.services.admin_service import AdminService
from app.services.audit_service import audit
from app.services.auth_service import AuthService
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard")
def dashboard(_: AdminUser = Depends(require_staff), db: Session = Depends(get_db)) -> dict:
    """Totals: registrations, confirmed/cancelled bookings, unique members, capacity, check-ins."""
    return ok(AdminService(db).dashboard())


@router.get("/analytics")
def analytics(_: AdminUser = Depends(require_staff), db: Session = Depends(get_db)) -> dict:
    """Dashboard data in the shape used by the admin console (cached briefly server-side)."""
    return ok(DashboardService(db).analytics())


@router.get("/integrity")
def integrity(_: AdminUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Reconciliation: reserved_count vs. confirmed reservations, member counts, cancellations."""
    return ok(AdminService(db).integrity_report())


@router.get("/audit-logs")
def audit_logs(
    page: Pagination = Depends(pagination_params),
    action: str | None = Query(None, max_length=64),
    entity_type: str | None = Query(None, max_length=64),
    entity_id: str | None = Query(None, max_length=64),
    actor_id: uuid.UUID | None = None,
    _: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    total, rows = AuditRepository(db).list(
        action=action, entity_type=entity_type, entity_id=entity_id, actor_id=actor_id,
        offset=page.offset, limit=page.page_size,
    )
    items = [
        {
            "id": r.id, "actor_id": r.actor_id, "actor_role": r.actor_role, "action": r.action,
            "entity_type": r.entity_type, "entity_id": r.entity_id, "previous_values": r.previous_values,
            "new_values": r.new_values, "request_id": r.request_id, "created_at": r.created_at,
        }
        for r in rows
    ]
    return ok(items, page.meta(total))


@router.get("/users", response_model=ApiResponse[list[StaffUserOut]])
def list_users(
    page: Pagination = Depends(pagination_params),
    role: Role | None = None,
    _: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    total, users = UserRepository(db).list(role=role.value if role else None, offset=page.offset, limit=page.page_size)
    return ok([StaffUserOut.model_validate(u).model_dump() for u in users], page.meta(total))


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=ApiResponse[StaffUserOut])
def create_user(
    body: StaffUserCreate, request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    """Create a SUPERVISOR / SCANNER (or ADMIN) account. Scanners get an assigned session."""
    created = AuthService(db).create_user(
        full_name=body.full_name, email=body.email, password=body.password, role=body.role.value,
        assigned_session_id=body.assigned_session_id, ctx=request_context(request, user),
    )
    return ok(StaffUserOut.model_validate(created).model_dump())


@router.patch("/users/{user_id}", response_model=ApiResponse[StaffUserOut])
def update_user(
    user_id: uuid.UUID,
    body: StaffUserUpdate,
    request: Request,
    user: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Rename, (de)activate, or (re)assign a scanner's session. Deactivation revokes tokens."""
    updated = AuthService(db).update_user(user_id, body.model_dump(), request_context(request, user))
    return ok(StaffUserOut.model_validate(updated).model_dump())


@router.post("/users/{user_id}/reset-password", response_model=ApiResponse[StaffUserOut])
def reset_user_password(
    user_id: uuid.UUID,
    body: StaffPasswordReset,
    request: Request,
    user: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """ADMIN sets a new password for a SCANNER/SUPERVISOR account. All of that account's sessions are
    revoked and any login lockout is cleared. Not available for ADMIN accounts or your own account."""
    updated = AuthService(db).reset_password(user_id, body.new_password, request_context(request, user))
    return ok(StaffUserOut.model_validate(updated).model_dump())


@router.post("/maintenance/purge-idempotency-secrets")
def purge_idempotency_secrets(
    request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    """Remove encrypted replay secrets from expired idempotency records (also run by cron)."""
    n = IdempotencyRepository(db).purge_secrets()
    audit(db, request_context(request, user), action="IDEMPOTENCY_PURGED", entity_type="idempotency_records",
          entity_id=None, new={"purged": n})
    db.commit()
    return ok({"purged": n})
