from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import request_context, require_admin
from app.models import AdminUser
from app.models.enums import ReportType
from app.schemas.common import ok
from app.services.audit_service import audit
from app.services.reporting_service import ReportingService, download_name, run_report_job

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
    background.add_task(run_report_job, job.id)
    return ok(_job_out(job))


@router.get("/exports/{job_id}")
def get_export(job_id: uuid.UUID, _: AdminUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return ok(_job_out(ReportingService(db).get_job(job_id)))


@router.get("/exports/{job_id}/download")
def download_export(
    job_id: uuid.UUID, request: Request, user: AdminUser = Depends(require_admin), db: Session = Depends(get_db)
) -> FileResponse:
    service = ReportingService(db)
    job = service.get_job(job_id)
    path = service.job_file(job)
    audit(db, request_context(request, user), action="REPORT_DOWNLOADED", entity_type="report_job",
          entity_id=str(job.id))
    db.commit()
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_name(job),
        headers={"Cache-Control": "no-store"},
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
