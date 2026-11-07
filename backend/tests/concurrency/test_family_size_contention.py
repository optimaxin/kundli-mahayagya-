"""Concurrent bookings competing for the last Kund that fits a given family size (1, 2, 3, 8).

The public availability check is informational. These tests show that the locked best-fit
allocation at booking time is the real authority: it re-reads capacity under the session lock,
falls back to another suitable Kund when the best one was just taken, and rejects the whole
(multi-session) booking when none is left.
"""

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.concurrency.test_concurrency import codes, register_service, run_concurrently
from tests.conftest import capacity_admin, only_kunds_active, registration_payload, reserved

pytestmark = pytest.mark.concurrency

MORNING, AFTERNOON = 1, 2


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


def session_total(db: Session, session_id: int) -> int:
    return db.execute(text("SELECT sum(reserved_count) FROM kund_session_capacity WHERE session_id = :s"),
                      {"s": session_id}).scalar_one()


def kund_of(result: dict, session_id: int = MORNING) -> int:
    return next(r["kund_number"] for r in result["reservations"] if r["session_id"] == session_id)


def test_family_of_one_race_for_the_last_single_place(db: Session) -> None:
    only_kunds_active(db, [1])
    set_reserved(db, MORNING, 1, 7)
    results = run_concurrently(8, lambda i: register_service(registration_payload(members=1, sessions=[MORNING])))
    assert codes(results) == Counter({"OK": 1, "CAPACITY_UNAVAILABLE": 7}), codes(results)
    assert reserved(db, MORNING, 1) == 8
    assert_never_overbooked(db)


def test_family_of_two_falls_back_to_another_suitable_kund(db: Session) -> None:
    """Both families saw 'AVAILABLE'. The first takes the best fit (K1, 2 free); the second
    re-reads under the lock and gets the next suitable Kund (K2) instead of failing."""
    only_kunds_active(db, [1, 2])
    set_reserved(db, MORNING, 1, 6)  # 2 free (best fit)
    set_reserved(db, MORNING, 2, 4)  # 4 free
    results = run_concurrently(2, lambda i: register_service(registration_payload(members=2, sessions=[MORNING])))
    assert codes(results) == Counter({"OK": 2}), results
    assert sorted(kund_of(r) for r in results) == [1, 2]
    assert reserved(db, MORNING, 1) == 8 and reserved(db, MORNING, 2) == 6
    assert_never_overbooked(db)


def test_families_of_two_race_where_single_places_do_not_help(db: Session) -> None:
    """K1 has 2 free, K2 and K3 have 1 free each: 4 places, but only ONE family of 2 can be seated."""
    only_kunds_active(db, [1, 2, 3])
    set_reserved(db, MORNING, 1, 6)
    set_reserved(db, MORNING, 2, 7)
    set_reserved(db, MORNING, 3, 7)
    results = run_concurrently(5, lambda i: register_service(registration_payload(members=2, sessions=[MORNING])))
    assert codes(results) == Counter({"OK": 1, "CAPACITY_UNAVAILABLE": 4}), codes(results)
    assert reserved(db, MORNING, 1) == 8 and reserved(db, MORNING, 2) == 7 and reserved(db, MORNING, 3) == 7
    assert_never_overbooked(db)


def test_families_of_three_compete_for_the_last_suitable_kund_while_a_single_still_fits(db: Session) -> None:
    """K1 has 3 free (the only Kund for a family of 3), K2 has 1 free. Two families of 3 and one
    family of 1 arrive together: exactly one family of 3 wins K1, the family of 1 gets K2."""
    only_kunds_active(db, [1, 2])
    set_reserved(db, MORNING, 1, 5)
    set_reserved(db, MORNING, 2, 7)
    sizes = [3, 3, 1]
    results = run_concurrently(3, lambda i: register_service(registration_payload(members=sizes[i], sessions=[MORNING])))
    by_size = Counter((sizes[i], "OK" if isinstance(r, dict) else r.code) for i, r in enumerate(results))
    assert by_size == Counter({(3, "OK"): 1, (3, "CAPACITY_UNAVAILABLE"): 1, (1, "OK"): 1}), by_size
    winners = {sizes[i]: kund_of(r) for i, r in enumerate(results) if isinstance(r, dict)}
    assert winners == {3: 1, 1: 2}
    assert reserved(db, MORNING, 1) == 8 and reserved(db, MORNING, 2) == 8
    assert_never_overbooked(db)


def test_families_of_eight_race_for_the_empty_kunds(db: Session) -> None:
    """Two empty Kunds (+ one partly filled that cannot take 8): exactly two families of 8 win."""
    only_kunds_active(db, [1, 2, 3])
    set_reserved(db, MORNING, 1, 1)  # 7 free: never enough for 8
    results = run_concurrently(6, lambda i: register_service(registration_payload(members=8, sessions=[MORNING])))
    assert codes(results) == Counter({"OK": 2, "CAPACITY_UNAVAILABLE": 4}), codes(results)
    assert sorted(kund_of(r) for r in results if isinstance(r, dict)) == [2, 3]
    assert reserved(db, MORNING, 1) == 1 and session_total(db, MORNING) == 17
    assert_never_overbooked(db)


def test_both_session_booking_loses_the_afternoon_race_and_reserves_nothing(db: Session) -> None:
    """Family A (2 members) books MORNING + AFTERNOON; families B (2 members) book only the AFTERNOON,
    whose last suitable Kund has exactly 2 free. Whoever loses the afternoon gets nothing at all."""
    only_kunds_active(db, [1])
    set_reserved(db, AFTERNOON, 1, 6)
    picks = [[MORNING, AFTERNOON]] + [[AFTERNOON]] * 4
    results = run_concurrently(
        len(picks), lambda i: register_service(registration_payload(members=2, sessions=picks[i]))
    )
    assert codes(results) == Counter({"OK": 1, "CAPACITY_UNAVAILABLE": 4}), codes(results)
    assert reserved(db, AFTERNOON, 1) == 8
    a_won = isinstance(results[0], dict)
    # Morning holds the family's 2 places only if the both-session booking won; never a partial booking.
    assert reserved(db, MORNING, 1) == (2 if a_won else 0)
    held = db.execute(text("SELECT array_agg(session_id ORDER BY session_id) FROM booking_sessions "
                           "GROUP BY booking_id")).scalars().all()
    assert held == ([[MORNING, AFTERNOON]] if a_won else [[AFTERNOON]])
    assert_never_overbooked(db)
