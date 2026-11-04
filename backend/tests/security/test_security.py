"""Authentication, authorization, rate limiting, headers, PII and secret hygiene."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limits
from tests.conftest import ROOT, STAFF_PASSWORD, auth, make_staff, register, register_ok, registration_payload

STAFF_GET_ENDPOINTS = [
    "/api/v1/admin/dashboard",
    "/api/v1/admin/audit-logs",
    "/api/v1/admin/users",
    "/api/v1/admin/integrity",
    "/api/v1/bookings",
    "/api/v1/bookings/MY26-AAAAAAAA",
    "/api/v1/family-members?booking_number=MY26-AAAAAAAA",
    "/api/v1/sessions/1",
    "/api/v1/sessions/1/kunds",
    "/api/v1/kunds/1",
    "/api/v1/checkins",
    "/api/v1/reports/summary",
    "/api/v1/offline/snapshot/1",
    "/api/v1/scanner/me",
    "/api/v1/auth/me",
]


@pytest.mark.parametrize("path", STAFF_GET_ENDPOINTS)
def test_unauthenticated_requests_rejected(client, path: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(path)
    assert r.status_code == 401
    assert r.json()["success"] is False


@pytest.mark.parametrize("path", ["/api/v1/admin/audit-logs", "/api/v1/admin/users", "/api/v1/admin/integrity"])
def test_supervisor_cannot_use_admin_only_endpoints(client, supervisor_token: str, path: str) -> None:  # type: ignore[no-untyped-def]
    assert client.get(path, headers=auth(supervisor_token)).status_code == 403


def test_supervisor_cannot_create_users_or_change_sessions(client, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    body = {"full_name": "X Y", "email": "x@example.org", "password": STAFF_PASSWORD, "role": "ADMIN"}
    assert client.post("/api/v1/admin/users", json=body, headers=auth(supervisor_token)).status_code == 403


def test_login_flow_and_token_claims(client) -> None:  # type: ignore[no-untyped-def]
    make_staff("SUPERVISOR", email="sup@example.org")
    r = client.post("/api/v1/auth/login", json={"email": "SUP@example.org", "password": STAFF_PASSWORD})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["role"] == "SUPERVISOR" and claims["aud"] == "mahayagya-staff"
    assert claims["exp"] - claims["iat"] == 30 * 60
    assert "email" not in claims and "password" not in json.dumps(claims)
    me = client.get("/api/v1/auth/me", headers=auth(token)).json()["data"]
    assert me["email"] == "sup@example.org" and "password_hash" not in me


def test_wrong_password_and_unknown_user_look_identical(client) -> None:  # type: ignore[no-untyped-def]
    make_staff("ADMIN", email="adm@example.org")
    a = client.post("/api/v1/auth/login", json={"email": "adm@example.org", "password": "Wrong-Passw0rd1"})
    b = client.post("/api/v1/auth/login", json={"email": "nobody@example.org", "password": "Wrong-Passw0rd1"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"] == b.json()["error"]


def test_account_lockout_after_repeated_failures(client) -> None:  # type: ignore[no-untyped-def]
    make_staff("ADMIN", email="lock@example.org")
    for _ in range(get_settings().LOGIN_MAX_FAILED_ATTEMPTS):
        client.post("/api/v1/auth/login", json={"email": "lock@example.org", "password": "Wrong-Passw0rd1"})
    r = client.post("/api/v1/auth/login", json={"email": "lock@example.org", "password": STAFF_PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_tampered_expired_and_alg_none_tokens_rejected(client) -> None:  # type: ignore[no-untyped-def]
    user, token = make_staff("ADMIN")
    head, body, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    claims["role"] = "ADMIN"
    claims["sub"] = str(uuid.uuid4())
    forged_body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    assert client.get("/api/v1/auth/me", headers=auth(f"{head}.{forged_body}.{sig}")).status_code == 401
    none_token = jwt.encode({**claims, "sub": str(user.id)}, key="", algorithm="none")
    assert client.get("/api/v1/auth/me", headers=auth(none_token)).status_code == 401
    other_key = jwt.encode({**claims, "sub": str(user.id)}, key="x" * 40, algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers=auth(other_key)).status_code == 401
    short, _ = security.create_access_token(subject=str(user.id), role="ADMIN", token_version=1, expires_minutes=1)
    clock.freeze(clock.now().replace(year=2027))
    assert client.get("/api/v1/auth/me", headers=auth(short)).status_code == 401


def test_role_in_token_must_match_database(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    user, _ = make_staff("SCANNER", session_id=1)
    elevated, _ = security.create_access_token(subject=str(user.id), role="ADMIN", token_version=1, expires_minutes=60)
    assert client.get("/api/v1/admin/dashboard", headers=auth(elevated)).status_code == 401


def test_deactivated_user_and_logout_invalidate_tokens(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    user, token = make_staff("SUPERVISOR")
    assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 200
    client.patch(f"/api/v1/admin/users/{user.id}", json={"is_active": False}, headers=auth(admin_token))
    assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401
    _, token2 = make_staff("SUPERVISOR")
    assert client.post("/api/v1/auth/logout", headers=auth(token2)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth(token2)).status_code == 401


def test_registration_rate_limited(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_REGISTRATION", "3/minute")
    reset_rate_limits()
    statuses = [register(client, members=1).status_code for _ in range(5)]
    assert statuses[:3] == [201, 201, 201] and statuses[3:] == [429, 429]
    r = register(client, members=1)
    assert r.headers.get("Retry-After") and r.json()["error"]["code"] == "RATE_LIMITED"


def test_pass_lookup_brute_force_limited(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_PASS_LOOKUP", "5/minute")
    reset_rate_limits()
    codes = [client.post("/api/v1/qr/pass", json={"token": secrets_like()}).status_code for _ in range(8)]
    assert codes[:5] == [404] * 5 and set(codes[5:]) == {429}


def secrets_like() -> str:
    import secrets

    return secrets.token_urlsafe(32)


def test_login_rate_limited(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_LOGIN", "3/minute")
    reset_rate_limits()
    codes = [
        client.post("/api/v1/auth/login", json={"email": f"u{i}@example.org", "password": "Xx-123456789"}).status_code
        for i in range(5)
    ]
    assert codes[:3] == [401] * 3 and codes[3:] == [429, 429]


def test_security_headers(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/sessions")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert "server" not in {k.lower() for k in r.headers}
    assert r.headers["x-request-id"]


def test_cors_allowlist(client) -> None:  # type: ignore[no-untyped-def]
    ok = client.options("/api/v1/registrations", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,idempotency-key"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/v1/registrations", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_production_config_refuses_insecure_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(APP_ENV="production", _env_file=None)  # type: ignore[call-arg]


def test_sql_injection_attempts_are_inert(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client)
    for payload in ("' OR 1=1 --", "x'; DROP TABLE bookings; --"):
        r = client.get("/api/v1/bookings", params={"booking_number": payload, "city": payload},
                       headers=auth(admin_token))
        # Either rejected by input validation (length) or executed as a bound parameter matching nothing.
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            assert r.json()["meta"]["total"] == 0
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == 1
    bad = registration_payload(name="Robert'); DROP TABLE bookings;--")
    assert register(client, payload=bad).status_code == 422


def test_no_pii_in_application_logs(client, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    data = register_ok(client, payload=registration_payload(mobile="9866666666", email="secret.person@example.com"))
    client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["token"]})
    logs = "\n".join(r.getMessage() + " " + json.dumps(r.__dict__, default=str) for r in caplog.records)
    for pii in ("9866666666", "secret.person@example.com", "Rahul Sharma", "Bharadwaj", data["qr_pass"]["token"]):
        assert pii not in logs, pii


def test_public_endpoints_expose_no_pii(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, payload=registration_payload(mobile="9877777777"))
    r = client.get("/api/v1/sessions")
    for leaked in ("9877777777", "Rahul", "Sharma", data["booking_number"], "MY26-"):
        assert leaked not in r.text


def test_no_secrets_committed() -> None:
    """Scan tracked source files for credential patterns and ensure .env is git-ignored."""
    gitignore = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    assert re.search(r"^\.env$", gitignore, re.M)
    patterns = [
        re.compile(r"eyJhbGciOi[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),  # embedded JWT (e.g. Supabase keys)
        re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
        re.compile(r"(?i)(service_role_key|secret_key|password)\s*=\s*['\"]?[A-Za-z0-9/+_\-]{24,}"),
        re.compile(r"postgres(ql)?(\+psycopg)?://[^:\s]+:[^@\s]{12,}@(?!localhost|db[:/]|127\.0\.0\.1)"),
    ]
    skip_dirs = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "var", "results"}
    offenders = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith((".py", ".md", ".yml", ".yaml", ".ini", ".txt", ".example", ".js", ".toml", ".sql")) or f in {
                "Dockerfile"}:
                path = os.path.join(base, f)
                content = open(path, encoding="utf-8", errors="ignore").read()
                for p in patterns:
                    if p.search(content):
                        offenders.append((os.path.relpath(path, ROOT), p.pattern[:30]))
    assert offenders == []
    if os.path.isdir(os.path.join(ROOT, ".git")):
        tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True).stdout
        assert tracked.strip() == ""


def test_docs_can_be_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "ENABLE_DOCS", False)
    from app.main import create_app

    with TestClient(create_app()) as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_database_outage_returns_retryable_503(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import OperationalError

    from app.main import create_app
    from app.services.registration_service import RegistrationService

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))

    monkeypatch.setattr(RegistrationService, "register", boom)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = register(c, members=1)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DATABASE_UNAVAILABLE" and r.headers["Retry-After"] == "5"
    assert "server closed" not in r.text  # no internal error details leaked


def test_root_health_probe_for_hosting_platforms(client) -> None:  # type: ignore[no-untyped-def]
    """Render/other platforms probe /health by default; it must answer 200 without touching the database."""
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert client.get("/api/v1/health").status_code == 200


def test_health_endpoints_answer_head_for_uptime_monitors(client) -> None:  # type: ignore[no-untyped-def]
    """Uptime monitors (e.g. UptimeRobot) use HEAD by default: it must be 200, not 405."""
    for path in ("/health", "/api/v1/health", "/api/v1/health/ready"):
        r = client.head(path)
        assert r.status_code == 200, path
        assert r.content == b""
