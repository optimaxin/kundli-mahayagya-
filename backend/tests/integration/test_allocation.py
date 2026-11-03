"""Best-fit Kund allocation engine (service + database, sequential cases)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import (
    assert_capacity_consistent,
    capacity_admin,
    only_kunds_active,
    register,
    register_ok,
    reserved,
)


def kund_of(data: dict, session_id: int = 1) -> int:
    return next(r["kund_number"] for r in data["reservations"] if r["session_id"] == session_id)


def test_best_fit_fills_partially_occupied_kund(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    """Spec example: Kund 101 has 6/8; a family of 2 must go to Kund 101."""
    only_kunds_active(db, [100, 101, 102])
    capacity_admin(
        db,
        "UPDATE kund_session_capacity SET reserved_count = 6 WHERE session_id = 1 "
        "AND kund_id = (SELECT id FROM kunds WHERE kund_number = 101)",
    )
    # (reserved_count changed out-of-band only for the test setup.)
    data = register_ok(client, members=2, sessions=[1])
    assert kund_of(data) == 101
    assert reserved(db, 1, 101) == 8


def test_best_fit_chooses_fullest_kund_that_fits(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    a = register_ok(client, members=6)  # K1 -> 6/8
    assert kund_of(a) == 1
    b = register_ok(client, members=4)  # does not fit K1 (2 free) -> K2 4/8
    assert kund_of(b) == 2
    c = register_ok(client, members=2)  # K1 (2 free) is a better fit than K2 (4 free)
    assert kund_of(c) == 1
    d = register_ok(client, members=1)  # K2 (4 free) better than empty K3 (8 free)
    assert kund_of(d) == 2
    e = register_ok(client, members=3)  # K2 now has exactly 3 free -> perfect fit
    assert kund_of(e) == 2
    assert reserved(db, 1, 1) == 8 and reserved(db, 1, 2) == 8 and reserved(db, 1, 3) == 0
    assert_capacity_consistent(db)


def test_empty_kund_used_when_no_partial_kund_fits(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=7)  # K1 7/8
    data = register_ok(client, members=2)  # K1 has 1 free -> new empty Kund
    assert kund_of(data) == 2


def test_family_is_never_split(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1, 2])
    register_ok(client, members=5)  # K1 5/8
    register_ok(client, members=5)  # K2 5/8 -> 6 free seats in total, but no Kund has 4 together
    r = register(client, members=4)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAPACITY_UNAVAILABLE"
    rows = db.execute(text("SELECT count(DISTINCT kund_id) FROM booking_sessions GROUP BY booking_id")).scalars().all()
    assert set(rows) == {1}


def test_no_available_kund(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1])
    register_ok(client, members=7)
    r = register(client, members=2)
    assert r.status_code == 409
    assert r.json()["error"]["details"]["availability"][0]["largest_family_bookable"] == 1
    register_ok(client, members=1)  # exactly fills Kund 1
    assert reserved(db, 1, 1) == 8
    assert register(client, members=1).status_code == 409


def test_inactive_kunds_never_allocated(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    db.execute(text("UPDATE kunds SET is_active = false WHERE kund_number <= 10"))
    db.commit()
    assert kund_of(register_ok(client, members=3)) == 11


def test_capacity_is_independent_per_session(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=8, sessions=[1])
    data = register_ok(client, members=8, sessions=[1, 3])
    by = {r["session_id"]: r["kund_number"] for r in data["reservations"]}
    assert by == {1: 2, 3: 1}  # Kund 1 is full in session 1 only


def test_no_kund_ever_exceeds_8(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    only_kunds_active(db, [1, 2, 3])
    sizes = [3, 5, 2, 6, 1, 4, 1, 2, 7, 8, 1]
    for s in sizes:
        register(client, members=s)
    assert db.execute(text("SELECT max(reserved_count) FROM kund_session_capacity")).scalar() <= 8
    assert_capacity_consistent(db)


def test_allocation_service_rolls_back_all_sessions_on_failure(db: Session) -> None:
    """Direct service-level check of the all-or-nothing rule."""
    import pytest

    from app.core.errors import CapacityUnavailable
    from app.services.allocation_service import AllocationService

    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = capacity WHERE session_id = 3")
    db.execute(
        text(
            "INSERT INTO bookings (booking_number, coordinator_name, primary_mobile, address, city, state, pincode, "
            "gotra, sankalp_purpose, member_count) VALUES ('MY26-ALLOC001', 'A B', '9999999999', 'Addr 1', 'Agra', "
            "'Uttar Pradesh', '282001', 'Kashyap', 'Wellbeing', 2)"
        )
    )
    bid = db.execute(text("SELECT id FROM bookings")).scalar_one()
    with pytest.raises(CapacityUnavailable):
        AllocationService(db).allocate_family(booking_id=bid, family_size=2, session_ids=[1, 2, 3])
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM booking_sessions")).scalar() == 0
    assert db.execute(
        text("SELECT coalesce(sum(reserved_count), 0) FROM kund_session_capacity WHERE session_id IN (1, 2)")
    ).scalar() == 0
