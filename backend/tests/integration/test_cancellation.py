"""Cancellation: exactly-once capacity release, idempotency, history preservation."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from tests.conftest import (
    DURING_SESSION_1,
    assert_capacity_consistent,
    auth,
    make_staff,
    register_ok,
    reserved,
)


def cancel(client, token: str, bn: str, **body):  # type: ignore[no-untyped-def]
    body.setdefault("reason", "Family requested cancellation")
    return client.post(f"/api/v1/bookings/{bn}/cancel", json=body, headers=auth(token))


def test_cancel_releases_capacity_exactly_once(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=5, sessions=[1, 3])
    k1 = data["reservations"][0]["kund_number"]
    assert reserved(db, 1, k1) == 5
    r = cancel(client, admin_token, data["booking_number"])
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["booking_status"] == "CANCELLED" and body["released_capacity"] == 10
    assert body["already_cancelled"] is False
    assert reserved(db, 1, k1) == 0
    again = cancel(client, admin_token, data["booking_number"]).json()["data"]
    assert again["already_cancelled"] is True and again["released_capacity"] == 0
    assert db.execute(text("SELECT coalesce(sum(reserved_count),0) FROM kund_session_capacity")).scalar() == 0
    assert_capacity_consistent(db)


def test_cancellation_history_is_preserved(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1, 3])
    cancel(client, admin_token, data["booking_number"], reason="Travel plans changed")
    cancel(client, admin_token, data["booking_number"], reason="Duplicate click")
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == 1
    assert db.execute(text("SELECT count(*) FROM family_members")).scalar() == 2
    assert db.execute(text("SELECT count(*) FROM booking_sessions WHERE status = 'CANCELLED'")).scalar() == 2
    events = db.execute(text("SELECT reason, released_member_count, actor_id FROM cancellation_events")).all()
    assert len(events) == 2 and all(e[0] == "Travel plans changed" and e[1] == 2 and e[2] for e in events)
    audit = db.execute(text("SELECT action, previous_values, new_values FROM audit_logs WHERE action LIKE '%CANCEL%'")).all()
    assert len(audit) == 1 and audit[0][1]["status"] == "CONFIRMED" and audit[0][2]["status"] == "CANCELLED"
    assert db.execute(text("SELECT count(*) FROM qr_passes WHERE is_active")).scalar() == 0


def test_partial_cancellation_keeps_booking_and_pass(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[1, 3, 5])
    body = cancel(client, admin_token, data["booking_number"], session_ids=[3]).json()["data"]
    assert body["booking_status"] == "CONFIRMED"
    assert body["remaining_confirmed_sessions"] == 2 and body["released_capacity"] == 3
    assert client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["token"]}).status_code == 200
    bad = cancel(client, admin_token, data["booking_number"], session_ids=[9])
    assert bad.status_code == 422


def test_freed_capacity_is_reused_by_best_fit(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=6)  # K1 6/8
    register_ok(client, members=2)  # K1 8/8
    cancel(client, admin_token, a["booking_number"])  # K1 2/8
    c = register_ok(client, members=5)
    assert c["reservations"][0]["kund_number"] == 1
    assert reserved(db, 1, 1) == 7


def test_cannot_cancel_reservation_with_checkins(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1])
    clock.freeze(DURING_SESSION_1)
    scanner = make_staff("SCANNER", session_id=1)[1]
    client.post("/api/v1/scanner/checkin", json={"qr_payload": data["qr_pass"]["qr_payload"], "member_number": 1},
                headers=auth(scanner))
    r = cancel(client, admin_token, data["booking_number"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "RESERVATION_HAS_CHECKINS"


def test_cancel_permissions(client, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client)
    scanner = make_staff("SCANNER", session_id=1)[1]
    assert cancel(client, scanner, data["booking_number"]).status_code == 403
    assert client.post(f"/api/v1/bookings/{data['booking_number']}/cancel", json={"reason": "x y z"}).status_code == 401
    assert cancel(client, supervisor_token, data["booking_number"]).status_code == 200


def test_cancel_unknown_booking(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    assert cancel(client, admin_token, "MY26-ZZZZZZZZ").status_code == 404
    assert cancel(client, admin_token, "not-a-number").status_code == 422
