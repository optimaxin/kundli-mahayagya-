"""14 December 2026 MORNING (session 1, 08:00-11:00) is closed to NEW bookings; nothing else changes.

The lock is the existing session-level closure (event_sessions.status = 'CLOSED'), applied by migration 0004
(and by seeding for a brand-new database). The shared test baseline re-opens session 1 so the rest of the suite
can keep booking it; the ``locked`` fixture below applies the real migration SQL to lock it again.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from app.core.database import get_sessionmaker, run_transaction
from app.core.errors import ValidationFailed
from app.services.allocation_service import AllocationService
from tests.conftest import (
    DURING_SESSION_1,
    FRESH_STATUS_OF_LOCKED_SESSION,
    ROOT,
    assert_capacity_consistent,
    auth,
    make_staff,
    register,
    register_ok,
    registration_payload,
    unique_mobile,
)

LOCKED = 1  # 14 Dec 2026 MORNING
AFTERNOON = 2  # 14 Dec 2026 AFTERNOON


def _migration():  # type: ignore[no-untyped-def]
    path = Path(ROOT) / "alembic" / "versions" / "0004_lock_14_dec_morning_session.py"
    spec = importlib.util.spec_from_file_location("migration_0004", os.fspath(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def apply_lock(db: Session) -> None:
    """Run exactly what production runs (migration 0004's SQL)."""
    db.execute(text(_migration().LOCK_SQL))
    db.commit()


def status_of(db: Session, session_id: int) -> str:
    return db.execute(text("SELECT status FROM event_sessions WHERE id = :i"), {"i": session_id}).scalar_one()


def counts(db: Session) -> dict[str, int]:
    tables = ["bookings", "family_members", "booking_sessions", "qr_passes", "idempotency_records"]
    out = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in tables}
    out["reserved"] = db.execute(text("SELECT coalesce(sum(reserved_count), 0) FROM kund_session_capacity")).scalar_one()
    return out


def mobile_of(db: Session, booking: dict) -> str:
    return db.execute(
        text("SELECT primary_mobile FROM bookings WHERE booking_number = :b"), {"b": booking["booking_number"]}
    ).scalar_one()


@pytest.fixture
def locked(db: Session) -> None:
    apply_lock(db)
    assert status_of(db, LOCKED) == "CLOSED"


def public_sessions(client, family_size: int = 1) -> dict[int, dict]:  # type: ignore[no-untyped-def]
    r = client.get(f"/api/v1/sessions?family_size={family_size}")
    assert r.status_code == 200
    return {s["id"]: s for s in r.json()["data"]}


# ------------------------------------------------------------ 1. the locked session is refused
def test_locked_session_booking_is_rejected_with_a_structured_error(client, db: Session, locked) -> None:  # type: ignore[no-untyped-def]
    r = register(client, sessions=[LOCKED])
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "SESSION_NOT_BOOKABLE"
    assert err["details"]["sessions"] == [
        {"session_id": LOCKED, "reason": "Session is full and closed to new bookings", "reason_code": "SESSION_FULL"}
    ]
    assert counts(db)["bookings"] == 0


@pytest.mark.parametrize("members", [1, 2, 8])
def test_rejected_for_every_family_size(client, db: Session, locked, members: int) -> None:  # type: ignore[no-untyped-def]
    assert register(client, members=members, sessions=[LOCKED]).status_code == 422


def test_direct_api_call_without_the_website_is_refused(client, locked) -> None:  # type: ignore[no-untyped-def]
    # A raw request, exactly what a script would send (no website, no frontend checks).
    r = client.post(
        "/api/v1/registrations", json=registration_payload(sessions=[LOCKED]), headers={"Idempotency-Key": "script-1"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "SESSION_NOT_BOOKABLE"


# ------------------------------------------------------------ 2/3. nothing else is affected
def test_afternoon_of_the_same_day_stays_bookable(client, locked) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[AFTERNOON])
    assert [r["session_id"] for r in data["reservations"]] == [AFTERNOON]


def test_every_other_session_is_unaffected(client, db: Session, locked) -> None:  # type: ignore[no-untyped-def]
    rows = db.execute(text("SELECT id, status, is_active FROM event_sessions ORDER BY id")).all()
    assert [r.id for r in rows if r.status != "SCHEDULED"] == [LOCKED]
    assert all(r.is_active for r in rows)
    # book every remaining session, each as its own family
    for sid in range(2, 17):
        assert register(client, sessions=[sid]).status_code == 201, sid


def test_other_dates_book_normally_in_one_multi_session_booking(client, locked) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[2, 3, 4, 15, 16])
    assert [r["session_id"] for r in data["reservations"]] == [2, 3, 4, 15, 16]


