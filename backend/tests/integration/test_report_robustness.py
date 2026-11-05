"""Report generation: timings, failure handling, ephemeral-disk behaviour and log hygiene."""

from __future__ import annotations

import io
import logging
import os
import time
import uuid
from datetime import timedelta
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.models import ReportJob
from app.services import reporting_service
from app.services.reporting_service import ReportingService, StageTimer
from tests.conftest import STAFF_PASSWORD, auth, register_ok, registration_payload

SHEETS = ["Dashboard", "Family Bookings", "Family Members", "Session Attendance", "Kund Allocation",
          "Cancellations", "No Shows"]


def make_job(client, token: str, **body):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/reports/exports", json=body or {"report_type": "FINAL"}, headers=auth(token))
    assert r.status_code == 202, r.text
    return r.json()["data"]


def reports_dir() -> Path:
    return Path(get_settings().REPORTS_DIR)


def test_job_summary_contains_timings_without_personal_data(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(mobile="9876501234", sessions=[1], email="private.person@example.com",
                                                     address="Plot 5 & 6 Civil Lines"))
    job = make_job(client, admin_token)
    status = client.get(f"/api/v1/reports/exports/{job['id']}", headers=auth(admin_token)).json()["data"]
    t = status["summary"]["timings"]
    assert t["total_s"] > 0 and t["size_bytes"] > 10_000 and t["queue_s"] >= 0
    for stage in ("dashboard.db", "family_bookings.db", "family_members.db", "session_attendance.db",
                  "kund_allocation.db", "cancellations.db", "kund_allocation.write", "connect"):
        assert stage in t["seconds"], stage
    assert t["rows"]["kund_allocation"] == 34416 and t["rows"]["family_bookings"] == 1
    blob = str(status["summary"]["timings"])
    for private in ("9876501234", "private.person", "Civil Lines", "Rahul", "Sharma"):
        assert private not in blob


def test_log_lines_carry_request_id_and_stage_timings_but_no_pii(client, admin_token: str, caplog) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(mobile="9876505678", email="hidden.person@example.com",
                                                     sessions=[1]))
    caplog.set_level(logging.INFO, logger="app.reports")
    job = make_job(client, admin_token)
    client.get(f"/api/v1/reports/exports/{job['id']}/download", headers=auth(admin_token))
    records = {r.getMessage(): r for r in caplog.records if r.name == "app.reports"}
    assert {"report_requested", "report_generated", "report_download_sent"} <= set(records)
    gen = records["report_generated"]
    assert gen.status == "ok" and gen.stages_s["kund_allocation.db"] >= 0 and gen.rows["kund_allocation"] == 34416
    assert gen.total_s > 0 and gen.size_bytes > 10_000 and gen.request_id and gen.job_id == job["id"]
    assert records["report_download_sent"].size_bytes == gen.size_bytes
    logs = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for private in ("9876505678", "hidden.person", STAFF_PASSWORD, "postgresql"):
        assert private not in logs


