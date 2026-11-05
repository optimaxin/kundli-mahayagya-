"""Registration API: validation, atomic multi-session allocation, idempotency."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from tests.conftest import (
    assert_capacity_consistent,
    capacity_admin,
    ist,
    register,
    register_ok,
    registration_payload,
    reserved,
)


def count(db: Session, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_one_member_family(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=1, sessions=[1])
    assert data["member_count"] == 1
    assert data["booking_number"].startswith("MY26-") and len(data["booking_number"]) == 13
    assert len(data["reservations"]) == 1
    assert data["reservations"][0]["kund_number"] == 1
    assert data["qr_pass"]["token"] and len(data["qr_pass"]["token"]) >= 43
    assert reserved(db, 1, 1) == 1
    assert_capacity_consistent(db)


def test_eight_member_family_occupies_one_full_kund(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=8, sessions=[1])
    assert data["member_count"] == 8 and len(data["members"]) == 8
    assert [m["member_number"] for m in data["members"]] == list(range(1, 9))
    kund = data["reservations"][0]["kund_number"]
    assert reserved(db, 1, kund) == 8


def test_multiple_sessions_one_kund_per_session(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[5, 1, 3])
    assert [r["session_id"] for r in data["reservations"]] == [1, 3, 5]
    for r in data["reservations"]:
        assert r["member_count"] == 3
        assert reserved(db, r["session_id"], r["kund_number"]) == 3
    assert count(db, "booking_sessions") == 3
    assert count(db, "qr_passes") == 1  # one pass for all sessions


def test_invalid_session_rejected(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    r = register(client, members=2, sessions=[1, 99])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_SESSION"
    assert r.json()["error"]["details"] == {"invalid_sessions": [99]}
    assert count(db, "bookings") == 0


def test_family_cannot_exceed_8_members(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    r = register(client, members=9)
    assert r.status_code == 422
    assert "at most 8 members" in r.text
    assert count(db, "bookings") == 0


def test_family_needs_at_least_one_member(client) -> None:  # type: ignore[no-untyped-def]
    assert register(client, members=0).status_code == 422


def test_validation_messages(client) -> None:  # type: ignore[no-untyped-def]
    bad = registration_payload(primary_mobile="12345", pincode="0123", state="Atlantis")
    r = register(client, payload=bad)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"coordinator.primary_mobile", "coordinator.pincode", "coordinator.state"} <= fields
    # submitted values are never echoed back
    assert "12345" not in r.text


def test_duplicate_member_names_and_sessions_rejected(client) -> None:  # type: ignore[no-untyped-def]
    p = registration_payload(members=2)
    p["members"] = [{"full_name": "Ram Kumar", "age": 40, "gender": "male"},
                    {"full_name": "ram  kumar", "age": 12, "gender": "male"}]
    assert register(client, payload=p).status_code == 422
    assert register(client, payload=registration_payload(sessions=[1, 1])).status_code == 422


def test_unknown_fields_rejected(client) -> None:  # type: ignore[no-untyped-def]
    p = registration_payload()
    p["kund_number"] = 5
    assert register(client, payload=p).status_code == 422


def test_mobile_normalisation(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(primary_mobile="+91 98765-43210"))
    assert db.execute(text("SELECT primary_mobile FROM bookings")).scalar_one() == "9876543210"


def test_idempotency_key_required(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/registrations", json=registration_payload())
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_duplicate_request_does_not_create_duplicate_booking(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    payload = registration_payload(members=4, sessions=[1, 3])
    key = str(uuid.uuid4())
    first = register(client, payload=payload, key=key)
    second = register(client, payload=payload, key=key)
    assert first.status_code == 201 and second.status_code == 201
    assert second.headers.get("Idempotent-Replayed") == "true"
    a, b = first.json()["data"], second.json()["data"]
    assert a["booking_number"] == b["booking_number"]
    assert a["qr_pass"]["token"] == b["qr_pass"]["token"]
    assert a["reservations"] == b["reservations"]
    assert count(db, "bookings") == 1
    assert count(db, "booking_sessions") == 2
    assert reserved(db, 1, a["reservations"][0]["kund_number"]) == 4
    # the raw token is NOT stored in plain text in the idempotency record
    payload_txt = db.execute(text("SELECT response_payload::text FROM idempotency_records")).scalar_one()
    assert a["qr_pass"]["token"] not in payload_txt


def test_idempotency_key_reuse_with_different_body_rejected(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    key = str(uuid.uuid4())
    assert register(client, payload=registration_payload(members=2), key=key).status_code == 201
    r = register(client, payload=registration_payload(members=3), key=key)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert count(db, "bookings") == 1


def test_same_mobile_cannot_book_same_session_twice(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(mobile="9811111111", sessions=[1, 3]))
    r = register(client, payload=registration_payload(mobile="9811111111", sessions=[3, 5]))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_BOOKING"
    assert r.json()["error"]["details"] == {"sessions": [3]}
    # a different session on a different day is fine
    register_ok(client, payload=registration_payload(mobile="9811111111", sessions=[5]))


# ------------------------------------------------------------ several days (both-session rules: test_both_sessions.py)
def test_one_session_each_day_in_either_slot_is_allowed(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1, 4, 5, 8])  # mixed mornings/afternoons, 4 different days
    assert [r["session_id"] for r in data["reservations"]] == [1, 4, 5, 8]


def test_failed_multi_session_allocation_rolls_back_completely(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    # Session 3 is completely full; sessions 1 and 5 have room.
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = capacity WHERE session_id = 3")
    key = str(uuid.uuid4())
    r = register(client, payload=registration_payload(members=2, sessions=[1, 3, 5]), key=key)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "CAPACITY_UNAVAILABLE"
    assert err["details"]["unavailable_sessions"] == [3]
    by_session = {a["session_id"]: a for a in err["details"]["availability"]}
    assert by_session[3]["fits_this_family"] is False and by_session[1]["fits_this_family"] is True
    # Nothing persisted: no booking, members, reservations, QR, idempotency record; sessions 1 and 5 untouched.
    for table in ("bookings", "family_members", "booking_sessions", "qr_passes", "idempotency_records"):
        assert count(db, table) == 0, table
    assert db.execute(text("SELECT sum(reserved_count) FROM kund_session_capacity WHERE session_id IN (1, 5)")).scalar() == 0
    # Retrying with the same key after capacity frees up works (failed attempts are not cached).
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 0 WHERE session_id = 3")
    assert register(client, payload=registration_payload(members=2, sessions=[1, 3, 5]), key=key).status_code == 201


def test_closed_or_inactive_session_not_bookable(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    db.execute(text("UPDATE event_sessions SET status = 'CLOSED' WHERE id = 4"))
    db.commit()
    r = register(client, sessions=[4])
    assert r.status_code == 422 and r.json()["error"]["code"] == "SESSION_NOT_BOOKABLE"


def test_booking_cutoff_enforced(client) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(ist(2026, 12, 14, 7, 30))  # 30 min before session 1 (cut-off is 60 min)
    r = register(client, sessions=[1])
    assert r.status_code == 422 and r.json()["error"]["code"] == "SESSION_NOT_BOOKABLE"
    assert register(client, sessions=[2]).status_code == 201  # afternoon session still open


def test_response_and_qr_contain_no_internal_ids_or_pii(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, payload=registration_payload(mobile="9822222222"))
    qr = data["qr_pass"]["qr_payload"]
    assert qr.startswith("MY26.") and qr.endswith(data["qr_pass"]["token"])
    for pii in ("9822222222", "Rahul", "Sharma", "Agra", "Bharadwaj", data["booking_number"]):
        assert pii not in qr
    assert data["primary_mobile_masked"] == "98******22"
    assert "id" not in data and "booking_id" not in str(data)
