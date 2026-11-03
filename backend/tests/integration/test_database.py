"""Seed counts and database-level integrity guarantees (real PostgreSQL)."""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.conftest import register_ok


def scalar(db: Session, sql: str, **p: object) -> object:
    return db.execute(text(sql), p).scalar()


def test_exactly_16_sessions_with_correct_dates_and_slots(db: Session) -> None:
    rows = db.execute(text("SELECT id, event_date, slot, start_time, end_time FROM event_sessions ORDER BY id")).all()
    assert len(rows) == 16
    assert [r[0] for r in rows] == list(range(1, 17))
    assert rows[0][1] == date(2026, 12, 14) and rows[-1][1] == date(2026, 12, 21)
    assert {r[2] for r in rows} == {"MORNING", "AFTERNOON"}
    assert sum(1 for r in rows if r[2] == "MORNING") == 8
    # Confirmed times: 08:00-11:00 and 13:00-16:00 IST.
    assert (rows[0][3], rows[0][4]) == (time(8, 0), time(11, 0))
    assert (rows[1][3], rows[1][4]) == (time(13, 0), time(16, 0))


def test_exactly_2151_kunds(db: Session) -> None:
    assert scalar(db, "SELECT count(*) FROM kunds") == 2151
    assert scalar(db, "SELECT min(kund_number) FROM kunds") == 1
    assert scalar(db, "SELECT max(kund_number) FROM kunds") == 2151


def test_exactly_34416_capacity_rows_all_8_and_0(db: Session) -> None:
    assert scalar(db, "SELECT count(*) FROM kund_session_capacity") == 34416
    assert scalar(db, "SELECT count(*) FROM kund_session_capacity WHERE capacity <> 8") == 0
    assert scalar(db, "SELECT count(*) FROM kund_session_capacity WHERE reserved_count <> 0") == 0
    # 17,208 per session, 275,328 attendee-session reservations overall.
    per_session = db.execute(text("SELECT sum(capacity) FROM kund_session_capacity GROUP BY session_id")).scalars().all()
    assert set(per_session) == {17208}
    assert scalar(db, "SELECT sum(capacity) FROM kund_session_capacity") == 275328


def test_seed_is_idempotent(db: Session) -> None:
    from app.services.seed_service import seed_all

    report = seed_all(db)
    assert (report.sessions, report.kunds, report.capacity_rows) == (16, 2151, 34416)


def test_reserved_count_cannot_be_changed_directly(db: Session) -> None:
    with pytest.raises(DBAPIError, match="reserved_count can only change through booking_sessions"):
        db.execute(text("UPDATE kund_session_capacity SET reserved_count = 3 WHERE session_id = 1 AND kund_id = 1"))
    db.rollback()


def test_capacity_cannot_be_changed_directly(db: Session) -> None:
    with pytest.raises(DBAPIError, match="controlled maintenance"):
        db.execute(text("UPDATE kund_session_capacity SET capacity = 7 WHERE session_id = 1 AND kund_id = 1"))
    db.rollback()


def test_capacity_check_constraint_blocks_overbooking(db: Session) -> None:
    db.execute(text("SELECT set_config('mahayagya.capacity_admin', 'on', true)"))
    with pytest.raises(IntegrityError, match="reserved_within_capacity"):
        db.execute(text("UPDATE kund_session_capacity SET reserved_count = 9 WHERE session_id = 1 AND kund_id = 1"))
    db.rollback()


def test_member_count_must_match_member_rows_at_commit(db: Session) -> None:
    db.execute(
        text(
            "INSERT INTO bookings (booking_number, coordinator_name, primary_mobile, address, city, state, pincode, "
            "gotra, sankalp_purpose, member_count) VALUES ('MY26-TEST0001', 'A B', '9999999999', 'Addr 1', 'Agra', "
            "'Uttar Pradesh', '282001', 'Kashyap', 'Wellbeing', 3)"
        )
    )
    db.execute(text("INSERT INTO family_members (booking_id, member_number, full_name) SELECT id, 1, 'X Y' FROM bookings"))
    with pytest.raises(IntegrityError, match="declares 3 members but has 1"):
        db.commit()
    db.rollback()


def test_family_size_above_8_rejected_by_database(db: Session) -> None:
    with pytest.raises(IntegrityError, match="member_count_range"):
        db.execute(
            text(
                "INSERT INTO bookings (booking_number, coordinator_name, primary_mobile, address, city, state, "
                "pincode, gotra, sankalp_purpose, member_count) VALUES ('MY26-TEST0002', 'A B', '9999999999', "
                "'Addr 1', 'Agra', 'Uttar Pradesh', '282001', 'Kashyap', 'Wellbeing', 9)"
            )
        )
    db.rollback()


def test_reservation_member_count_must_equal_family_size(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[1])
    bid = scalar(db, "SELECT id FROM bookings WHERE booking_number = :b", b=data["booking_number"])
    with pytest.raises(IntegrityError, match="fk_booking_sessions_booking_member_count"):
        db.execute(
            text("INSERT INTO booking_sessions (booking_id, session_id, kund_id, member_count) VALUES (:b, 2, 5, 2)"),
            {"b": bid},
        )
    db.rollback()


def test_unique_reservation_per_booking_and_session(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=1, sessions=[1])
    bid = scalar(db, "SELECT id FROM bookings WHERE booking_number = :b", b=data["booking_number"])
    with pytest.raises(IntegrityError, match="uq_booking_sessions_booking_session"):
        db.execute(
            text("INSERT INTO booking_sessions (booking_id, session_id, kund_id, member_count) VALUES (:b, 1, 9, 1)"),
            {"b": bid},
        )
    db.rollback()


def test_checkin_member_must_belong_to_booking(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=1, sessions=[1])
    b = register_ok(client, members=1, sessions=[1])
    a_id = scalar(db, "SELECT id FROM bookings WHERE booking_number = :b", b=a["booking_number"])
    b_member = scalar(
        db, "SELECT m.id FROM family_members m JOIN bookings b ON b.id = m.booking_id WHERE b.booking_number = :b",
        b=b["booking_number"],
    )
    a_bs = scalar(db, "SELECT id FROM booking_sessions WHERE booking_id = :b", b=a_id)
    with pytest.raises(IntegrityError, match="fk_attendance_checkins_member"):
        db.execute(
            text(
                "INSERT INTO attendance_checkins (event_id, booking_session_id, booking_id, member_id, checked_in_at) "
                "VALUES (gen_random_uuid(), :bs, :b, :m, now())"
            ),
            {"bs": a_bs, "b": a_id, "m": b_member},
        )
    db.rollback()


@pytest.mark.parametrize("table", ["bookings", "family_members", "booking_sessions", "qr_passes", "audit_logs"])
def test_historical_records_cannot_be_deleted(client, db: Session, table: str) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=1, sessions=[1])
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(text(f"DELETE FROM {table}"))
    db.rollback()


def test_audit_log_is_append_only(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=1, sessions=[1])
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE audit_logs SET action = 'X'"))
    db.rollback()


def test_cancelled_reservation_cannot_be_reactivated(client, db: Session, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1])
    client.post(
        f"/api/v1/bookings/{data['booking_number']}/cancel",
        json={"reason": "Test cancel"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    with pytest.raises(DBAPIError, match="cannot be re-activated"):
        db.execute(text("UPDATE booking_sessions SET status = 'CONFIRMED'"))
    db.rollback()


def test_row_level_security_enabled_on_all_tables(db: Session) -> None:
    rows = db.execute(
        text("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' "
             "AND relname <> 'alembic_version' AND NOT relrowsecurity")
    ).scalars().all()
    assert rows == []
