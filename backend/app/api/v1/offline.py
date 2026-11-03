from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.core.permissions import request_context, require_roles, require_scanner, require_staff
from app.core.rate_limit import check_rate
from app.models import AdminUser
from app.models.enums import Role
from app.schemas.common import ok
from app.schemas.scanner import CheckinIn, ScanIn
from app.services.offline_sync_service import CloudSyncService, LocalNodeService

router = APIRouter(prefix="/offline", tags=["offline"])


class SyncEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: uuid.UUID
    session_id: int = Field(..., ge=1)
    booking_number: str = Field(..., max_length=20)
    member_number: int = Field(..., ge=1, le=8)
    checked_in_at: datetime


class SyncBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    events: list[SyncEventIn] = Field(..., min_length=1, max_length=500)


# ------------------------------------------------------------- cloud APIs
@router.get("/snapshot/{session_id}")
def export_snapshot(
    session_id: int, request: Request, user: AdminUser = Depends(require_staff), db: Session = Depends(get_db)
) -> dict:
    """Roster snapshot for a venue local server (token hashes only, never raw tokens)."""
    return ok(CloudSyncService(db).export_snapshot(session_id, request_context(request, user)))


@router.post("/sync/checkins")
def ingest_checkins(
    body: SyncBatchIn, request: Request, user: AdminUser = Depends(require_staff), db: Session = Depends(get_db)
) -> dict:
    """Idempotent ingestion of offline check-in events. Re-sending an event_id returns
    the original outcome (``replayed=true``)."""
    results = CloudSyncService(db).ingest_events(
        body.node_id, [e.model_dump() for e in body.events], request_context(request, user)
    )
    return ok(results)


# -------------------------------------------------------- local node APIs
def _require_node_mode() -> None:
    if not get_settings().OFFLINE_NODE_MODE:
        raise NotFound("Not available: this server is not running in OFFLINE_NODE_MODE")


def _local_checks(user: AdminUser, body: ScanIn) -> None:
    if body.session_id is not None:
        raise ValidationFailed("Scanner accounts cannot choose a session", code="SESSION_NOT_ALLOWED")
    check_rate("scanner", str(user.id), "RATE_LIMIT_SCANNER")
    if body.booking_number is not None:
        check_rate("scanner-manual", str(user.id), "RATE_LIMIT_SCANNER_MANUAL")


@router.post("/local/scan", dependencies=[Depends(_require_node_mode)])
def local_scan(body: ScanIn, user: AdminUser = Depends(require_scanner), db: Session = Depends(get_db)) -> dict:
    _local_checks(user, body)
    return ok(LocalNodeService(db).scan(user, body.qr_payload, booking_number=body.booking_number))


@router.post("/local/checkin", dependencies=[Depends(_require_node_mode)])
def local_checkin(body: CheckinIn, user: AdminUser = Depends(require_scanner), db: Session = Depends(get_db)) -> dict:
    _local_checks(user, body)
    return ok(LocalNodeService(db).checkin(user, body.qr_payload, body.member_number, body.event_id,
                                           booking_number=body.booking_number))


@router.get("/local/status", dependencies=[Depends(_require_node_mode)])
def local_status(
    _: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERVISOR, Role.SCANNER)), db: Session = Depends(get_db)
) -> dict:
    return ok(LocalNodeService(db).status())