# ------------------------------------------------------------ 4/5. atomic failure, no capacity used
def test_multi_session_booking_containing_the_locked_session_fails_atomically(client, db: Session, locked) -> None:  # type: ignore[no-untyped-def]
    before = counts(db)
    mobile = unique_mobile()
    r = register(client, payload=registration_payload(members=4, sessions=[AFTERNOON, LOCKED, 3], mobile=mobile))
    assert r.status_code == 422 and r.json()["error"]["code"] == "SESSION_NOT_BOOKABLE"
    assert counts(db) == before  # no booking, members, reservations, QR pass, idempotency record, capacity
    assert db.execute(text("SELECT count(*) FROM booking_sessions")).scalar() == 0
    assert_capacity_consistent(db)
    # the same family can still book the open sessions afterwards (no half-reserved state, mobile not burnt)
    ok = register(client, payload=registration_payload(members=4, sessions=[AFTERNOON, 3], mobile=mobile))
    assert ok.status_code == 201


def test_rejected_booking_consumes_no_kund_capacity(client, db: Session, locked) -> None:  # type: ignore[no-untyped-def]
    for _ in range(3):
        assert register(client, members=8, sessions=[LOCKED, AFTERNOON]).status_code == 422
    assert db.execute(text("SELECT coalesce(sum(reserved_count), 0) FROM kund_session_capacity")).scalar() == 0
    # Kund 1 of the locked session is still completely free
    free = db.execute(
        text("SELECT reserved_count FROM kund_session_capacity WHERE session_id = :s AND kund_id = 1"), {"s": LOCKED}
    ).scalar()
    assert free == 0


def test_allocation_service_refuses_the_locked_session_under_its_own_lock(db: Session, locked) -> None:  # type: ignore[no-untyped-def]
    # Defence in depth: even if the up-front check were skipped (e.g. the session was locked after validation),
    # the allocation step re-checks under the row lock and reserves nothing for ANY session in the request.
    def work(tx: Session) -> None:
        AllocationService(tx).allocate_family(booking_id=0, family_size=2, session_ids=[AFTERNOON, LOCKED])

    with pytest.raises(ValidationFailed) as exc:
        run_transaction(db, work, label="test_lock")
    assert exc.value.code == "SESSION_NOT_BOOKABLE"
    assert exc.value.details["sessions"][0]["reason_code"] == "SESSION_FULL"
    assert db.execute(text("SELECT count(*) FROM booking_sessions")).scalar() == 0
    assert db.execute(text("SELECT coalesce(sum(reserved_count), 0) FROM kund_session_capacity")).scalar() == 0


