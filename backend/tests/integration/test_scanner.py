"""Scanner workflow: assigned-session enforcement and per-member check-in."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from tests.conftest import DURING_SESSION_1, auth, ist, make_staff, register_ok


@pytest.fixture
def family(client) -> dict:  # type: ignore[no-untyped-def]
    return register_ok(client, members=3, sessions=[1, 3])


@pytest.fixture
def scanner1() -> str:
    clock.freeze(DURING_SESSION_1)
    return make_staff("SCANNER", session_id=1)[1]


def scan(client, token: str, qr: str) -> dict:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/scanner/scan", json={"qr_payload": qr}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def checkin(client, token: str, qr: str, member: int, event_id: str | None = None) -> dict:  # type: ignore[no-untyped-def]
    body = {"qr_payload": qr, "member_number": member}
    if event_id:
        body["event_id"] = event_id
    r = client.post("/api/v1/scanner/checkin", json=body, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_scan_returns_roster_and_kund_for_assigned_session(client, family, scanner1) -> None:  # type: ignore[no-untyped-def]
    data = scan(client, scanner1, family["qr_pass"]["qr_payload"])
    assert data["status"] == "VALID"
    assert data["session"]["session_id"] == 1
    assert data["booking_number"] == family["booking_number"]
    assert data["kund_number"] == family["reservations"][0]["kund_number"]
    assert [m["member_number"] for m in data["roster"]] == [1, 2, 3]
    assert not any(m["checked_in"] for m in data["roster"])


def test_each_member_checked_in_individually_and_once(client, db: Session, family, scanner1) -> None:  # type: ignore[no-untyped-def]
    qr = family["qr_pass"]["qr_payload"]
    first = checkin(client, scanner1, qr, 1)
    assert first["status"] == "CHECKIN_SUCCESS" and first["checked_in_count"] == 1
    roster = scan(client, scanner1, qr)["roster"]
    assert [m["checked_in"] for m in roster] == [True, False, False]  # NOT the whole family
    dup = checkin(client, scanner1, qr, 1)
    assert dup["status"] == "ALREADY_CHECKED_IN"
    assert checkin(client, scanner1, qr, 2)["status"] == "CHECKIN_SUCCESS"
    last = checkin(client, scanner1, qr, 3)
    assert last["status"] == "CHECKIN_SUCCESS" and last["checked_in_count"] == 3
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 3


def test_event_id_retry_is_idempotent(client, family, scanner1) -> None:  # type: ignore[no-untyped-def]
    eid = str(uuid.uuid4())
    a = checkin(client, scanner1, family["qr_pass"]["qr_payload"], 2, eid)
    b = checkin(client, scanner1, family["qr_pass"]["qr_payload"], 2, eid)
    assert a["status"] == b["status"] == "CHECKIN_SUCCESS"
    assert a["checked_in_at"] == b["checked_in_at"]


def test_same_member_can_check_in_to_another_reserved_session(client, family) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(DURING_SESSION_1)
    s1 = make_staff("SCANNER", session_id=1)[1]
    s2 = make_staff("SCANNER", session_id=3)[1]
    qr = family["qr_pass"]["qr_payload"]
    assert checkin(client, s1, qr, 1)["status"] == "CHECKIN_SUCCESS"
    clock.freeze(ist(2026, 12, 15, 8, 5))  # next day's morning session 3 (08:00-11:00)
    assert checkin(client, s2, qr, 1)["status"] == "CHECKIN_SUCCESS"
    assert checkin(client, s2, qr, 1)["status"] == "ALREADY_CHECKED_IN"


def test_invalid_member(client, family, scanner1) -> None:  # type: ignore[no-untyped-def]
    r = checkin(client, scanner1, family["qr_pass"]["qr_payload"], 4)  # family has 3
    assert r["status"] == "INVALID_MEMBER"
    bad = client.post(
        "/api/v1/scanner/checkin", json={"qr_payload": family["qr_pass"]["qr_payload"], "member_number": 9},
        headers=auth(scanner1),
    )
    assert bad.status_code == 422


def test_invalid_qr(client, scanner1) -> None:  # type: ignore[no-untyped-def]
    assert scan(client, scanner1, "MY26." + "z" * 43)["status"] == "INVALID_QR"
    assert checkin(client, scanner1, "MY26." + "z" * 43, 1)["status"] == "INVALID_QR"


def test_family_without_reservation_for_scanner_session(client, scanner1) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(ist(2026, 11, 10, 10, 0))
    other = register_ok(client, members=2, sessions=[5])
    clock.freeze(DURING_SESSION_1)
    assert scan(client, scanner1, other["qr_pass"]["qr_payload"])["status"] == "INVALID_SESSION"
    assert checkin(client, scanner1, other["qr_pass"]["qr_payload"], 1)["status"] == "INVALID_SESSION"


def test_session_id_from_client_is_never_trusted(client, family, scanner1) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/scanner/checkin",
        json={"qr_payload": family["qr_pass"]["qr_payload"], "member_number": 1, "session_id": 2},
        headers=auth(scanner1),
    )
    assert r.status_code == 422  # unknown field rejected; session comes from the account


def test_unassigned_scanner_rejected(client, family) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(DURING_SESSION_1)
    token = make_staff("SCANNER")[1]
    assert scan(client, token, family["qr_pass"]["qr_payload"])["status"] == "INVALID_SESSION"


def test_checkin_outside_session_window_rejected(client, family) -> None:  # type: ignore[no-untyped-def]
    token = make_staff("SCANNER", session_id=1)[1]
    clock.freeze(ist(2026, 12, 14, 11, 20))  # session 1 closed (ended 11:00 + 15 min)
    assert checkin(client, token, family["qr_pass"]["qr_payload"], 1)["status"] == "INVALID_SESSION"


def test_cancelled_booking_reported(client, family, admin_token: str, scanner1) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(ist(2026, 11, 20, 10, 0))
    r = client.post(f"/api/v1/bookings/{family['booking_number']}/cancel", json={"reason": "Family request"},
                    headers=auth(admin_token))
    assert r.status_code == 200, r.text
    clock.freeze(DURING_SESSION_1)
    assert scan(client, scanner1, family["qr_pass"]["qr_payload"])["status"] == "BOOKING_CANCELLED"
    assert checkin(client, scanner1, family["qr_pass"]["qr_payload"], 1)["status"] == "BOOKING_CANCELLED"


def test_cancelled_single_session_reported(client, family, admin_token: str, scanner1) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(ist(2026, 11, 20, 10, 0))
    r = client.post(f"/api/v1/bookings/{family['booking_number']}/cancel",
                    json={"reason": "Only morning", "session_ids": [1]}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    clock.freeze(DURING_SESSION_1)
    assert scan(client, scanner1, family["qr_pass"]["qr_payload"])["status"] == "BOOKING_CANCELLED"


def test_scanner_endpoints_require_gate_roles(client, family, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    body = {"qr_payload": family["qr_pass"]["qr_payload"]}
    assert client.post("/api/v1/scanner/scan", json=body).status_code == 401
    assert client.post("/api/v1/scanner/scan", json=body, headers=auth("not-a-jwt")).status_code == 401
    # Staff may scan, but must name the session explicitly.
    r = client.post("/api/v1/scanner/scan", json=body, headers=auth(admin_token))
    assert r.status_code == 422 and r.json()["error"]["code"] == "SESSION_REQUIRED"


def test_scanner_me(client, scanner1) -> None:  # type: ignore[no-untyped-def]
    data = client.get("/api/v1/scanner/me", headers=auth(scanner1)).json()["data"]
    assert data["session"]["session_id"] == 1 and data["checkin_window_open"] is True


def test_staff_can_list_checkins(client, family, scanner1, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    checkin(client, scanner1, family["qr_pass"]["qr_payload"], 2)
    r = client.get("/api/v1/checkins?session_id=1", headers=auth(supervisor_token))
    assert r.status_code == 200 and r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["member_number"] == 2
