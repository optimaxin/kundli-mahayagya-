"""Authentication dependencies and role-based access control.

Permission matrix (see docs/api-documentation.md):

=====================================  =====  ==========  =======
Capability                             ADMIN  SUPERVISOR  SCANNER
=====================================  =====  ==========  =======
Dashboard / capacity / reports          yes      yes        no
Booking search by booking number        yes      yes        no
Booking search by mobile (audited)      yes      yes        no
Cancel bookings                         yes      yes        no
Regenerate / revoke QR passes           yes      yes        no
Offline snapshot / sync ingest          yes      yes        no
Audit logs, staff user management       yes      no         no
Integrity reconciliation                yes      no         no
Scan / check-in (assigned session)      no       no         yes
=====================================  =====  ==========  =======
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.models import AdminUser
from app.models.enums import Role
from app.services.audit_service import RequestContext

bearer_scheme = HTTPBearer(auto_error=False, description="JWT obtained from POST /api/v1/auth/login")


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(str(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Invalid or expired token", code="INVALID_TOKEN") from exc
    user = db.get(AdminUser, user_id)
    # Re-check account state on every request: deactivation, role change or
    # token_version bump (logout / password change) take effect immediately.
    if (
        user is None
        or not user.is_active
        or user.token_version != payload.get("ver")
        or user.role != payload.get("role")
    ):
        raise Unauthorized("Invalid or expired token", code="INVALID_TOKEN")
    request.state.user_id = str(user.id)
    return user


def require_roles(*roles: Role) -> Callable[..., AdminUser]:
    allowed = {r.value for r in roles}

    def dependency(user: AdminUser = Depends(get_current_user)) -> AdminUser:
        if user.role not in allowed:
            raise Forbidden("You do not have permission to perform this action")
        return user

    return dependency


def request_context(request: Request, user: AdminUser | None = None) -> RequestContext:
    return RequestContext(
        actor_id=user.id if user else None,
        actor_role=user.role if user else None,
        request_id=getattr(request.state, "request_id", None),
    )


require_admin = require_roles(Role.ADMIN)
require_staff = require_roles(Role.ADMIN, Role.SUPERVISOR)
require_scanner = require_roles(Role.SCANNER)
