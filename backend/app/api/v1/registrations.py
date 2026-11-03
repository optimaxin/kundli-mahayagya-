from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.rate_limit import rate_limit, registration_admission
from app.schemas.common import ApiResponse, ErrorResponse, ok
from app.schemas.registration import RegistrationOut, RegistrationRequest
from app.services.audit_service import RequestContext
from app.services.registration_service import RegistrationService

router = APIRouter(prefix="/registrations", tags=["registrations"])
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[RegistrationOut],
    dependencies=[Depends(rate_limit("registration", "RATE_LIMIT_REGISTRATION"))],
    responses={
        409: {"model": ErrorResponse, "description": "CAPACITY_UNAVAILABLE / DUPLICATE_BOOKING"},
        422: {"model": ErrorResponse, "description": "Validation error / IDEMPOTENCY_KEY_REUSED"},
        429: {"model": ErrorResponse, "description": "Rate limited"},
        503: {"model": ErrorResponse, "description": "Admission control: system busy, retry later"},
    },
)
async def create_registration(
    body: RegistrationRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
        description="Unique per submission attempt (e.g. a UUID). Retrying with the same key "
        "and body returns the original booking instead of creating a new one.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Register a family (1-8 members) for one or more sessions.

    All selected sessions are allocated atomically (one Kund per session,
    best-fit, never split). If any session cannot be allocated, nothing is
    booked and a 409 CAPACITY_UNAVAILABLE explains which sessions failed.
    The response contains the family's QR pass token -- shown only here.
    """
    settings = get_settings()
    if idempotency_key is None and settings.REQUIRE_IDEMPOTENCY_KEY:
        raise AppError("Idempotency-Key header is required", code="IDEMPOTENCY_KEY_REQUIRED", status_code=400)
    if idempotency_key is not None and not _KEY_RE.match(idempotency_key):
        raise AppError(
            "Idempotency-Key must be 8-128 characters of letters, digits, '-', '_', ':' or '.'",
            code="IDEMPOTENCY_KEY_INVALID",
            status_code=400,
        )
    ctx = RequestContext(request_id=getattr(request.state, "request_id", None))
    service = RegistrationService(db)

    async def _run() -> object:
        return await run_in_threadpool(service.register, body, idempotency_key=idempotency_key, ctx=ctx)

    result = await registration_admission(request).run(_run)
    if result.replayed:  # type: ignore[attr-defined]
        response.headers["Idempotent-Replayed"] = "true"
    return ok(result.payload)  # type: ignore[attr-defined]
