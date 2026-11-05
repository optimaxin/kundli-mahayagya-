"""Business rule (Nov 2026): a family may book the MORNING, the AFTERNOON or BOTH sessions of a date.

Session ids: 1 = 14 Dec morning, 2 = 14 Dec afternoon, 3 = 15 Dec morning, 4 = 15 Dec afternoon, ...
"""

from __future__ import annotations

import io

from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from tests.conftest import (
    assert_capacity_consistent,
    auth,
    capacity_admin,
    ist,
    make_staff,
    register,
    register_ok,
    registration_payload,
    reserved,
)

TABLES = ("bookings", "family_members", "booking_sessions", "qr_passes", "idempotency_records")


def count(db: Session, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608 - fixed table names


def kunds(data: dict) -> dict[int, int]:
    return {r["session_id"]: r["kund_number"] for r in data["reservations"]}


def fill_session(db: Session, session_id: int) -> None:
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = capacity WHERE session_id = :s",
                   {"s": session_id})


def session_total(db: Session, session_id: int) -> int:
    return db.execute(text("SELECT coalesce(sum(reserved_count), 0) FROM kund_session_capacity WHERE session_id = :s"),
                      {"s": session_id}).scalar_one()


# ------------------------------------------------------------------ booking combinations
def test_morning_only(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[1])
    assert list(kunds(data)) == [1]
    assert session_total(db, 1) == 3 and session_total(db, 2) == 0


def test_afternoon_only(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[2])
    assert list(kunds(data)) == [2]
    assert session_total(db, 1) == 0 and session_total(db, 2) == 3


def test_both_sessions_on_the_same_date(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=4, sessions=[2, 1])
    assert sorted(kunds(data)) == [1, 2]
    assert {r["event_date"] for r in data["reservations"]} == {"2026-12-14"}
    assert session_total(db, 1) == 4 and session_total(db, 2) == 4  # each session holds the whole family
    assert count(db, "bookings") == 1 and count(db, "booking_sessions") == 2 and count(db, "qr_passes") == 1
    assert_capacity_consistent(db)


def test_both_sessions_across_multiple_dates(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1, 2, 3, 4, 7])  # 14 Dec both, 15 Dec both, 17 Dec morning
    assert sorted(kunds(data)) == [1, 2, 3, 4, 7]
    assert count(db, "booking_sessions") == 5
    assert sum(session_total(db, s) for s in (1, 2, 3, 4, 7)) == 10
    assert_capacity_consistent(db)


def test_all_sixteen_sessions_in_one_booking(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=1, sessions=list(range(1, 17)))
    assert sorted(kunds(data)) == list(range(1, 17))


