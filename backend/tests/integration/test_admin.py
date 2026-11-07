"""Admin dashboard, search, Kund views, audit logs, user management, integrity."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import STAFF_PASSWORD, auth, make_staff, register_ok, registration_payload


def test_dashboard_totals(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=3, sessions=[1, 3])
    register_ok(client, members=8, sessions=[1])
    client.post(f"/api/v1/bookings/{a['booking_number']}/cancel", json={"reason": "Changed plans"},
                headers=auth(admin_token))
    d = client.get("/api/v1/admin/dashboard", headers=auth(admin_token)).json()["data"]
    assert d["total_family_bookings"] == 2
    assert d["confirmed_bookings"] == 1 and d["cancelled_bookings"] == 1
    assert d["total_registered_members"] == 11
    assert d["members_in_confirmed_bookings"] == 8
    assert d["confirmed_attendee_session_reservations"] == 8
    assert d["capacity"]["total_attendee_session_capacity"] == 275328
    assert d["capacity"]["remaining"] == 275328 - 8


def test_public_session_availability(client) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=8, sessions=[1])
    data = client.get("/api/v1/sessions").json()["data"]
    assert len(data) == 16
    s1 = data[0]
    assert s1["availability"] == "AVAILABLE" and s1["fits_family"] is True and s1["family_size"] == 1
    for hidden in ("total_capacity", "reserved", "remaining", "kunds_full", "kunds_empty", "largest_family_bookable"):
        assert hidden not in s1, hidden


def test_staff_session_capacity_has_exact_numbers(client, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=8, sessions=[1])
    data = client.get("/api/v1/sessions/capacity", headers=auth(supervisor_token)).json()["data"]
    assert len(data) == 16
    s1 = data[0]
    assert s1["total_capacity"] == 17208 and s1["reserved"] == 8 and s1["remaining"] == 17200
    assert s1["kunds_full"] == 1 and s1["kunds_empty"] == 2150 and s1["largest_family_bookable"] == 8


def test_session_detail_and_kund_allocation(client, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=6)
    register_ok(client, members=2)
    d = client.get("/api/v1/sessions/1", headers=auth(supervisor_token)).json()["data"]
    assert d["confirmed_families"] == 2 and d["completed"] is False and d["no_shows"] is None
    r = client.get("/api/v1/sessions/1/kunds?only_occupied=true", headers=auth(supervisor_token)).json()
    assert r["meta"]["total"] == 1
    k = r["data"][0]
    assert k["kund_number"] == 1 and k["reserved_count"] == 8 and k["remaining"] == 0
    assert {f["booking_number"] for f in k["families"]} >= {a["booking_number"]}
    page = client.get("/api/v1/sessions/1/kunds?page=2&page_size=100", headers=auth(supervisor_token)).json()
    assert page["meta"] == {"page": 2, "page_size": 100, "total": 2151, "total_pages": 22}
    kund = client.get("/api/v1/kunds/1", headers=auth(supervisor_token)).json()["data"]
    assert len(kund["sessions"]) == 16 and kund["sessions"][0]["reserved_count"] == 8


def test_search_by_booking_number_and_details(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=2, sessions=[1, 3])
    register_ok(client, members=1)
    r = client.get(f"/api/v1/bookings?booking_number={a['booking_number']}", headers=auth(admin_token)).json()
    assert r["meta"]["total"] == 1 and r["data"][0]["session_count"] == 2
    assert "*" in r["data"][0]["primary_mobile_masked"]
    detail = client.get(f"/api/v1/bookings/{a['booking_number']}", headers=auth(admin_token)).json()["data"]
    assert detail["primary_mobile"].isdigit() and len(detail["members"]) == 2
    assert [x["session_id"] for x in detail["reservations"]] == [1, 3]
    members = client.get(f"/api/v1/family-members?booking_number={a['booking_number']}", headers=auth(admin_token))
    assert len(members.json()["data"]) == 2
    sessions = client.get(f"/api/v1/bookings/{a['booking_number']}/sessions", headers=auth(admin_token))
    assert [s["kund_number"] for s in sessions.json()["data"]] == [1, 1]


def test_search_by_mobile_is_audited(client, db: Session, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(mobile="9855555555"))
    r = client.get("/api/v1/bookings?mobile=+91%209855555555", headers=auth(supervisor_token))
    assert r.status_code == 200 and r.json()["meta"]["total"] == 1
    row = db.execute(text("SELECT new_values FROM audit_logs WHERE action = 'BOOKING_SEARCH_BY_MOBILE'")).scalar_one()
    assert row == {"mobile_masked": "98******55", "results": 1, "returned": 1}


def test_search_filters_sorting_and_pagination(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    for n in (1, 5, 3):
        register_ok(client, members=n, sessions=[2])
    register_ok(client, members=2, sessions=[4])
    r = client.get("/api/v1/bookings?session_id=2&sort=member_count&order=asc&page_size=2", headers=auth(admin_token))
    body = r.json()
    assert body["meta"]["total"] == 3 and body["meta"]["total_pages"] == 2
    assert [b["member_count"] for b in body["data"]] == [1, 3]
    assert client.get("/api/v1/bookings?sort=password", headers=auth(admin_token)).status_code == 422


def test_audit_logs_admin_only(client, admin_token: str, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client)
    r = client.get("/api/v1/admin/audit-logs?action=BOOKING_CREATED", headers=auth(admin_token))
    assert r.status_code == 200 and r.json()["meta"]["total"] == 1
    assert client.get("/api/v1/admin/audit-logs", headers=auth(supervisor_token)).status_code == 403


def test_user_management(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/admin/users",
        json={"full_name": "Gate One", "email": "Gate1@Example.org", "password": STAFF_PASSWORD, "role": "SCANNER",
              "assigned_session_id": 3},
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    user = r.json()["data"]
    assert user["email"] == "gate1@example.org" and user["assigned_session_id"] == 3
    assert "password" not in str(user) and "hash" not in str(user)
    weak = client.post("/api/v1/admin/users", json={"full_name": "Weak Pw", "email": "w@example.org",
                                                    "password": "short", "role": "SUPERVISOR"}, headers=auth(admin_token))
    assert weak.status_code == 422
    dup = client.post("/api/v1/admin/users", json={"full_name": "Gate One", "email": "gate1@example.org",
                                                   "password": STAFF_PASSWORD, "role": "SCANNER"}, headers=auth(admin_token))
    assert dup.status_code == 409
    upd = client.patch(f"/api/v1/admin/users/{user['id']}", json={"assigned_session_id": 4}, headers=auth(admin_token))
    assert upd.json()["data"]["assigned_session_id"] == 4
    h = db.execute(text("SELECT password_hash FROM admin_users WHERE email = 'gate1@example.org'")).scalar_one()
    assert h.startswith("$argon2id$")


def test_session_update_admin_only_and_audited(client, db: Session, admin_token: str, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    assert client.patch("/api/v1/sessions/5", json={"status": "CLOSED"}, headers=auth(supervisor_token)).status_code == 403
    r = client.patch("/api/v1/sessions/5", json={"status": "CLOSED"}, headers=auth(admin_token))
    assert r.json()["data"]["status"] == "CLOSED"
    assert client.patch("/api/v1/sessions/5", json={"capacity": 9}, headers=auth(admin_token)).status_code == 422
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'SESSION_UPDATED'")).scalar() == 1


def test_integrity_report_ok(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=4, sessions=[1, 3])
    register_ok(client, members=7, sessions=[3])
    client.post(f"/api/v1/bookings/{a['booking_number']}/cancel", json={"reason": "Test", "session_ids": [1]},
                headers=auth(admin_token))
    r = client.get("/api/v1/admin/integrity", headers=auth(admin_token)).json()["data"]
    assert r["ok"] is True and r["capacity_mismatches"] == [] and r["overbooked_kunds"] == 0


def test_scanner_cannot_access_admin_views(client) -> None:  # type: ignore[no-untyped-def]
    token = make_staff("SCANNER", session_id=1)[1]
    for path in ("/api/v1/admin/dashboard", "/api/v1/bookings", "/api/v1/sessions/1", "/api/v1/checkins",
                 "/api/v1/reports/summary", "/api/v1/offline/snapshot/1"):
        assert client.get(path, headers=auth(token)).status_code == 403, path