def test_idempotency_key_is_not_burnt_by_a_rejected_booking(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    apply_lock(db)
    payload = registration_payload(sessions=[LOCKED])
    assert register(client, payload=payload, key="lock-key-1").status_code == 422
    assert db.execute(text("SELECT count(*) FROM idempotency_records")).scalar() == 0
    # an admin deliberately re-opens it (existing admin feature): the same request now works
    r = client.patch(f"/api/v1/sessions/{LOCKED}", json={"status": "SCHEDULED"}, headers=auth(admin_token))
    assert r.status_code == 200
    assert register(client, payload=payload, key="lock-key-1").status_code == 201


# ------------------------------------------------------------ 6/7. existing records keep working
def test_existing_bookings_passes_and_checkin_survive_the_lock(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    # Families booked session 1 while it was open (before the lock).
    fam = register_ok(client, members=3, sessions=[LOCKED, 3])
    other = register_ok(client, members=2, sessions=[LOCKED])
    clock.freeze(DURING_SESSION_1)
    scanner = make_staff("SCANNER", session_id=LOCKED)[1]
    admin = make_staff("ADMIN")[1]
    qr_before = db.execute(text("SELECT token_hash, is_active, expires_at FROM qr_passes ORDER BY id")).all()
    kunds_before = [(r["session_id"], r["kund_number"]) for r in fam["reservations"]]
    qr = fam["qr_pass"]["qr_payload"]
    # a member is checked in BEFORE the lock, to prove existing check-in records stay untouched
    first = client.post("/api/v1/scanner/checkin", json={"qr_payload": qr, "member_number": 1}, headers=auth(scanner))
    assert first.json()["data"]["status"] == "CHECKIN_SUCCESS"
    checkin_sql = "SELECT id, booking_session_id, member_id, checked_in_at FROM attendance_checkins ORDER BY id"
    checkins_before = db.execute(text(checkin_sql)).all()
    before = counts(db)

    apply_lock(db)  # <-- the lock

    # nothing was modified or deleted
    assert counts(db) == before
    assert db.execute(text("SELECT token_hash, is_active, expires_at FROM qr_passes ORDER BY id")).all() == qr_before
    assert db.execute(text(checkin_sql)).all() == checkins_before
    assert db.execute(text("SELECT count(*) FROM bookings WHERE status = 'CONFIRMED'")).scalar() == 2
    assert db.execute(text("SELECT count(*) FROM booking_sessions WHERE status = 'CONFIRMED'")).scalar() == 3
    assert_capacity_consistent(db)

    # the pass and booking are still fully accessible
    p = client.post("/api/v1/qr/pass", json={"token": fam["qr_pass"]["token"]})
    assert p.status_code == 200
    assert sorted((r["session_id"], r["kund_number"]) for r in p.json()["data"]["reservations"]) == sorted(kunds_before)
    d = client.get(f"/api/v1/bookings/{fam['booking_number']}", headers=auth(admin))
    assert d.status_code == 200 and d.json()["data"]["status"] == "CONFIRMED"
    assert len(d.json()["data"]["reservations"]) == 2
    s = client.post(
        "/api/v1/qr/status",
        json={"booking_number": other["booking_number"], "primary_mobile": mobile_of(db, other)},
    )
    assert s.status_code == 200

    # QR scan and per-member check-in at the locked session still work under the normal rules
    scan = client.post("/api/v1/scanner/scan", json={"qr_payload": qr}, headers=auth(scanner))
    assert scan.status_code == 200 and scan.json()["data"]["status"] == "VALID"
    assert [m["checked_in"] for m in scan.json()["data"]["roster"]] == [True, False, False]
    for member, expected in ((2, "CHECKIN_SUCCESS"), (3, "CHECKIN_SUCCESS"), (2, "ALREADY_CHECKED_IN")):
        r = client.post("/api/v1/scanner/checkin", json={"qr_payload": qr, "member_number": member}, headers=auth(scanner))
        assert r.status_code == 200 and r.json()["data"]["status"] == expected
    r = client.post(
        "/api/v1/scanner/checkin",
        json={"qr_payload": other["qr_pass"]["qr_payload"], "member_number": 1},
        headers=auth(scanner),
    )
    assert r.json()["data"]["status"] == "CHECKIN_SUCCESS"
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 4


def test_existing_booking_can_still_be_cancelled_and_the_session_stays_closed(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=2, sessions=[LOCKED])
    apply_lock(db)
    r = client.post(
        f"/api/v1/bookings/{fam['booking_number']}/cancel",
        json={"reason": "Family requested cancellation"},
        headers=auth(admin_token),
    )
    assert r.status_code == 200
    assert status_of(db, LOCKED) == "CLOSED"  # freed places do not re-open public booking
    assert register(client, sessions=[LOCKED]).status_code == 422


def test_admin_views_still_include_the_locked_session(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=2, sessions=[LOCKED])
    apply_lock(db)
    cap = client.get("/api/v1/sessions/capacity", headers=auth(admin_token)).json()["data"]
    s1 = next(s for s in cap if s["id"] == LOCKED)
    assert s1["reserved"] == 2 and s1["booking_open"] is False and s1["status"] == "CLOSED"
    detail = client.get(f"/api/v1/sessions/{LOCKED}", headers=auth(admin_token))
    assert detail.status_code == 200 and detail.json()["data"]["confirmed_families"] == 1


# ------------------------------------------------------------ 8. the public API
@pytest.mark.parametrize("family_size", range(1, 9))
def test_public_api_never_reports_the_locked_session_as_bookable(client, locked, family_size: int) -> None:  # type: ignore[no-untyped-def]
    s = public_sessions(client, family_size)
    assert len(s) == 16
    row = s[LOCKED]
    assert row["booking_open"] is False
    assert row["availability"] == "CLOSED"
    assert row["closed_reason"] == "SESSION_FULL"
    assert row["fits_family"] is False
    assert row["status"] == "CLOSED"
    # no capacity numbers leak
    assert not {"remaining", "reserved", "total_capacity", "largest_family_bookable", "kunds_empty"} & set(row)
    # every other session, including the same-day afternoon, is open and shows no closed reason
    for sid, other in s.items():
        if sid != LOCKED:
            assert other["booking_open"] is True and other["availability"] == "AVAILABLE", sid
            assert other["closed_reason"] is None, sid


def test_public_api_is_unchanged_for_other_closed_reasons(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    # booking cut-off keeps the generic "closed" meaning: it must not be shown as the locked "Session Full"
    clock.freeze(DURING_SESSION_1)
    rows = public_sessions(client)
    assert rows[LOCKED]["closed_reason"] == "CUTOFF" and rows[LOCKED]["availability"] == "CLOSED"
    assert rows[AFTERNOON]["closed_reason"] is None
    clock.freeze(None)
    db.execute(text("UPDATE event_sessions SET is_active = false WHERE id = 5"))
    db.commit()
    assert public_sessions(client)[5]["closed_reason"] == "NOT_OPEN"


# ------------------------------------------------------------ the migration / seed
def test_migration_only_touches_the_one_session_and_is_idempotent(db: Session) -> None:
    assert status_of(db, LOCKED) == "SCHEDULED"
    others = "SELECT id, status, is_active FROM event_sessions WHERE id <> :i ORDER BY id"
    others_before = db.execute(text(others), {"i": LOCKED}).all()
    apply_lock(db)
    apply_lock(db)  # idempotent
    assert status_of(db, LOCKED) == "CLOSED"
    assert db.execute(text(others), {"i": LOCKED}).all() == others_before
    audit = db.execute(text("SELECT actor_role, entity_id FROM audit_logs WHERE action = 'SESSION_UPDATED'")).all()
    assert len(audit) == 1  # written once, only when the session was actually closed
    assert audit[0].actor_role == "SYSTEM" and audit[0].entity_id == str(LOCKED)
    # it targets exactly 14 Dec 2026 MORNING 08:00-11:00
    row = db.execute(
        text("SELECT event_date::text, slot, start_time::text, end_time::text FROM event_sessions WHERE id = :i"),
        {"i": LOCKED},
    ).one()
    assert tuple(row) == ("2026-12-14", "MORNING", "08:00:00", "11:00:00")


def test_migration_never_overrides_a_status_an_admin_has_set(db: Session) -> None:
    db.execute(text("UPDATE event_sessions SET status = 'COMPLETED' WHERE id = :i"), {"i": LOCKED})
    db.commit()
    apply_lock(db)
    assert status_of(db, LOCKED) == "COMPLETED"
    assert db.execute(text("SELECT count(*) FROM audit_logs")).scalar() == 0


def test_a_freshly_seeded_database_creates_the_session_already_locked() -> None:
    # conftest records the status right after `alembic upgrade head` + seed_all, before re-opening it for the suite
    assert FRESH_STATUS_OF_LOCKED_SESSION["status"] == "CLOSED"


def test_reseeding_never_changes_existing_sessions(db: Session) -> None:
    from app.services.seed_service import seed_all

    assert status_of(db, LOCKED) == "SCHEDULED"
    with get_sessionmaker()() as other:
        seed_all(other)  # idempotent: must not re-lock a session an admin has re-opened
    assert status_of(db, LOCKED) == "SCHEDULED"


def test_lock_is_persistent_database_state_not_process_state(client, db: Session, locked) -> None:  # type: ignore[no-untyped-def]
    # A restart or redeploy builds a new engine and app; the lock lives in the database row and survives it.
    from app.core.database import reset_engine

    reset_engine()
    with get_sessionmaker()() as fresh:
        assert status_of(fresh, LOCKED) == "CLOSED"
    assert register(client, sessions=[LOCKED]).status_code == 422
