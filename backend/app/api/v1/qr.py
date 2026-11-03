from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core import clock
from app.core.database import get_db
from app.core.errors import NotFound
from app.core.permissions import request_context, require_roles, require_staff
from app.core.rate_limit import check_rate, client_ip, rate_limit
from app.models import AdminUser
from app.models.enums import Role
from app.schemas.common import ApiResponse, MessageOut, ok
from app.schemas.qr import (
    PassImageIn,
    PassIssuedOut,
    PassOut,
    PassStatusLookupIn,
    PassStatusOut,
    PassTokenIn,
    RevokeIn,
)
from app.services.qr_service import QrService
from app.utils.identifiers import normalize_booking_number

router = APIRouter(prefix="/qr", tags=["qr"])
_pass_limit = Depends(rate_limit("pass-lookup", "RATE_LIMIT_PASS_LOOKUP"))


@router.post("/pass", response_model=ApiResponse[PassOut], dependencies=[_pass_limit])
def get_pass(body: PassTokenIn, db: Session = Depends(get_db)) -> dict:
    """Family pass retrieval for the holder of the pass token.

    The token travels in the request BODY (never in the URL) so it does not
    end up in proxy/access logs. Unknown, revoked and expired tokens return the
    same 404 to avoid an oracle; requests are rate limited per IP.
    """
    return ok(QrService(db).pass_details(body.token))


@router.post(
    "/pass/image",
    dependencies=[_pass_limit],
    responses={200: {"content": {"image/png": {}, "image/svg+xml": {}}, "description": "QR image"}},
)
def get_pass_image(body: PassImageIn, db: Session = Depends(get_db)) -> Response:
    """Download the family QR pass as PNG or SVG (valid passes only)."""
    found = QrService(db).lookup(body.token)
    if not found.usable:
        raise NotFound("Pass not found or no longer valid", code="INVALID_QR")
    data = QrService.render(body.token, body.format, body.scale)
    media = "image/png" if body.format == "png" else "image/svg+xml"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="mahayagya-pass.{body.format}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/status", response_model=ApiResponse[PassStatusOut], dependencies=[_pass_limit])
def pass_status(body: PassStatusLookupIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Public status check by booking number + registered primary mobile.

    Returns no names or contact data. Rate limited per IP and per booking
    number to prevent brute-force enumeration.
    """
    check_rate("pass-status-booking", body.booking_number, "RATE_LIMIT_PASS_LOOKUP")
    check_rate("pass-status-ip", client_ip(request), "RATE_LIMIT_PASS_LOOKUP")
    return ok(QrService(db).status_lookup(body.booking_number, body.primary_mobile))


@router.post("/validate")
def validate_pass(
    body: PassTokenIn,
    _: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERVISOR, Role.SCANNER)),
    db: Session = Depends(get_db),
) -> dict:
    """Backend QR validation for staff tools (no roster; scanners use /scanner/scan)."""
    found = QrService(db).lookup(body.token)
    return ok(
        {
            "valid": found.usable and found.booking is not None and found.booking.status == "CONFIRMED",
            "booking_number": found.booking.booking_number if found.booking else None,
            "booking_status": found.booking.status if found.booking else None,
            "pass_active": bool(found.qr_pass and found.qr_pass.is_active),
            "expired": bool(found.qr_pass and found.qr_pass.expires_at <= clock.now()),
        }
    )


@router.post("/{booking_number}/regenerate", response_model=ApiResponse[PassIssuedOut])
def regenerate_pass(
    booking_number: str, request: Request, user: AdminUser = Depends(require_staff), db: Session = Depends(get_db)
) -> dict:
    """ADMIN/SUPERVISOR help-desk action: revoke the current pass and issue a new one."""
    booking, issued = QrService(db).regenerate(normalize_booking_number(booking_number), request_context(request, user))
    return ok(
        {
            "booking_number": booking.booking_number,
            "token": issued.token,
            "qr_payload": issued.qr_payload,
            "expires_at": issued.expires_at,
        }
    )


@router.post("/{booking_number}/revoke", response_model=ApiResponse[MessageOut])
def revoke_pass(
    booking_number: str,
    body: RevokeIn,
    request: Request,
    user: AdminUser = Depends(require_staff),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke the family's active pass (e.g. reported lost). Regenerate to issue a new one."""
    n = QrService(db).revoke(normalize_booking_number(booking_number), body.reason, request_context(request, user))
    return ok({"message": f"Revoked {n} active pass(es)"})
