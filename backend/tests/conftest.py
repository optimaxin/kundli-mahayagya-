"""Shared fixtures. Tests run against a REAL PostgreSQL database (no mocks, no SQLite).

Default test DB: postgresql+psycopg://mahayagya:mahayagya@localhost:5432/mahayagya_test
(created automatically by docker-compose). Override with TEST_DATABASE_URL.
The schema is rebuilt with Alembic (downgrade base -> upgrade head) once per run
and seeded with the 16 sessions / 2,151 Kunds / 34,416 capacity rows.
"""

from __future__ import annotations

import itertools
import os
import tempfile
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

# --- environment MUST be configured before any app module is imported --------
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://mahayagya:mahayagya@localhost:5432/mahayagya_test"
)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("DB_POOL_SIZE", "20")
os.environ.setdefault("DB_MAX_OVERFLOW", "40")
os.environ.setdefault("REPORTS_DIR", os.path.join(tempfile.gettempdir(), "mahayagya-test-reports"))
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("ANALYTICS_CACHE_SECONDS", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core import clock, security  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import get_sessionmaker, reset_engine  # noqa: E402
from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.models import AdminUser  # noqa: E402
from app.services.audit_service import RequestContext  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.seed_service import seed_all  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAFF_PASSWORD = "Str0ng-Test-Passw0rd"

# Default "now" for tests: registration is open, event has not started.
BEFORE_EVENT = datetime(2026, 11, 10, 10, 0, tzinfo=IST)
# During session 1 (14 Dec 2026, 08:00-11:00 IST; check-in window 07:45-11:15).
DURING_SESSION_1 = datetime(2026, 12, 14, 8, 5, tzinfo=IST)
# Session 1 has ended (no-shows computable), session 2 (afternoon 13:00-16:00) has not.
AFTER_SESSION_1 = datetime(2026, 12, 14, 12, 0, tzinfo=IST)

TRANSACTIONAL_TABLES = [
    "attendance_checkins", "cancellation_events", "qr_passes", "booking_sessions", "family_members",
    "bookings", "idempotency_records", "audit_logs", "report_jobs", "admin_users",
    "offline_checkin_events", "offline_roster_entries", "offline_sync_receipts",
]  # fmt: skip


def ist(*args: int) -> datetime:
    return datetime(*args, tzinfo=IST)  # type: ignore[misc]


def _ensure_database(url: str) -> None:
    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": u.database}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{u.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    url = get_settings().DATABASE_URL
    _ensure_database(url)
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.attributes["database_url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with get_sessionmaker()() as db:
        report = seed_all(db)
        assert report.expected_ok, report
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def clean_state(database: None) -> Iterator[None]:
    clock.freeze(BEFORE_EVENT)
    reset_rate_limits()
    yield
    with get_sessionmaker()() as db:
        db.execute(text(f"TRUNCATE {', '.join(TRANSACTIONAL_TABLES)} RESTART IDENTITY CASCADE"))
        db.execute(text("SELECT set_config('mahayagya.capacity_admin', 'on', true)"))
        db.execute(
            text(
                "UPDATE kund_session_capacity SET reserved_count = 0, capacity = 8 "
                "WHERE reserved_count <> 0 OR capacity <> 8"
            )
        )
        db.execute(text("UPDATE kunds SET is_active = true WHERE NOT is_active"))
        db.execute(
            text("UPDATE event_sessions SET status = 'SCHEDULED', is_active = true WHERE status <> 'SCHEDULED' OR NOT is_active")
        )
        db.commit()
    clock.freeze(None)


@pytest.fixture
def db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------- factories
_mobiles = itertools.count(9000000001)


def unique_mobile() -> str:
    return str(next(_mobiles))


_NAMES = ["Rahul", "Priya", "Aarav", "Ananya", "Vivaan", "Diya", "Arjun", "Saanvi", "Kabir"]


def registration_payload(members: int = 2, sessions: list[int] | None = None, mobile: str | None = None,
                         **coordinator: Any) -> dict[str, Any]:
    coord = {
        "name": "Rahul Sharma",
        "primary_mobile": mobile or unique_mobile(),
        "secondary_mobile": "",
        "email": "rahul@example.com",
        "address": "12 Civil Lines",
        "city": "Agra",
        "state": "Uttar Pradesh",
        "pincode": "282001",
        "gotra": "Bharadwaj",
        "sankalp_purpose": "Family wellbeing",
    }
    coord.update(coordinator)
    return {
        "coordinator": coord,
        "members": [
            {
                "full_name": f"{_NAMES[i % len(_NAMES)]} Sharma",
                "age": 20 + i * 7,
                "gender": "female" if i % 2 else "male",
                "relationship": "Self" if i == 0 else ["Spouse", "Child", "Parent", "Sibling"][i % 4],
            }
            for i in range(members)
        ],
        "selected_sessions": sessions if sessions is not None else [1],
    }


def register(client: TestClient, payload: dict[str, Any] | None = None, key: str | None = None, **kw: Any):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/registrations",
        json=payload or registration_payload(**kw),
        headers={"Idempotency-Key": key or uuid.uuid4().hex},
    )


def register_ok(client: TestClient, **kw: Any) -> dict[str, Any]:
    r = register(client, **kw)
    assert r.status_code == 201, r.text
    return r.json()["data"]


def make_staff(role: str = "ADMIN", session_id: int | None = None, email: str | None = None) -> tuple[AdminUser, str]:
    with get_sessionmaker()() as db:
        user = AuthService(db).create_user(
            full_name=f"Test {role.title()}",
            email=email or f"{role.lower()}-{uuid.uuid4().hex[:8]}@example.org",
            password=STAFF_PASSWORD,
            role=role,
            assigned_session_id=session_id,
            ctx=RequestContext(actor_role="SYSTEM"),
        )
    token, _ = security.create_access_token(
        subject=str(user.id), role=user.role, token_version=user.token_version, expires_minutes=60 * 24 * 90
    )
    return user, token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token() -> str:
    return make_staff("ADMIN")[1]


@pytest.fixture
def supervisor_token() -> str:
    return make_staff("SUPERVISOR")[1]


def capacity_admin(db: Session, sql: str, params: dict[str, Any] | None = None) -> None:
    """Controlled maintenance write to kund_session_capacity (tests only)."""
    db.execute(text("SELECT set_config('mahayagya.capacity_admin', 'on', true)"))
    db.execute(text(sql), params or {})
    db.commit()


def only_kunds_active(db: Session, kund_numbers: list[int]) -> None:
    db.execute(text("UPDATE kunds SET is_active = (kund_number = ANY(:k))"), {"k": kund_numbers})
    db.commit()


def reserved(db: Session, session_id: int, kund_number: int) -> int:
    return db.execute(
        text(
            "SELECT reserved_count FROM kund_session_capacity c JOIN kunds k ON k.id = c.kund_id "
            "WHERE c.session_id = :s AND k.kund_number = :k"
        ),
        {"s": session_id, "k": kund_number},
    ).scalar_one()


def assert_capacity_consistent(db: Session) -> None:
    """reserved_count == SUM(confirmed member_count) for every Kund-session; never > capacity."""
    bad = db.execute(
        text(
            """
            SELECT c.session_id, c.kund_id, c.reserved_count, COALESCE(a.n, 0) AS active
            FROM kund_session_capacity c
            LEFT JOIN (SELECT session_id, kund_id, SUM(member_count) n FROM booking_sessions
                       WHERE status = 'CONFIRMED' GROUP BY session_id, kund_id) a
              ON a.session_id = c.session_id AND a.kund_id = c.kund_id
            WHERE c.reserved_count <> COALESCE(a.n, 0) OR c.reserved_count > c.capacity
            """
        )
    ).all()
    assert bad == [], f"capacity inconsistencies: {bad[:5]}"