def test_failed_generation_marks_job_failed_and_leaves_no_files(client, admin_token: str, monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    def boom(self, tmp, report_type, report_date, timer):  # type: ignore[no-untyped-def]
        tmp.write_bytes(b"partial")  # simulate a crash after the temp file was created
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(ReportingService, "_write", boom)
    caplog.set_level(logging.INFO, logger="app.reports")
    job = make_job(client, admin_token)
    status = client.get(f"/api/v1/reports/exports/{job['id']}", headers=auth(admin_token)).json()["data"]
    assert status["status"] == "FAILED" and status["error"] == "RuntimeError"
    assert not list(reports_dir().glob(f"{uuid.UUID(job['id']).hex}*"))  # neither .xlsx nor .tmp left behind
    failed = next(r for r in caplog.records if r.getMessage() == "report_failed")
    assert failed.error_type == "RuntimeError" and failed.status == "failed"
    dl = client.get(f"/api/v1/reports/exports/{job['id']}/download", headers=auth(admin_token))
    assert dl.status_code == 409 and dl.json()["error"]["code"] == "REPORT_NOT_READY"


def test_report_file_removed_from_ephemeral_disk_returns_410(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    job = make_job(client, admin_token)
    (reports_dir() / f"{uuid.UUID(job['id']).hex}.xlsx").unlink()  # e.g. the instance restarted
    dl = client.get(f"/api/v1/reports/exports/{job['id']}/download", headers=auth(admin_token))
    assert dl.status_code == 410 and dl.json()["error"]["code"] == "REPORT_EXPIRED"
    # generating again works
    again = make_job(client, admin_token)
    assert client.get(f"/api/v1/reports/exports/{again['id']}/download", headers=auth(admin_token)).status_code == 200


def test_abandoned_jobs_are_reported_failed_not_preparing_forever(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    job = make_job(client, admin_token)
    db.execute(text("UPDATE report_jobs SET status = 'RUNNING', file_name = NULL, "
                    "created_at = :t, completed_at = NULL WHERE id = :i"),
               {"i": job["id"], "t": clock.now() - timedelta(minutes=30)})
    db.commit()
    status = client.get(f"/api/v1/reports/exports/{job['id']}", headers=auth(admin_token)).json()["data"]
    assert status["status"] == "FAILED" and status["error"] == "ABANDONED"
    # a recent running job is left alone
    db.execute(text("UPDATE report_jobs SET status = 'RUNNING', error = NULL, created_at = :t WHERE id = :i"),
               {"i": job["id"], "t": clock.now()})
    db.commit()
    assert client.get(f"/api/v1/reports/exports/{job['id']}", headers=auth(admin_token)).json()["data"]["status"] == "RUNNING"


def test_old_report_files_are_cleaned_up_when_a_new_report_is_requested(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    d = reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    old, fresh, old_tmp = d / "old.xlsx", d / "fresh.xlsx", d / "crashed.tmp"
    for f in (old, fresh, old_tmp):
        f.write_bytes(b"x")
    stale = time.time() - reporting_service.FILE_RETENTION.total_seconds() - 60
    os.utime(old, (stale, stale))
    os.utime(old_tmp, (stale, stale))
    make_job(client, admin_token)
    assert not old.exists() and not old_tmp.exists() and fresh.exists()
    fresh.unlink()


def test_workbook_contents_survive_special_characters_in_user_text(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(address='Plot 5 & 6, "Civil" Lines', gotra="Bharadwaj",
                                                     sankalp_purpose="Peace & prosperity", sessions=[1]))
    job = make_job(client, admin_token)
    wb = load_workbook(io.BytesIO(client.get(f"/api/v1/reports/exports/{job['id']}/download",
                                              headers=auth(admin_token)).content), read_only=True)
    assert wb.sheetnames == SHEETS
    row = next(wb["Family Bookings"].iter_rows(min_row=2, max_row=2, values_only=True))
    assert row[6] == 'Plot 5 & 6, "Civil" Lines' and row[11] == "Peace & prosperity"
    assert row[13].startswith("1:K1:C")  # session:kund:status aggregated in SQL


def test_kund_allocation_lists_families_per_kund_deterministically(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=3, sessions=[1])
    b = register_ok(client, members=4, sessions=[1])  # best-fit: shares Kund 1 with the first family
    job = make_job(client, admin_token, report_type="DAILY", report_date="2026-12-14")
    wb = load_workbook(io.BytesIO(client.get(f"/api/v1/reports/exports/{job['id']}/download",
                                              headers=auth(admin_token)).content), read_only=True)
    rows = list(wb["Kund Allocation"].iter_rows(min_row=2, values_only=True))
    k1 = next(r for r in rows if r[0] == 1 and r[3] == 1)
    assert (k1[5], k1[6], k1[7]) == (8, 7, 1)
    assert k1[9] == f"{a['booking_number']}:3, {b['booking_number']}:4"  # booking order
    assert len(rows) == 2151 * 2  # every Kund of both sessions of the day, empty ones included


def test_stage_timer_records_seconds_and_counts_only() -> None:
    timer = StageTimer()
    with timer.stage("x"):
        time.sleep(0.01)
    timer.counts = {"sheet": 3}
    report = timer.report()
    assert report["seconds"]["x"] >= 0.01 and report["rows"] == {"sheet": 3}
    assert set(report) == {"seconds", "rows"}


def test_report_job_stays_consistent_when_run_twice_for_same_job(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    job = make_job(client, admin_token)
    reporting_service.run_report_job(uuid.UUID(job["id"]))  # a duplicate run must not corrupt the file or job
    db.expire_all()
    row = db.get(ReportJob, uuid.UUID(job["id"]))
    assert row is not None and row.status == "COMPLETED"
    assert clock.now() - row.completed_at < timedelta(minutes=1)
    assert load_workbook(io.BytesIO((reports_dir() / f"{uuid.UUID(job['id']).hex}.xlsx").read_bytes()),
                         read_only=True).sheetnames == SHEETS
