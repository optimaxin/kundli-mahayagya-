"""Organizer Console: admin provisioning (CLI), login/RBAC, volunteer management, Excel report download.

These tests only ever use the local test database (guarded below); they never touch production.
"""

from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import get_settings
from scripts import create_admin
from tests.conftest import STAFF_PASSWORD, auth, ist, make_staff, register_ok

SHEETS = ["Dashboard", "Family Bookings", "Family Members", "Session Attendance", "Kund Allocation",
          "Cancellations", "No Shows"]
NEW_PASSWORD = "Fresh-Volunteer-Pass9"


@pytest.fixture(autouse=True)
def _never_production() -> None:
    url = get_settings().DATABASE_URL
    assert "localhost" in url or "127.0.0.1" in url, "organizer-console tests must run on the local test DB"
    assert get_settings().APP_ENV == "test"


def login(client, email: str, password: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# ============================================================ admin provisioning (CLI)
def run_cli(monkeypatch, argv: list[str], password: str = STAFF_PASSWORD, confirm: str | None = None) -> int:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    if confirm is not None:
        monkeypatch.setattr("builtins.input", lambda _prompt="": confirm)
    return create_admin.main(argv)


def test_cli_creates_admin_with_hashed_password_and_audit(monkeypatch, db: Session, capsys) -> None:  # type: ignore[no-untyped-def]
    code = run_cli(monkeypatch, ["--email", "Owner@Example.org", "--name", "Event Owner", "--password-stdin"])
    assert code == 0
    out = capsys.readouterr()
    assert "Created ADMIN account owner@example.org" in out.out
    assert STAFF_PASSWORD not in out.out + out.err  # password never printed
    assert "mahayagya@" not in out.out  # DB credentials never printed (only host:port/db)
    row = db.execute(text("SELECT role, password_hash, is_active FROM admin_users WHERE email='owner@example.org'")).one()
    assert row.role == "ADMIN" and row.is_active and row.password_hash.startswith("$argon2id$")
    assert STAFF_PASSWORD not in row.password_hash
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action='STAFF_USER_CREATED' "
                           "AND request_id='cli:create_admin'")).scalar() == 1


def test_cli_never_overwrites_an_existing_account(monkeypatch, db: Session, capsys) -> None:  # type: ignore[no-untyped-def]
    assert run_cli(monkeypatch, ["--email", "owner@example.org", "--name", "Owner", "--password-stdin"]) == 0
    before = db.execute(text("SELECT password_hash, role FROM admin_users")).one()
    code = run_cli(monkeypatch, ["--email", "OWNER@example.org", "--name", "Someone Else", "--role", "SUPERVISOR",
                                 "--password-stdin"], password="Another-Strong-Pass1")
    assert code == create_admin.EXIT_EXISTS
    assert "already exists" in capsys.readouterr().err
    db.expire_all()
    assert db.execute(text("SELECT password_hash, role FROM admin_users")).one() == before
    assert db.execute(text("SELECT count(*) FROM admin_users")).scalar() == 1


def test_cli_rejects_weak_password_and_bad_input(monkeypatch, db: Session) -> None:  # type: ignore[no-untyped-def]
    for weak in ("admin123", "password123", "admin", "Short1A"):
        assert run_cli(monkeypatch, ["--email", "a@example.org", "--name", "Ab Cd", "--password-stdin"],
                       password=weak) == create_admin.EXIT_INPUT
    assert run_cli(monkeypatch, ["--email", "not-an-email", "--name", "Ab Cd", "--password-stdin"]) == create_admin.EXIT_INPUT
    assert run_cli(monkeypatch, ["--email", "s@example.org", "--name", "Ab Cd", "--session", "1",
                                 "--password-stdin"]) == create_admin.EXIT_INPUT  # session only for SCANNER
    assert db.execute(text("SELECT count(*) FROM admin_users")).scalar() == 0


