from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, request_context
from app.core.rate_limit import check_rate, rate_limit
from app.models import AdminUser
from app.schemas.auth import ChangePasswordRequest, LoginRequest, StaffUserOut, TokenOut
from app.schemas.common import ApiResponse, MessageOut, ok
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
_login_limit = Depends(rate_limit("login", "RATE_LIMIT_LOGIN"))


def _login(db: Session, request: Request, email: str, password: str) -> dict:
    check_rate("login-account", email.lower(), "RATE_LIMIT_LOGIN")
    token, expires, user = AuthService(db).login(email, password, request_context(request))
    return {"access_token": token, "token_type": "bearer", "expires_at": expires, "role": user.role}


@router.post("/login", response_model=ApiResponse[TokenOut], dependencies=[_login_limit])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Staff login (ADMIN / SUPERVISOR / SCANNER). Returns a short-lived JWT."""
    return ok(_login(db, request, body.email, body.password))


@router.post("/token", response_model=TokenOut, dependencies=[_login_limit], include_in_schema=True)
def token(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    """OAuth2 password form variant (used by the Swagger UI "Authorize" button)."""
    return _login(db, request, form.username, form.password)


@router.get("/me", response_model=ApiResponse[StaffUserOut])
def me(user: AdminUser = Depends(get_current_user)) -> dict:
    return ok(StaffUserOut.model_validate(user).model_dump())


@router.post("/logout", response_model=ApiResponse[MessageOut])
def logout(request: Request, user: AdminUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Invalidates ALL tokens of the current user (token version bump)."""
    AuthService(db).logout_everywhere(user, request_context(request, user))
    return ok({"message": "Logged out"})


@router.post("/change-password", response_model=ApiResponse[MessageOut])
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    check_rate("change-password", str(user.id), "RATE_LIMIT_LOGIN")
    AuthService(db).change_password(user, body.current_password, body.new_password, request_context(request, user))
    return ok({"message": "Password changed. Please log in again."})
