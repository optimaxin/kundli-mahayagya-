"""Excel reporting: sheets, attendance accuracy, no-shows only after completion."""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from app.services.reporting_service import ReportingService
from tests.conftest import AFTER_SESSION_1, DURING_SESSION_1, auth, make_staff, register_ok, registration_payload

SHEETS = ["Dashboard", "Family Bookings", "Family Members", "Session Attendance", "Kund Allocation",
          "Cancellations", "No Shows"]


def _setup(client) -> tuple[dict, dict, str]:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=3, sessions=[1, 3])
    b = register_ok(client, payload=registration_payload(members=2, sessions=[1], address="=HYPERLINK(1) Lane"))
    admin = make_staff("ADMIN")[1]
    clock.freeze(DURING_SESSION_1)
    scanner = make_staff("SCANNER", session_id=1)[1]
    for member in (1, 2):
        r = client.post("/api/v1/scanner/checkin", json={"qr_payload": a["qr_pass"]["qr_payload"], "member_number": member},
                        headers=auth(scanner))
        assert r.json()["data"]["status"] == "CHECKIN_SUCCESS"
    return a, b, admin


def _rows(wb, sheet: str) -> list[tuple]:  # type: ignore[no-untyped-def]
    return [r for r in wb[sheet].iter_rows(min_row=2, values_only=True)]


def test_no_shows_not_calculated_before_session_completes(client, db: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _setup(client)
    summary = ReportingService(db).build_workbook(tmp_path / "r.xlsx", "DAILY", clock.today_local())
    s1 = next(s for s in summary["sessions"] if s["session_id"] == 1)
    assert s1["completed"] is False and s1["no_shows"] is None and s1["checkins"] == 2
    wb = load_workbook(tmp_path / "r.xlsx", read_only=True)
    assert wb.sheetnames == SHEETS
    ns = _rows(wb, "No Shows")
    assert all("not completed" in str(r[3]) for r in ns)


def test_report_accuracy_after_completion(client, db: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    a, b, _ = _setup(client)
    counts_before = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in
                     ("bookings", "family_members", "booking_sessions", "attendance_checkins")}
    clock.freeze(AFTER_SESSION_1)
    summary = ReportingService(db).build_workbook(tmp_path / "f.xlsx", "FINAL", None)
    s1 = next(s for s in summary["sessions"] if s["session_id"] == 1)
    s2 = next(s for s in summary["sessions"] if s["session_id"] == 3)  # next day: not completed yet
    assert s1["registered_members"] == 5 and s1["checkins"] == 2
    assert s1["completed"] is True and s1["no_shows"] == 3
    assert s2["completed"] is False and s2["no_shows"] is None
    wb = load_workbook(tmp_path / "f.xlsx", read_only=True)
    attendance = _rows(wb, "Session Attendance")
    s1_rows = [r for r in attendance if r[0] == 1]
    assert len(s1_rows) == 5 and sum(1 for r in s1_rows if r[8] == "YES") == 2
    no_shows = [r for r in _rows(wb, "No Shows") if r[0] == 1]
    assert len(no_shows) == 3
    assert {(r[3], r[5]) for r in no_shows} == {(a["booking_number"], 3), (b["booking_number"], 1), (b["booking_number"], 2)}
    assert len(_rows(wb, "Kund Allocation")) == 2151 * 16
    assert len(_rows(wb, "Family Bookings")) == 2 and len(_rows(wb, "Family Members")) == 5
    # Formula injection neutralised.
    addresses = [r[6] for r in _rows(wb, "Family Bookings")]
    assert "'=HYPERLINK(1) Lane" in addresses
    assert not any(str(a).startswith("=") for a in addresses)
    # Reporting never deletes or changes records.
    counts_after = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in counts_before}
    assert counts_after == counts_before


def test_export_api_async_job_and_download(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=2, sessions=[1])
    r = client.post("/api/v1/reports/exports", json={"report_type": "DAILY", "report_date": "2026-12-14"},
                    headers=auth(admin_token))
    assert r.status_code == 202
    job_id = r.json()["data"]["id"]
    status = client.get(f"/api/v1/reports/exports/{job_id}", headers=auth(admin_token)).json()["data"]
    assert status["status"] == "COMPLETED", status  # TestClient runs background tasks before returning
    dl = client.get(f"/api/v1/reports/exports/{job_id}/download", headers=auth(admin_token))
    assert dl.status_code == 200
    wb = load_workbook(io.BytesIO(dl.content), read_only=True)
    assert wb.sheetnames == SHEETS
    bad = client.post("/api/v1/reports/exports", json={"report_type": "DAILY"}, headers=auth(admin_token))
    assert bad.status_code == 422


def test_summary_endpoint(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=4, sessions=[3])
    data = client.get("/api/v1/reports/summary?report_date=2026-12-15", headers=auth(admin_token)).json()["data"]
    assert [s["session_id"] for s in data] == [3, 4]
    assert data[0]["registered_members"] == 4 and data[0]["no_shows"] is None