def test_duplicate_session_id_in_one_request_rejected(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    r = register(client, members=2, sessions=[1, 2, 1])
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert count(db, "bookings") == 0


def test_invalid_session_rejected_even_with_valid_same_day_pair(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    r = register(client, members=2, sessions=[1, 2, 99])
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_SESSION"
    assert r.json()["error"]["details"] == {"invalid_sessions": [99]}
    for table in TABLES:
        assert count(db, table) == 0, table


# ------------------------------------------------------------------ duplicates (same mobile)
def test_same_family_same_session_rejected(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(mobile="9814444444", sessions=[1, 2]))
    r = register(client, payload=registration_payload(mobile="9814444444", sessions=[2]))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_BOOKING"
    assert r.json()["error"]["details"] == {"sessions": [2]}
    assert count(db, "bookings") == 1 and session_total(db, 2) == 2


def test_same_family_other_session_of_the_same_date_accepted(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, payload=registration_payload(mobile="9815555555", members=3, sessions=[1]))  # morning
    register_ok(client, payload=registration_payload(mobile="9815555555", members=3, sessions=[2]))  # afternoon
    assert count(db, "bookings") == 2
    # one family, two bookings, two family-session reservations, 6 attendee places
    a = client.get("/api/v1/admin/analytics", headers=auth(admin_token)).json()["data"]
    assert (a["uniqueFamilies"], a["families"], a["familySessions"], a["seatsUsed"]) == (1, 2, 2, 6)


# ------------------------------------------------------------------ capacity
def test_morning_full_afternoon_still_bookable(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    fill_session(db, 1)
    r = register(client, members=2, sessions=[1])
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAPACITY_UNAVAILABLE"
    data = register_ok(client, members=2, sessions=[2])
    assert list(kunds(data)) == [2]


def test_afternoon_full_morning_still_bookable(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    fill_session(db, 2)
    r = register(client, members=2, sessions=[2])
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAPACITY_UNAVAILABLE"
    data = register_ok(client, members=2, sessions=[1])
    assert list(kunds(data)) == [1]


def test_both_sessions_fail_atomically_when_one_is_full(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    for full, free in ((1, 2), (2, 1)):
        fill_session(db, full)
        before_free = session_total(db, free)
        r = register(client, members=3, sessions=[1, 2])
        assert r.status_code == 409
        err = r.json()["error"]
        assert err["code"] == "CAPACITY_UNAVAILABLE" and err["details"]["unavailable_sessions"] == [full]
        assert session_total(db, free) == before_free  # nothing reserved in the session that had room
        for table in TABLES:
            assert count(db, table) == 0, table
        capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 0 WHERE session_id = :s", {"s": full})
    assert_capacity_consistent(db)


def test_each_session_gets_its_own_kund_by_best_fit(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    # Morning: Kund 1 has 6/8 (a 3-member family does not fit) -> next empty Kund (2).
    # Afternoon: Kund 1 has 5/8 -> exactly 3 free, best fit -> Kund 1.
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 6 WHERE session_id = 1 "
                       "AND kund_id = (SELECT id FROM kunds WHERE kund_number = 1)")
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 5 WHERE session_id = 2 "
                       "AND kund_id = (SELECT id FROM kunds WHERE kund_number = 1)")
    data = register_ok(client, members=3, sessions=[1, 2])
    assert kunds(data) == {1: 2, 2: 1}
    assert reserved(db, 1, 2) == 3 and reserved(db, 2, 1) == 8  # whole family in one Kund per session
    assert reserved(db, 1, 1) == 6


def test_full_family_of_eight_occupies_one_kund_in_each_session(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=8, sessions=[1, 2])
    k = kunds(data)
    assert reserved(db, 1, k[1]) == 8 and reserved(db, 2, k[2]) == 8
    rows = db.execute(text("SELECT session_id, count(DISTINCT kund_id), sum(member_count) FROM booking_sessions "
                           "GROUP BY session_id ORDER BY 1")).all()
    assert [tuple(r) for r in rows] == [(1, 1, 8), (2, 1, 8)]  # never split across Kunds


def test_cancelling_one_session_keeps_the_other(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1, 2])
    r = client.post(f"/api/v1/bookings/{data['booking_number']}/cancel",
                    json={"reason": "Only the morning", "session_ids": [2]}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert session_total(db, 1) == 2 and session_total(db, 2) == 0
    assert_capacity_consistent(db)


# ------------------------------------------------------------------ QR & attendance
def _checkin(client, token: str, qr: str, member: int) -> dict:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/scanner/checkin", json={"qr_payload": qr, "member_number": member}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _scan(client, token: str, qr: str) -> dict:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/scanner/scan", json={"qr_payload": qr}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_same_qr_checks_in_each_member_once_per_session(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[1, 2])
    qr = data["qr_pass"]["qr_payload"]
    clock.freeze(ist(2026, 12, 14, 8, 5))
    morning = make_staff("SCANNER", session_id=1)[1]
    afternoon = make_staff("SCANNER", session_id=2)[1]

    first = _scan(client, morning, qr)
    assert first["status"] == "VALID" and first["session"]["session_id"] == 1
    assert first["kund_number"] == kunds(data)[1]
    assert _checkin(client, morning, qr, 1)["status"] == "CHECKIN_SUCCESS"
    assert _checkin(client, morning, qr, 1)["status"] == "ALREADY_CHECKED_IN"  # duplicate in the same session
    assert _checkin(client, morning, qr, 2)["status"] == "CHECKIN_SUCCESS"

    clock.freeze(ist(2026, 12, 14, 13, 5))  # same QR, afternoon session
    roster = _scan(client, afternoon, qr)
    assert roster["status"] == "VALID" and roster["session"]["session_id"] == 2
    assert roster["kund_number"] == kunds(data)[2]
    assert [m["checked_in"] for m in roster["roster"]] == [False, False, False]  # morning check-ins do not leak
    assert _checkin(client, afternoon, qr, 1)["status"] == "CHECKIN_SUCCESS"  # member 1 again, new session
    assert _checkin(client, afternoon, qr, 1)["status"] == "ALREADY_CHECKED_IN"

    per_session = dict(db.execute(text(
        "SELECT bs.session_id, count(*) FROM attendance_checkins a "
        "JOIN booking_sessions bs ON bs.id = a.booking_session_id GROUP BY 1")).all())
    assert per_session == {1: 2, 2: 1}
    assert count(db, "qr_passes") == 1


def test_morning_scanner_cannot_check_in_afternoon_only_booking(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[2])
    clock.freeze(ist(2026, 12, 14, 8, 5))
    morning = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/scanner/checkin", json={"qr_payload": data["qr_pass"]["qr_payload"], "member_number": 1},
                    headers=auth(morning))
    body = r.json()
    status = body.get("data", {}).get("status") if r.status_code == 200 else body["error"]["code"]
    assert status not in ("CHECKIN_SUCCESS", "ALREADY_CHECKED_IN"), body


# ------------------------------------------------------------------ dashboard & Excel report
def test_dashboard_and_excel_report_for_a_two_session_family(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    both = register_ok(client, members=4, sessions=[1, 2])
    morning_only = register_ok(client, members=2, sessions=[1])
    qr = both["qr_pass"]["qr_payload"]
    clock.freeze(ist(2026, 12, 14, 8, 5))
    _checkin(client, make_staff("SCANNER", session_id=1)[1], qr, 1)
    clock.freeze(ist(2026, 12, 14, 13, 5))
    _checkin(client, make_staff("SCANNER", session_id=2)[1], qr, 1)
    _checkin(client, make_staff("SCANNER", session_id=2)[1], qr, 2)

    a = client.get("/api/v1/admin/analytics", headers=auth(admin_token)).json()["data"]
    assert (a["families"], a["uniqueFamilies"], a["familySessions"], a["people"], a["seatsUsed"], a["entered"]) == \
        (2, 2, 3, 6, 10, 3)
    day = next(d for d in a["days"] if d["date"] == "2026-12-14")
    assert (day["morning"]["used"], day["afternoon"]["used"]) == (6, 4)
    assert (day["morning"]["attended"], day["afternoon"]["attended"]) == (1, 2)

    clock.freeze(ist(2026, 12, 14, 17, 0))  # both sessions of the day completed
    job = client.post("/api/v1/reports/exports", json={"report_type": "DAILY", "report_date": "2026-12-14"},
                      headers=auth(admin_token)).json()["data"]
    content = client.get(f"/api/v1/reports/exports/{job['id']}/download", headers=auth(admin_token)).content
    wb = load_workbook(io.BytesIO(content), read_only=True)

    def rows(sheet: str) -> list[tuple]:
        return [r for r in wb[sheet].iter_rows(min_row=2, values_only=True) if r and r[0] is not None]

    dash = {r[0]: r[1] for r in rows("Dashboard") if isinstance(r[0], str)}
    assert dash["Confirmed family bookings"] == 2  # the two-session family is ONE booking
    assert dash["Unique families (distinct primary mobile, confirmed)"] == 2
    assert dash["Total unique registered members"] == 6
    assert dash["Family-session reservations (confirmed)"] == 3
    assert dash["Attendee-session reservations (confirmed)"] == 10
    assert dash["Actual check-ins"] == 3
    assert dash["No-shows (completed sessions only)"] == 7  # morning 6 - 1, afternoon 4 - 2

    bookings = {r[0]: r for r in rows("Family Bookings")}
    assert len(bookings) == 2
    sessions_col = bookings[both["booking_number"]][13]
    assert sessions_col == f"1:K{kunds(both)[1]}:C, 2:K{kunds(both)[2]}:C"  # session:kund:status (C = confirmed)
    assert len([r for r in rows("Family Members") if r[0] == both["booking_number"]]) == 4  # not doubled

    attendance = [r for r in rows("Session Attendance") if r[3] == both["booking_number"]]
    assert sorted((r[0], r[5]) for r in attendance) == [(s, m) for s in (1, 2) for m in (1, 2, 3, 4)]
    checked = sorted((r[0], r[5]) for r in attendance if r[8] in (True, "Yes", "YES"))
    assert checked == [(1, 1), (2, 1), (2, 2)]

    alloc = rows("Kund Allocation")
    fam_in = {r[0] for r in alloc if r[9] and both["booking_number"] in r[9]}
    assert fam_in == {1, 2}
    no_shows = [(r[0], r[5]) for r in rows("No Shows") if r[3] == both["booking_number"]]
    assert sorted(no_shows) == [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4)]
    assert morning_only["booking_number"] not in {r[3] for r in rows("No Shows") if r[0] == 2}