def test_cli_requires_explicit_production_confirmation(monkeypatch, db: Session) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "APP_ENV", "production")
    argv = ["--email", "prod@example.org", "--name", "Prod Admin"]
    # --password-stdin without --yes-production is refused outright
    assert run_cli(monkeypatch, [*argv, "--password-stdin"]) == create_admin.EXIT_INPUT
    # interactive confirmation answered wrongly -> nothing happens
    monkeypatch.setattr("getpass.getpass", lambda _p="": STAFF_PASSWORD)
    assert run_cli(monkeypatch, argv, confirm="yes") == create_admin.EXIT_INPUT
    assert db.execute(text("SELECT count(*) FROM admin_users")).scalar() == 0
    # typed PRODUCTION -> created
    assert run_cli(monkeypatch, argv, confirm="PRODUCTION") == 0
    assert db.execute(text("SELECT role FROM admin_users WHERE email='prod@example.org'")).scalar() == "ADMIN"


def test_cli_hidden_prompt_requires_matching_passwords(monkeypatch, db: Session) -> None:  # type: ignore[no-untyped-def]
    answers = iter([STAFF_PASSWORD, "Different-Pass-123"])
    monkeypatch.setattr("getpass.getpass", lambda _p="": next(answers))
    assert create_admin.main(["--email", "x@example.org", "--name", "Xy Zw"]) == create_admin.EXIT_INPUT
    assert db.execute(text("SELECT count(*) FROM admin_users")).scalar() == 0


# ============================================================ admin login & RBAC
def test_admin_login_and_wrong_credentials_look_identical(client) -> None:  # type: ignore[no-untyped-def]
    make_staff("ADMIN", email="boss@example.org")
    ok = login(client, "boss@example.org", STAFF_PASSWORD)
    assert ok.status_code == 200 and ok.json()["data"]["role"] == "ADMIN"
    token = ok.json()["data"]["access_token"]
    assert client.get("/api/v1/admin/dashboard", headers=auth(token)).status_code == 200
    bad_pw = login(client, "boss@example.org", "Wrong-Password-99")
    unknown = login(client, "nobody@example.org", "Wrong-Password-99")
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json()["error"] == unknown.json()["error"]  # no account-existence oracle


def test_expired_admin_token_rejected(client) -> None:  # type: ignore[no-untyped-def]
    user, _ = make_staff("ADMIN")
    token, _exp = security.create_access_token(subject=str(user.id), role="ADMIN", token_version=1, expires_minutes=30)
    assert client.get("/api/v1/admin/dashboard", headers=auth(token)).status_code == 200
    clock.freeze(clock.now().replace(year=clock.now().year + 1))
    r = client.get("/api/v1/admin/dashboard", headers=auth(token))
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_TOKEN"


def test_disabled_account_cannot_log_in(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    vol, _ = make_staff("SCANNER", session_id=1, email="vol@example.org")
    client.patch(f"/api/v1/admin/users/{vol.id}", json={"is_active": False}, headers=auth(admin_token))
    assert login(client, "vol@example.org", STAFF_PASSWORD).status_code == 401


def test_scanner_denied_every_admin_only_page(client) -> None:  # type: ignore[no-untyped-def]
    _, scanner = make_staff("SCANNER", session_id=1)
    for method, path in [("get", "/api/v1/admin/dashboard"), ("get", "/api/v1/admin/analytics"),
                         ("get", "/api/v1/admin/users"), ("get", "/api/v1/admin/audit-logs"),
                         ("get", "/api/v1/bookings"), ("get", "/api/v1/reports/summary")]:
        assert getattr(client, method)(path, headers=auth(scanner)).status_code == 403, path


# ============================================================ volunteer management
def test_admin_creates_volunteer_with_session(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/admin/users", headers=auth(admin_token), json={
        "full_name": "Gate Seva", "email": "Gate.Seva@example.org", "password": STAFF_PASSWORD,
        "role": "SCANNER", "assigned_session_id": 4})
    assert r.status_code == 201
    body = r.json()["data"]
    assert body["email"] == "gate.seva@example.org" and body["assigned_session_id"] == 4
    assert not {"password", "password_hash", "token_version"} & set(body)
    listing = client.get("/api/v1/admin/users?page_size=200", headers=auth(admin_token)).text
    assert "argon2" not in listing and STAFF_PASSWORD not in listing
    assert login(client, "gate.seva@example.org", STAFF_PASSWORD).json()["data"]["role"] == "SCANNER"
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action='STAFF_USER_CREATED'")).scalar() >= 1


