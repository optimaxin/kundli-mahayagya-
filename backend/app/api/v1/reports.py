from __future__ import annotations

import logging
import time
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.core.permissions import request_context, require_admin
from app.models import AdminUser
from app.models.enums import ReportType
from app.schemas.common import ok
from app.services.audit_service import audit
from app.services.reporting_service import ReportingService, download_name, run_report_job

logger = logging.getLogger("app.reports")

# Reports contain personal data of every family: ADMIN only (SUPERVISOR and SCANNER get 403).
router = APIRouter(prefix="/reports", tags=["reports"])


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_type: ReportType = ReportType.FINAL
    report_date: date | None = None


def _job_out(job) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": job.id, "report_type": job.report_type, "report_date": job.report_date, "status": job.status,
        "file_name": job.file_name, "error": job.error, "summary": job.summary,
        "created_at": job.created_at, "started_at": job.started_at, "completed_at": job.completed_at,
    }


@router.post("/exports", status_code=status.HTTP_202_ACCEPTED)
def create_export(
    body: ExportRequest,
    background: BackgroundTasks,
    request: Request,
    user: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Queue an Excel export (DAILY needs ``report_date``). Generation runs asynchronously;
    poll ``GET /reports/exports/{id}`` and download when COMPLETED."""
    job = ReportingService(db).create_job(body.report_type.value, body.report_date, request_context(request, user))
    request_id = getattr(request.state, "request_id", None)
    logger.info("report_requested", extra={"request_id": request_id, "job_id": str(job.id),
                                           "report_type": job.report_type})
    background.add_task(run_report_job, job.id, request_id)
    return ok(_job_out(job))


@router.get("/exports/{job_id}")
def get_export(job_id: uuid.UUID, _: AdminUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return ok(_job_out(ReportingService(db).get_job(job_id)))


@router.get("/exports/{job_id}/download")
def download_export(
    job_id: uuid.UUID, request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)
) -> FileResponse:
    started = time.perf_counter()
    service = ReportingService(db)
    job = service.get_job(job_id)
    path = service.job_file(job)
    audit(db, request_context(request, user), action="REPORT_DOWNLOADED", entity_type="report_job",
          entity_id=str(job.id))
    db.commit()
    size = path.stat().st_size
    request_id = getattr(request.state, "request_id", None)
    prepared_s = time.perf_counter() - started

    def sent() -> None:  # runs after the last byte has been handed to the client connection
        logger.info("report_download_sent", extra={
            "request_id": request_id, "job_id": str(job.id), "size_bytes": size,
            "prepare_s": round(prepared_s, 3), "send_s": round(time.perf_counter() - started - prepared_s, 3)})

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_name(job),
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(sent),
    )


@router.get("/summary")
def summary(
    report_date: date | None = None, _: AdminUser = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    """Session-wise registrations, check-ins, utilisation and (completed sessions only) no-shows."""
    service = ReportingService(db)
    kind = ReportType.DAILY.value if report_date else ReportType.FINAL.value
    sessions = service._sessions_in_scope(kind, report_date)  # noqa: SLF001
    return ok(service.session_summary(sessions))
