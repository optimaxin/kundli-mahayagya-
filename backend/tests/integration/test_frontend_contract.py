"""Behaviour the React frontend (frontend/src/lib/db.js) depends on."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from tests.conftest import (
    DURING_SESSION_1,
    auth,
    ist,
    make_staff,
    only_kunds_active,
    register,
    register_ok,
    registration_payload,
    reserved,
)


# ------------------------------------------------------------ registration
def test_frontend_style_registration_with_optional_fields_blank(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    p = registration_payload(members=3, sessions=[1, 3], address="", pincode="", gotra="", sankalp_purpose="",
                             email="", state="Other")
    p["members"][1]["mobile"] = "9812345678"
    p["members"][2]["relationship"] = "Friend"
    data = register_ok(client, payload=p)
    assert data["members"][0] == {"member_number": 1, "full_name": "Rahul Sharma", "age": 20, "gender": "male",
                                  "relationship": "Self"}
    row = db.execute(text("SELECT address, pincode, gotra, sankalp_purpose, state, email FROM bookings")).one()
    assert tuple(row) == (None, None, None, None, "Other", None)
    m = db.execute(text("SELECT age, gender, relationship, mobile FROM family_members ORDER BY member_number")).all()
    assert [tuple(x) for x in m] == [(20, "male", "Self", None), (27, "female", "Child", "9812345678"),
                                     (34, "male", "Friend", None)]


def test_member_fields_validated(client) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"age": 0}, {"age": 111}, {"gender": "x"}, {"relationship": "<b>"}, {"mobile": "12345"}):
        p = registration_payload(members=1)
        p["members"][0].update(bad)
        assert register(client, payload=p).status_code == 422, bad
    p = registration_payload(members=1)
    del p["members"][0]["age"]
    assert register(client, payload=p).status_code == 422


def test_sessions_endpoint_shape_for_frontend(client) -> None:  # type: ignore[no-untyped-def]
    s = client.get("/api/v1/sessions").json()["data"]
    assert [(x["slot"], x["start_time"], x["end_time"]) for x in s[:2]] == [
        ("MORNING", "08:00:00", "11:00:00"), ("AFTERNOON", "13:00:00", "16:00:00")]
    assert s[0]["kunds_blocked"] == 0 and s[0]["booking_open"] is True


# -------------------------------------------------------------- QR pass
def test_pass_details_for_ticket_page(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1, 3])
    p = client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["token"]}).json()["data"]
    assert p["qr_payload"] == data["qr_pass"]["qr_payload"]
    assert p["coordinator_name"] == "Rahul Sharma" and p["primary_mobile_masked"].startswith("90")
    assert [(r["session_id"], r["start_time"], r["checked_in_count"]) for r in p["reservations"]] == [
        (1, "08:00:00", 0), (3, "08:00:00", 0)]
    assert "age" not in p["members"][0]  # pass may be shared: names only


# ------------------------------------------------------- scanner (+manual)
def test_check_in_window_is_plus_minus_15_minutes(client) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=1, sessions=[1])
    token = make_staff("SCANNER", session_id=1)[1]
    body = {"qr_payload": fam["qr_pass"]["qr_payload"]}
    for at, expected, reason in [
        (ist(2026, 12, 14, 7, 44), "INVALID_SESSION", "SESSION_NOT_OPEN"),
        (ist(2026, 12, 14, 7, 45), "VALID", None),
        (ist(2026, 12, 14, 11, 15), "VALID", None),
        (ist(2026, 12, 14, 11, 16), "INVALID_SESSION", "SESSION_OVER"),
    ]:
        clock.freeze(at)
        r = client.post("/api/v1/scanner/scan", json=body, headers=auth(token)).json()["data"]
        assert (r["status"], r["reason"]) == (expected, reason), at


def test_manual_pass_id_entry_and_reasons(client) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=2, sessions=[1])
    other = register_ok(client, members=1, sessions=[3])
    clock.freeze(DURING_SESSION_1)
    token = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/scanner/scan", json={"booking_number": fam["booking_number"].lower()},
                    headers=auth(token)).json()["data"]
    assert r["status"] == "VALID" and r["coordinator_name"] == "Rahul Sharma" and len(r["roster"]) == 2
    c = client.post("/api/v1/scanner/checkin", json={"booking_number": fam["booking_number"], "member_number": 2},
                    headers=auth(token)).json()["data"]
    assert c["status"] == "CHECKIN_SUCCESS"
    n = client.post("/api/v1/scanner/scan", json={"booking_number": other["booking_number"]},
                    headers=auth(token)).json()["data"]
    assert (n["status"], n["reason"]) == ("INVALID_SESSION", "NO_RESERVATION")
    assert [b["session_id"] for b in n["booked_sessions"]] == [3]
    u = client.post("/api/v1/scanner/scan", json={"booking_number": "MY26-ZZZZZZZZ"}, headers=auth(token)).json()
    assert (u["data"]["status"], u["data"]["reason"]) == ("INVALID_QR", "UNKNOWN_PASS")
    both = client.post("/api/v1/scanner/scan", json={"booking_number": fam["booking_number"],
                                                     "qr_payload": fam["qr_pass"]["qr_payload"]}, headers=auth(token))
    assert both.status_code == 422


def test_revoked_pass_blocks_manual_entry_until_reissued(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=1, sessions=[1])
    client.post(f"/api/v1/qr/{fam['booking_number']}/revoke", json={"reason": "Lost"}, headers=auth(admin_token))
    clock.freeze(DURING_SESSION_1)
    token = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/scanner/scan", json={"booking_number": fam["booking_number"]}, headers=auth(token))
    assert r.json()["data"]["reason"] == "PASS_REVOKED"


def test_staff_scan_with_explicit_session_and_scanner_cannot_choose(client, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=1, sessions=[1])
    clock.freeze(DURING_SESSION_1)
    body = {"qr_payload": fam["qr_pass"]["qr_payload"], "member_number": 1, "session_id": 1}
    ok = client.post("/api/v1/scanner/checkin", json=body, headers=auth(supervisor_token)).json()["data"]
    assert ok["status"] == "CHECKIN_SUCCESS"
    scanner = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/scanner/checkin", json=body, headers=auth(scanner))
    assert r.status_code == 422 and r.json()["error"]["code"] == "SESSION_NOT_ALLOWED"
    recent = client.get("/api/v1/scanner/recent", headers=auth(supervisor_token)).json()["data"]
    assert len(recent) == 1 and recent[0]["booking_number"] == fam["booking_number"]
    assert client.get("/api/v1/scanner/recent", headers=auth(scanner)).json()["data"] == []


def test_manual_checkin_by_staff(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=3, sessions=[1])
    bn = fam["booking_number"]
    early = client.post(f"/api/v1/bookings/{bn}/checkin", json={"session_id": 1}, headers=auth(admin_token))
    assert early.status_code == 409 and early.json()["error"]["code"] == "SESSION_NOT_OPEN"
    clock.freeze(DURING_SESSION_1)
    one = client.post(f"/api/v1/bookings/{bn}/checkin", json={"session_id": 1, "member_numbers": [2]},
                      headers=auth(admin_token)).json()["data"]
    assert one["checked_in"] == [2] and one["checked_in_count"] == 1
    rest = client.post(f"/api/v1/bookings/{bn}/checkin", json={"session_id": 1}, headers=auth(admin_token)).json()
    assert rest["data"]["checked_in"] == [1, 3] and rest["data"]["already_checked_in"] == [2]
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 3
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'MANUAL_CHECKIN'")).scalar() == 2
    scanner = make_staff("SCANNER", session_id=1)[1]
    assert client.post(f"/api/v1/bookings/{bn}/checkin", json={"session_id": 1},
                       headers=auth(scanner)).status_code == 403


# ------------------------------------------------------------ kund map
def test_kund_map_and_per_session_block(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1, 2, 3])
    register_ok(client, members=5, sessions=[1])  # -> Kund 1
    m = client.get("/api/v1/sessions/1/kund-map", headers=auth(admin_token)).json()["data"]
    assert m["occ"] == {"1": 5} and m["blocked"] == [] and len(m["inactive"]) == 2148
    busy = client.post("/api/v1/sessions/1/kunds/1/block", json={"blocked": True}, headers=auth(admin_token))
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "KUND_NOT_EMPTY"
    assert client.post("/api/v1/sessions/1/kunds/2/block", json={"blocked": True},
                       headers=auth(admin_token)).json()["data"]["blocked"] is True
    fam = register_ok(client, members=4, sessions=[1, 3])  # session 1: K1 has 3 free -> K3 (K2 blocked)
    assert {r["session_id"]: r["kund_number"] for r in fam["reservations"]} == {1: 3, 3: 1}
    assert reserved(db, 1, 2) == 0
    s1 = next(s for s in client.get("/api/v1/sessions").json()["data"] if s["id"] == 1)
    assert s1["kunds_blocked"] == 2149 and s1["total_capacity"] == 2 * 8 + 0  # K1 + K3 usable
    client.post("/api/v1/sessions/1/kunds/2/block", json={"blocked": False}, headers=auth(admin_token))
    assert client.get("/api/v1/sessions/1/kund-map", headers=auth(admin_token)).json()["data"]["blocked"] == []
    fams = client.get("/api/v1/sessions/1/kunds?kund_number=3", headers=auth(admin_token)).json()["data"]
    assert fams[0]["families"][0]["coordinator_name"] == "Rahul Sharma"


# ------------------------------------------------------------ analytics
def test_analytics_matches_dashboard_shape(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=3, sessions=[1, 4])  # day 1 morning + day 2 afternoon
    register_ok(client, payload=registration_payload(members=1, sessions=[1], city="Mathura"))
    clock.freeze(DURING_SESSION_1)
    scanner = make_staff("SCANNER", session_id=1)[1]
    a = client.get("/api/v1/admin/analytics", headers=auth(admin_token)).json()["data"]
    assert a["families"] == 2 and a["people"] == 4 and a["seatsUsed"] == 7 and a["seatsTotal"] == 275328
    assert len(a["days"]) == 8 and set(a["days"][0]) == {"date", "morning", "afternoon"}
    assert a["days"][0]["morning"]["used"] == 4 and a["days"][0]["afternoon"]["used"] == 0
    assert a["days"][1]["afternoon"]["used"] == 3
    assert a["days"][0]["morning"]["partial"] == 1
    assert a["ages"]["13-30"] == 3 and a["gender"] == {"male": 3, "female": 1, "other": 0}
    assert a["sizes"][3] == 1 and a["sizes"][1] == 1 and a["avgFamily"] == 2
    assert a["cities"][0] == ["Agra", 3] and len(a["trend"]) == 14
    assert ["Self", 2] in a["rel"]
    assert client.get("/api/v1/admin/analytics", headers=auth(scanner)).status_code == 403


# ---------------------------------------------------------- bookings list
def test_bookings_search_q_date_slot_expand(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, payload=registration_payload(members=2, sessions=[1], mobile="9871111111",
                                                         name="Govind Prasad"))
    register_ok(client, members=1, sessions=[4])
    h = auth(admin_token)
    assert client.get("/api/v1/bookings?q=Govind", headers=h).json()["meta"]["total"] == 1
    assert client.get("/api/v1/bookings?q=priya", headers=h).json()["meta"]["total"] == 1  # member name
    assert client.get("/api/v1/bookings?q=98711", headers=h).json()["meta"]["total"] == 1
    assert client.get(f"/api/v1/bookings?q={a['booking_number'][:8]}", headers=h).json()["meta"]["total"] >= 1
    assert client.get("/api/v1/bookings?event_date=2026-12-15&slot=AFTERNOON", headers=h).json()["meta"]["total"] == 1
    assert client.get("/api/v1/bookings?event_date=2026-12-14&slot=AFTERNOON", headers=h).json()["meta"]["total"] == 0
    full = client.get("/api/v1/bookings?q=Govind&expand=true", headers=h).json()["data"][0]
    assert full["primary_mobile"] == "9871111111"
    assert [m["relationship"] for m in full["members"]] == ["Self", "Child"]
    assert full["reservations"][0]["kund_number"] == 1 and full["reservations"][0]["checked_in_by"] is None
