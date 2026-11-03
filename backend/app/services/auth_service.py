"""Staff authentication (ADMIN / SUPERVISOR / SCANNER) with lockout and auditing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import get_settings
from app.core.database import run_transaction
from app.core.errors import AppError, Conflict, NotFound, TooManyRequests, Unauthorized, ValidationFailed
from app.models import AdminUser
from app.models.enums import Role
from app.repositories.misc_repositories import UserRepository
from app.repositories.session_repository import SessionRepository
from app.services.audit_service import RequestContext, audit

_INVALID = "Invalid email or password"
_EMAIL = TypeAdapter(EmailStr)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def login(self, email: str, password: str, ctx: RequestContext) -> tuple[str, datetime, AdminUser]:
        settings = get_settings()

        def work(db: Session) -> tuple[str, datetime, AdminUser] | AppError:
            users = UserRepository(db)
            user = users.by_email(email, for_update=True)
            now = clock.now()
            if user is None:
                security.verify_password(password, None)  # equalise timing
                return Unauthorized(_INVALID, code="INVALID_CREDENTIALS")
            if user.locked_until and user.locked_until > now:
                return TooManyRequests(
                    "Too many failed login attempts. Try again later.",
                    code="ACCOUNT_LOCKED",
                    headers={"Retry-After": str(int((user.locked_until - now).total_seconds()) + 1)},
                )
            if not user.is_active or not security.verify_password(password, user.password_hash):
                user.failed_login_count += 1
                details: dict[str, Any] = {"failed_count": user.failed_login_count}
                if user.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                    user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                    user.failed_login_count = 0
                    details["locked_until"] = user.locked_until.isoformat()
                audit(
                    db, RequestContext(actor_id=user.id, actor_role=user.role, request_id=ctx.request_id),
                    action="LOGIN_FAILED", entity_type="admin_user", entity_id=str(user.id), new=details,
                )
                # Commit the failure counter, then report the error.
                return Unauthorized(_INVALID, code="INVALID_CREDENTIALS")
            if security.password_needs_rehash(user.password_hash):
                user.password_hash = security.hash_password(password)
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            minutes = (
                settings.SCANNER_TOKEN_EXPIRE_MINUTES
                if user.role == Role.SCANNER.value
                else settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
            token, expires = security.create_access_token(
                subject=str(user.id), role=user.role, token_version=user.token_version, expires_minutes=minutes
            )
            audit(
                db, RequestContext(actor_id=user.id, actor_role=user.role, request_id=ctx.request_id),
                action="LOGIN_SUCCESS", entity_type="admin_user", entity_id=str(user.id),
            )
            return token, expires, user

        result = run_transaction(self.db, work, label="login")
        if isinstance(result, AppError):
            raise result
        return result

    def logout_everywhere(self, user: AdminUser, ctx: RequestContext) -> None:
        def work(db: Session) -> None:
            u = db.get(AdminUser, user.id, with_for_update=True)
            assert u is not None
            u.token_version += 1
            audit(db, ctx, action="LOGOUT_ALL", entity_type="admin_user", entity_id=str(u.id))

        run_transaction(self.db, work, label="logout")

    def change_password(self, user: AdminUser, current: str, new: str, ctx: RequestContext) -> None:
        def work(db: Session) -> None:
            u = db.get(AdminUser, user.id, with_for_update=True)
            assert u is not None
            if not security.verify_password(current, u.password_hash):
                raise Unauthorized("Current password is incorrect", code="INVALID_CREDENTIALS")
            u.password_hash = security.hash_password(new)
            u.token_version += 1  # invalidate existing tokens
            audit(db, ctx, action="PASSWORD_CHANGED", entity_type="admin_user", entity_id=str(u.id))

        run_transaction(self.db, work, label="change_password")

    # ---------------------------------------------------- user management
    def create_user(
        self,
        *,
        full_name: str,
        email: str,
        password: str,
        role: str,
        assigned_session_id: int | None,
        ctx: RequestContext,
    ) -> AdminUser:
        security.validate_password_strength(password)
        try:
            # Same rules as the login endpoint, so no account is created that cannot log in.
            email = _EMAIL.validate_python(email).lower()
        except ValidationError as exc:
            raise ValidationFailed("Invalid email address", code="INVALID_EMAIL") from exc

        def work(db: Session) -> AdminUser:
            if assigned_session_id is not None and SessionRepository(db).get(assigned_session_id) is None:
                raise ValidationFailed("Assigned session does not exist", code="INVALID_SESSION")
            user = AdminUser(
                id=uuid.uuid4(),
                full_name=full_name,
                email=email.lower(),
                password_hash=security.hash_password(password),
                role=role,
                assigned_session_id=assigned_session_id,
            )
            db.add(user)
            try:
                db.flush()
            except IntegrityError as exc:
                raise Conflict("A staff account with this email already exists", code="EMAIL_EXISTS") from exc
            audit(
                db, ctx, action="STAFF_USER_CREATED", entity_type="admin_user", entity_id=str(user.id),
                new={"role": role, "assigned_session_id": assigned_session_id},
            )
            return user

        return run_transaction(self.db, work, label="create_user")

    def update_user(self, user_id: uuid.UUID, changes: dict[str, Any], ctx: RequestContext) -> AdminUser:
        def work(db: Session) -> AdminUser:
            user = db.get(AdminUser, user_id, with_for_update=True)
            if user is None:
                raise NotFound("Staff user not found")
            if ctx.actor_id == user.id and changes.get("is_active") is False:
                raise ValidationFailed("You cannot deactivate your own account")
            previous = {"full_name": user.full_name, "is_active": user.is_active,
                        "assigned_session_id": user.assigned_session_id}
            if changes.get("full_name") is not None:
                user.full_name = changes["full_name"]
            if changes.get("is_active") is not None:
                user.is_active = changes["is_active"]
                if not user.is_active:
                    user.token_version += 1
            if changes.get("clear_assigned_session"):
                user.assigned_session_id = None
            elif changes.get("assigned_session_id") is not None:
                if user.role != Role.SCANNER.value:
                    raise ValidationFailed("Only SCANNER accounts can be assigned to a session")
                if SessionRepository(db).get(changes["assigned_session_id"]) is None:
                    raise ValidationFailed("Assigned session does not exist", code="INVALID_SESSION")
                user.assigned_session_id = changes["assigned_session_id"]
            audit(
                db, ctx, action="STAFF_USER_UPDATED", entity_type="admin_user", entity_id=str(user.id),
                previous=previous,
                new={"full_name": user.full_name, "is_active": user.is_active,
                     "assigned_session_id": user.assigned_session_id},
            )
            return user

        return run_transaction(self.db, work, label="update_user")