def test_duplicate_volunteer_email_rejected(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    payload = {"full_name": "Gate Seva", "email": "dup@example.org", "password": STAFF_PASSWORD, "role": "SCANNER",
               "assigned_session_id": 1}
    assert client.post("/api/v1/admin/users", json=payload, headers=auth(admin_token)).status_code == 201
    r = client.post("/api/v1/admin/users", json={**payload, "email": "DUP@example.org"}, headers=auth(admin_token))
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_EXISTS"


def test_session_assignment_validated(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    base = {"full_name": "Gate Seva", "password": STAFF_PASSWORD, "role": "SCANNER"}
    bad = client.post("/api/v1/admin/users", json={**base, "email": "a1@example.org", "assigned_session_id": 99},
                      headers=auth(admin_token))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SESSION"
    sup = client.post("/api/v1/admin/users", json={**base, "email": "a2@example.org", "role": "SUPERVISOR",
                                                   "assigned_session_id": 1}, headers=auth(admin_token))
    assert sup.status_code == 422  # only SCANNER accounts get a session
    vol = client.post("/api/v1/admin/users", json={**base, "email": "a3@example.org", "assigned_session_id": 1},
                      headers=auth(admin_token)).json()["data"]
    move = client.patch(f"/api/v1/admin/users/{vol['id']}", json={"assigned_session_id": 16}, headers=auth(admin_token))
    assert move.json()["data"]["assigned_session_id"] == 16
    assert client.patch(f"/api/v1/admin/users/{vol['id']}", json={"assigned_session_id": 17},
                        headers=auth(admin_token)).status_code == 422


def test_scanner_cannot_create_users_or_change_own_role_or_session(client) -> None:  # type: ignore[no-untyped-def]
    me, scanner = make_staff("SCANNER", session_id=1)
    new = {"full_name": "Evil Twin", "email": "evil@example.org", "password": STAFF_PASSWORD, "role": "ADMIN"}
    assert client.post("/api/v1/admin/users", json=new, headers=auth(scanner)).status_code == 403
    for patch in ({"assigned_session_id": 5}, {"is_active": True}):
        assert client.patch(f"/api/v1/admin/users/{me.id}", json=patch, headers=auth(scanner)).status_code == 403
    # role is not an updatable field at all, even for admins
    _, admin = make_staff("ADMIN")
    assert client.patch(f"/api/v1/admin/users/{me.id}", json={"role": "ADMIN"}, headers=auth(admin)).status_code == 422
    assert client.post(f"/api/v1/admin/users/{me.id}/reset-password", json={"new_password": NEW_PASSWORD},
                       headers=auth(scanner)).status_code == 403


def test_activate_and_deactivate_volunteer(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    vol, vol_token = make_staff("SCANNER", session_id=1, email="toggle@example.org")
    off = client.patch(f"/api/v1/admin/users/{vol.id}", json={"is_active": False}, headers=auth(admin_token))
    assert off.json()["data"]["is_active"] is False
    assert client.get("/api/v1/scanner/me", headers=auth(vol_token)).status_code == 401  # existing token revoked
    on = client.patch(f"/api/v1/admin/users/{vol.id}", json={"is_active": True}, headers=auth(admin_token))
    assert on.json()["data"]["is_active"] is True
    assert login(client, "toggle@example.org", STAFF_PASSWORD).status_code == 200


def test_admin_resets_volunteer_password(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    vol, vol_token = make_staff("SCANNER", session_id=2, email="forgot@example.org")
    for _ in range(get_settings().LOGIN_MAX_FAILED_ATTEMPTS):  # get the account locked out
        login(client, "forgot@example.org", "Wrong-Password-99")
    weak = client.post(f"/api/v1/admin/users/{vol.id}/reset-password", json={"new_password": "admin123"},
                       headers=auth(admin_token))
    assert weak.status_code == 422
    r = client.post(f"/api/v1/admin/users/{vol.id}/reset-password", json={"new_password": NEW_PASSWORD},
                    headers=auth(admin_token))
    assert r.status_code == 200 and "password" not in r.text.lower().replace("reset-password", "")
    assert client.get("/api/v1/scanner/me", headers=auth(vol_token)).status_code == 401  # old sessions revoked
    assert login(client, "forgot@example.org", STAFF_PASSWORD).status_code == 401
    assert login(client, "forgot@example.org", NEW_PASSWORD).status_code == 200  # lockout cleared
    audit = db.execute(text("SELECT new_values::text FROM audit_logs WHERE action='STAFF_PASSWORD_RESET'")).scalar_one()
    assert NEW_PASSWORD not in audit


def test_password_reset_not_allowed_for_admins_or_self(client) -> None:  # type: ignore[no-untyped-def]
    me, my_token = make_staff("ADMIN")
    other_admin, _ = make_staff("ADMIN")
    r1 = client.post(f"/api/v1/admin/users/{other_admin.id}/reset-password", json={"new_password": NEW_PASSWORD},
                     headers=auth(my_token))
    assert r1.status_code == 403 and r1.json()["error"]["code"] == "ADMIN_PASSWORD_RESET"
    r2 = client.post(f"/api/v1/admin/users/{me.id}/reset-password", json={"new_password": NEW_PASSWORD},
                     headers=auth(my_token))
    assert r2.status_code == 422 and r2.json()["error"]["code"] == "OWN_ACCOUNT"
    missing = client.post(f"/api/v1/admin/users/{uuid.uuid4()}/reset-password", json={"new_password": NEW_PASSWORD},
                          headers=auth(my_token))
    assert missing.status_code == 404


def test_scanner_limited_to_assigned_session(client) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=1, sessions=[3])
    clock.freeze(ist(2026, 12, 14, 8, 5))  # session 1 is open
    _, scanner = make_staff("SCANNER", session_id=1)
    r = client.post("/api/v1/scanner/scan", json={"qr_payload": fam["qr_pass"]["qr_payload"]}, headers=auth(scanner))
    assert r.json()["data"]["status"] == "INVALID_SESSION"
    other = client.post("/api/v1/scanner/scan", json={"qr_payload": fam["qr_pass"]["qr_payload"], "session_id": 3},
                        headers=auth(scanner))
    assert other.status_code == 422  # a scanner cannot pick another session


# ============================================================ Excel report download
def export_and_download(client, token: str, **body):  # type: ignore[no-untyped-def]
    job = client.post("/api/v1/reports/exports", json=body or {"report_type": "FINAL"}, headers=auth(token))
    assert job.status_code == 202, job.text
    job_id = job.json()["data"]["id"]
    status = client.get(f"/api/v1/reports/exports/{job_id}", headers=auth(token)).json()["data"]
    assert status["status"] == "COMPLETED", status
    return status, client.get(f"/api/v1/reports/exports/{job_id}/download", headers=auth(token))


def test_admin_downloads_valid_workbook_matching_database(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=3, sessions=[1, 4])
    b = register_ok(client, members=2, sessions=[1])
    client.post(f"/api/v1/bookings/{b['booking_number']}/cancel", json={"reason": "Family request"},
                headers=auth(admin_token))
    status, dl = export_and_download(client, admin_token)
    stamp = clock.now().astimezone(clock.event_tz()).strftime("%Y%m%d")
    assert status["file_name"] == f"Mahayagya_Registration_Report_{stamp}.xlsx"
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert f'filename="Mahayagya_Registration_Report_{stamp}.xlsx"' in dl.headers["content-disposition"]
    assert dl.headers["cache-control"] == "no-store"
    assert dl.content[:2] == b"PK"  # xlsx is a zip container
    wb = load_workbook(io.BytesIO(dl.content), read_only=True)
    assert wb.sheetnames == SHEETS
    rows = lambda name: [r for r in wb[name].iter_rows(min_row=2, values_only=True) if any(v is not None for v in r)]  # noqa: E731
    bookings = rows("Family Bookings")
    assert sorted(r[0] for r in bookings) == sorted([a["booking_number"], b["booking_number"]])  # no duplicates
    assert len(rows("Family Members")) == 5
    assert db.execute(text("SELECT count(*) FROM family_members")).scalar() == 5
    cancels = rows("Cancellations")
    assert len(cancels) == 1 and cancels[0][0] == b["booking_number"] and cancels[0][5] == 2
    attendance = rows("Session Attendance")
    assert len(attendance) == 3 + 3 + 2  # a: 3 members x 2 sessions, b: 2 members x 1 session
    assert len(rows("Kund Allocation")) == 2151 * 16
    dash = {r[0]: r[1] for r in rows("Dashboard") if isinstance(r[0], str)}
    assert dash["Confirmed family bookings"] == 1 and dash["Total family bookings"] == 2
    assert dash["Cancelled family reservations"] == 1 and dash["Cancelled attendee places"] == 2
    times = {r[3] for r in rows("Dashboard") if isinstance(r[0], int)}
    assert times == {"08:00-11:00", "13:00-16:00"}


def test_empty_report_has_all_sheets_and_no_fabricated_rows(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    _, dl = export_and_download(client, admin_token)
    wb = load_workbook(io.BytesIO(dl.content), read_only=True)
    assert wb.sheetnames == SHEETS
    for name in ("Family Bookings", "Family Members", "Session Attendance", "Cancellations"):
        data = [r for r in wb[name].iter_rows(min_row=2, values_only=True) if any(v is not None for v in r)]
        assert data == [], name
    dash = {r[0]: r[1] for r in wb["Dashboard"].iter_rows(min_row=2, values_only=True) if r and isinstance(r[0], str)}
    assert dash["Total family bookings"] == 0 and dash["Actual check-ins"] == 0


def test_daily_report_file_name(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    status, dl = export_and_download(client, admin_token, report_type="DAILY", report_date="2026-12-15")
    assert status["file_name"] == "Mahayagya_Daily_Report_20261215.xlsx"
    assert 'filename="Mahayagya_Daily_Report_20261215.xlsx"' in dl.headers["content-disposition"]


@pytest.mark.parametrize("role", ["SUPERVISOR", "SCANNER"])
def test_reports_are_admin_only(client, db: Session, admin_token: str, role: str) -> None:  # type: ignore[no-untyped-def]
    """Every /reports endpoint returns 403 for SUPERVISOR and SCANNER, 401 without a token."""
    _, other = make_staff(role, session_id=1 if role == "SCANNER" else None)
    job = client.post("/api/v1/reports/exports", json={"report_type": "FINAL"}, headers=auth(admin_token)).json()["data"]
    daily = client.post("/api/v1/reports/exports", json={"report_type": "DAILY", "report_date": "2026-12-14"},
                        headers=auth(admin_token)).json()["data"]
    calls = [
        ("post", "/api/v1/reports/exports", {"report_type": "FINAL"}),
        ("post", "/api/v1/reports/exports", {"report_type": "DAILY", "report_date": "2026-12-14"}),
        ("get", f"/api/v1/reports/exports/{job['id']}", None),
        ("get", f"/api/v1/reports/exports/{job['id']}/download", None),
        ("get", f"/api/v1/reports/exports/{daily['id']}/download", None),
        ("get", "/api/v1/reports/summary", None),
    ]
    jobs_before = db.execute(text("SELECT count(*) FROM report_jobs")).scalar()
    for method, path, body in calls:
        kwargs = {"json": body} if body else {}
        r = getattr(client, method)(path, headers=auth(other), **kwargs)
        assert r.status_code == 403, (role, path)
        assert r.json()["error"]["code"] == "FORBIDDEN"
        assert getattr(client, method)(path, **kwargs).status_code == 401, path
    # the forbidden attempts created no report jobs; the admin can still read the job
    assert db.execute(text("SELECT count(*) FROM report_jobs")).scalar() == jobs_before
    assert client.get(f"/api/v1/reports/exports/{job['id']}", headers=auth(admin_token)).status_code == 200


def test_admin_downloads_full_and_daily_reports(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=2, sessions=[1])
    for body, name in [({"report_type": "FINAL"}, "Mahayagya_Registration_Report_"),
                       ({"report_type": "DAILY", "report_date": "2026-12-14"}, "Mahayagya_Daily_Report_20261214")]:
        status, dl = export_and_download(client, admin_token, **body)
        assert dl.status_code == 200 and status["file_name"].startswith(name)
        assert dl.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert load_workbook(io.BytesIO(dl.content), read_only=True).sheetnames == SHEETS
