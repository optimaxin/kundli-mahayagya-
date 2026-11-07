"""Family-size-based public availability (no exact capacity exposed) + authoritative allocation.

Public ``GET /sessions?family_size=N`` says, per session, only whether a family of N can be seated
together in ONE Kund (``AVAILABLE`` / ``NOT_FOR_THIS_FAMILY`` / ``FULL`` / ``CLOSED``). The real
allocation still happens under row locks in ``POST /registrations``; staff keep exact numbers via
``GET /sessions/capacity``, the dashboard, the Kund map and the reports.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import (
    assert_capacity_consistent,
    auth,
    capacity_admin,
    make_staff,
    only_kunds_active,
    register,
    register_ok,
    registration_payload,
    reserved,
)

PUBLIC_SESSION_KEYS = {
    "id", "event_date", "slot", "start_time", "end_time", "status", "is_active",
    "booking_open", "family_size", "availability", "fits_family",
}  # fmt: skip
# Session 1 = 14 Dec MORNING, session 2 = 14 Dec AFTERNOON (same date).
MORNING, AFTERNOON = 1, 2


def availability(client, family_size: int) -> dict[int, str]:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/sessions", params={"family_size": family_size})
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert all(row["family_size"] == family_size for row in rows)
    assert all(row["fits_family"] == (row["availability"] == "AVAILABLE") for row in rows)
    return {row["id"]: row["availability"] for row in rows}


def assert_never_overbooked(db: Session) -> None:
    """Occupancy is partly seeded out-of-band here, so check the hard invariant directly."""
    assert db.execute(text("SELECT count(*) FROM kund_session_capacity WHERE reserved_count > capacity")).scalar() == 0


def set_reserved(db: Session, session_id: int, kund_number: int, n: int) -> None:
    capacity_admin(
        db,
        "UPDATE kund_session_capacity SET reserved_count = :n WHERE session_id = :s "
        "AND kund_id = (SELECT id FROM kunds WHERE kund_number = :k)",
        {"n": n, "s": session_id, "k": kund_number},
    )


def kund_of(data: dict[str, Any], session_id: int = MORNING) -> int:
    return next(r["kund_number"] for r in data["reservations"] if r["session_id"] == session_id)


def count(db: Session, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


# ------------------------------------------------------------- 1. family of 1, one place left
def test_family_of_one_fits_the_last_single_place(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1])
    set_reserved(db, MORNING, 1, 7)  # Kund 1: 7/8 -> exactly one place
    assert availability(client, 1)[MORNING] == "AVAILABLE"
    data = register_ok(client, members=1, sessions=[MORNING])
    assert kund_of(data) == 1 and reserved(db, MORNING, 1) == 8
    # Now nothing is left for anybody.
    assert {availability(client, n)[MORNING] for n in range(1, 9)} == {"FULL"}


# ------------------------------------------------------------- 2. family of 2, one place left
def test_family_of_two_does_not_fit_a_single_place(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1])
    set_reserved(db, MORNING, 1, 7)
    assert availability(client, 2)[MORNING] == "NOT_FOR_THIS_FAMILY"
    assert availability(client, 3)[MORNING] == "NOT_FOR_THIS_FAMILY"
    r = register(client, members=2, sessions=[MORNING])
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAPACITY_UNAVAILABLE"
    assert reserved(db, MORNING, 1) == 7 and count(db, "bookings") == 0


# ------------------------------------------- 6. a Kund stays eligible for smaller families
def test_kund_too_small_for_large_family_stays_open_for_small_family(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1])
    set_reserved(db, MORNING, 1, 5)  # 3 places left in the only Kund
    states = availability_matrix(client, MORNING)
    assert states == {1: "AVAILABLE", 2: "AVAILABLE", 3: "AVAILABLE", 4: "NOT_FOR_THIS_FAMILY",
                      5: "NOT_FOR_THIS_FAMILY", 6: "NOT_FOR_THIS_FAMILY", 7: "NOT_FOR_THIS_FAMILY",
                      8: "NOT_FOR_THIS_FAMILY"}
    assert register(client, members=4, sessions=[MORNING]).status_code == 409  # not marked full ...
    assert kund_of(register_ok(client, members=2, sessions=[MORNING])) == 1  # ... a smaller family still fits
    assert availability_matrix(client, MORNING) == {1: "AVAILABLE", **{n: "NOT_FOR_THIS_FAMILY" for n in range(2, 9)}}


def availability_matrix(client, session_id: int) -> dict[int, str]:  # type: ignore[no-untyped-def]
    return {n: availability(client, n)[session_id] for n in range(1, 9)}


# ----------------------------------------- 3. family of 3 uses a different Kund that fits
def test_family_of_three_uses_another_kund_with_room(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1, 2])
    set_reserved(db, MORNING, 1, 7)  # 1 free
    set_reserved(db, MORNING, 2, 3)  # 5 free
    assert availability(client, 3)[MORNING] == "AVAILABLE"
    assert kund_of(register_ok(client, members=3, sessions=[MORNING])) == 2
    # Best-fit still holds: a family of 1 goes to the fullest Kund that fits (Kund 1), not Kund 2.
    assert kund_of(register_ok(client, members=1, sessions=[MORNING])) == 1
    assert reserved(db, MORNING, 1) == 8 and reserved(db, MORNING, 2) == 6
    assert_never_overbooked(db)


# ----------------------------------------------------- 4. family of 8 needs an empty Kund
def test_family_of_eight_gets_the_empty_kund(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1, 2, 3])
    set_reserved(db, MORNING, 1, 7)
    set_reserved(db, MORNING, 2, 1)
    assert availability(client, 8)[MORNING] == "AVAILABLE"  # Kund 3 is empty
    assert kund_of(register_ok(client, members=8, sessions=[MORNING])) == 3
    assert availability(client, 8)[MORNING] == "NOT_FOR_THIS_FAMILY"  # 8 places remain in total, but split
    assert availability(client, 7)[MORNING] == "AVAILABLE"  # Kund 2 has 7 free
    assert register(client, members=8, sessions=[MORNING]).status_code == 409


# ---------------------------------------------------------------- 5. family of 9 rejected
def test_family_size_outside_1_to_8_rejected(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    for bad in (0, 9, -1):
        r = client.get("/api/v1/sessions", params={"family_size": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", bad
    assert client.get("/api/v1/sessions", params={"family_size": "x"}).status_code == 422
    r = register(client, payload=registration_payload(members=9, sessions=[MORNING]))
    assert r.status_code == 422
    assert count(db, "bookings") == 0


# ------------------------------------------------- 7. MORNING and AFTERNOON are independent
def test_morning_and_afternoon_availability_are_independent(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1])
    set_reserved(db, MORNING, 1, 7)  # morning: 1 free
    set_reserved(db, AFTERNOON, 1, 2)  # afternoon: 6 free
    a4 = availability(client, 4)
    assert a4[MORNING] == "NOT_FOR_THIS_FAMILY" and a4[AFTERNOON] == "AVAILABLE"
    assert kund_of(register_ok(client, members=4, sessions=[AFTERNOON]), AFTERNOON) == 1
    assert reserved(db, MORNING, 1) == 7  # morning untouched
    a1 = availability(client, 1)
    assert a1[MORNING] == "AVAILABLE" and a1[AFTERNOON] == "AVAILABLE"
    set_reserved(db, MORNING, 1, 8)
    a1 = availability(client, 1)
    assert a1[MORNING] == "FULL" and a1[AFTERNOON] == "AVAILABLE"


# ------------------------------------------------- 8. both sessions of the same date
def test_both_sessions_on_the_same_date_for_each_family_size(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    for size in (1, 2, 3, 8):
        a = availability(client, size)
        assert a[MORNING] == a[AFTERNOON] == "AVAILABLE"
        data = register_ok(client, members=size, sessions=[MORNING, AFTERNOON])
        assert {r["session_id"] for r in data["reservations"]} == {MORNING, AFTERNOON}
        assert all(r["member_count"] == size for r in data["reservations"])
    assert db.execute(text(
        "SELECT session_id, sum(reserved_count) FROM kund_session_capacity WHERE session_id IN (1, 2) "
        "GROUP BY session_id ORDER BY session_id")).all() == [(1, 14), (2, 14)]
    assert_capacity_consistent(db)


# ---------------------------------- 10. atomic failure when one selected session cannot fit
def test_multi_session_booking_fails_atomically_when_one_session_cannot_fit(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1])
    set_reserved(db, AFTERNOON, 1, 7)  # afternoon cannot take 2; morning can
    a2 = availability(client, 2)
    assert a2[MORNING] == "AVAILABLE" and a2[AFTERNOON] == "NOT_FOR_THIS_FAMILY"
    r = register(client, members=2, sessions=[MORNING, AFTERNOON, 3])
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "CAPACITY_UNAVAILABLE" and err["details"]["unavailable_sessions"] == [AFTERNOON]
    assert {a["session_id"]: a["availability"] for a in err["details"]["availability"]} == {
        MORNING: "AVAILABLE", AFTERNOON: "NOT_FOR_THIS_FAMILY", 3: "AVAILABLE"}
    for table in ("bookings", "family_members", "booking_sessions", "qr_passes"):
        assert count(db, table) == 0, table
    assert reserved(db, MORNING, 1) == 0 and reserved(db, 3, 1) == 0 and reserved(db, AFTERNOON, 1) == 7


def test_closed_session_is_closed_for_every_family_size(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    db.execute(text("UPDATE event_sessions SET status = 'CLOSED' WHERE id = 3"))
    db.commit()
    assert {availability(client, n)[3] for n in range(1, 9)} == {"CLOSED"}
    assert availability(client, 8)[4] == "AVAILABLE"


def test_backend_ignores_client_supplied_kund_or_availability_claims(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    """Extra fields (kund ids, availability flags) are rejected; the server picks the Kund itself."""
    only_kunds_active(db, [1, 2])
    set_reserved(db, MORNING, 2, 6)
    for extra in ({"kund_number": 1}, {"kund_id": 1}, {"fits_family": True}, {"family_size": 1}):
        p = registration_payload(members=2, sessions=[MORNING])
        p.update(extra)
        assert register(client, payload=p).status_code == 422, extra
    assert kund_of(register_ok(client, members=2, sessions=[MORNING])) == 2  # best-fit, server-chosen


# --------------------------------------------- 11. no exact capacity in public responses
def test_public_responses_expose_no_capacity_numbers(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1, 2])
    set_reserved(db, MORNING, 1, 5)
    for size in range(1, 9):
        rows = client.get("/api/v1/sessions", params={"family_size": size}).json()["data"]
        assert len(rows) == 16
        for row in rows:
            assert set(row) == PUBLIC_SESSION_KEYS, set(row) ^ PUBLIC_SESSION_KEYS
    default = client.get("/api/v1/sessions").json()["data"]
    assert all(set(row) == PUBLIC_SESSION_KEYS and row["family_size"] == 1 for row in default)

    # Capacity-failure details: per-session yes/no only.
    set_reserved(db, AFTERNOON, 1, 8)
    set_reserved(db, AFTERNOON, 2, 7)
    r = register(client, members=3, sessions=[MORNING, AFTERNOON])
    assert r.status_code == 409
    details = r.json()["error"]["details"]
    assert set(details) == {"unavailable_sessions", "availability"}
    for a in details["availability"]:
        assert set(a) == {"session_id", "availability", "fits_this_family"}
    for leaked in ("remaining", "reserved", "largest", "capacity", "kunds_"):
        assert leaked not in r.text.lower().replace("capacity_unavailable", ""), leaked

    # Successful registration and the ticket show the family's own Kund, nothing about other seats.
    data = register_ok(client, members=2, sessions=[MORNING])
    p = client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["token"]})
    for body in (str(data), p.text):
        for leaked in ("remaining", "reserved_count", "largest_family", "total_capacity", "kunds_empty"):
            assert leaked not in body, leaked


def test_staff_capacity_endpoint_requires_admin_or_supervisor(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/sessions/capacity").status_code == 401
    scanner = make_staff("SCANNER", session_id=1)[1]
    assert client.get("/api/v1/sessions/capacity", headers=auth(scanner)).status_code == 403
    for role in ("ADMIN", "SUPERVISOR"):
        assert client.get("/api/v1/sessions/capacity", headers=auth(make_staff(role)[1])).status_code == 200


# ---------------------------------------------- 12. admin reports keep accurate capacity
def test_admin_views_still_report_exact_capacity(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=3, sessions=[MORNING, AFTERNOON])
    register_ok(client, members=8, sessions=[MORNING])
    register_ok(client, members=1, sessions=[MORNING])

    cap = {s["id"]: s for s in client.get("/api/v1/sessions/capacity", headers=auth(admin_token)).json()["data"]}
    m, a = cap[MORNING], cap[AFTERNOON]
    assert (m["total_capacity"], m["reserved"], m["remaining"]) == (17208, 12, 17196)
    assert (m["kunds_full"], m["kunds_empty"], m["largest_family_bookable"]) == (1, 2149, 8)
    assert (a["reserved"], a["remaining"], a["kunds_empty"]) == (3, 17205, 2150)

    dash = client.get("/api/v1/admin/dashboard", headers=auth(admin_token)).json()["data"]
    assert dash["capacity"]["reserved"] == 15 and dash["capacity"]["remaining"] == 275328 - 15

    summary = client.get("/api/v1/reports/summary?report_date=2026-12-14", headers=auth(admin_token)).json()["data"]
    by_id = {s["session_id"]: s for s in summary}
    assert (by_id[MORNING]["reserved"], by_id[MORNING]["remaining"], by_id[MORNING]["kunds_in_use"]) == (12, 17196, 2)
    assert (by_id[AFTERNOON]["reserved"], by_id[AFTERNOON]["remaining"]) == (3, 17205)

    occ = client.get(f"/api/v1/sessions/{MORNING}/kund-map", headers=auth(admin_token)).json()["data"]["occ"]
    assert occ == {"1": 4, "2": 8}  # family of 3 -> K1, family of 8 -> K2, family of 1 -> K1 (best fit)
