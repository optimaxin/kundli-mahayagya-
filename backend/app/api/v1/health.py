from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def liveness() -> dict:
    """Process is up (no dependencies checked)."""
    return {"success": True, "data": {"status": "ok", "time": clock.now().isoformat()}}


@router.get("/ready")
def readiness(db: Session = Depends(get_db)) -> JSONResponse:
    """Database reachable, migrations applied and seed data present."""
    try:
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        sessions = db.execute(text("SELECT count(*) FROM event_sessions")).scalar() or 0
        kunds = db.execute(text("SELECT count(*) FROM kunds")).scalar() or 0
    except Exception:
        return JSONResponse(status_code=503, content={"success": False, "data": {"status": "database_unavailable"}})
    s = get_settings()
    seeded = sessions == s.EVENT_DAYS * 2 and kunds == s.TOTAL_KUNDS
    body = {
        "status": "ready" if seeded else "not_seeded",
        "migration": version,
        "sessions": sessions,
        "kunds": kunds,
        "offline_node_mode": s.OFFLINE_NODE_MODE,
    }
    return JSONResponse(status_code=200 if seeded else 503, content={"success": seeded, "data": body})
