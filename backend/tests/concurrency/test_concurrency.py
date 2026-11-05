"""Real concurrency tests: many threads, each with its OWN PostgreSQL connection,
released simultaneously by a barrier. These exercise the actual row locks,
triggers and constraints -- nothing is mocked.
"""

from __future__ import annotations

import random
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_sessionmaker
from app.core.errors import AppError
from app.schemas.registration import RegistrationRequest
from app.services.audit_service import RequestContext
from app.services.cancellation_service import CancellationService
from app.services.checkin_service import CheckinService
from app.services.registration_service import RegistrationService
from tests.conftest import (
    DURING_SESSION_1,
    assert_capacity_consistent,
    capacity_admin,
    make_staff,
    only_kunds_active,
    registration_payload,
    reserved,
)

pytestmark = pytest.mark.concurrency


def run_concurrently(n: int, fn: Callable[[int], Any]) -> list[Any]:
    """Run fn(i) for i in range(n) in n threads released at the same instant."""
    barrier = threading.Barrier(n)

    def wrapper(i: int) -> Any:
        barrier.wait()
        try:
            return fn(i)
        except AppError as exc:
            return exc
        except Exception as exc:  # surfaced in assertions
            return exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(wrapper, range(n)))


def register_service(payload: dict[str, Any], key: str | None = None) -> dict[str, Any]:
    with get_sessionmaker()() as db:
        result = RegistrationService(db).register(
            RegistrationRequest.model_validate(payload),
            idempotency_key=key or uuid.uuid4().hex,
            ctx=RequestContext(request_id="concurrency-test"),
        )
        return result.payload


def codes(results: list[Any]) -> Counter[str]:
    return Counter("OK" if isinstance(r, dict) else getattr(r, "code", type(r).__name__) for r in results)


def test_two_families_compete_for_the_last_two_places(db: Session) -> None:
    only_kunds_active(db, [1])
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 6 WHERE session_id = 1 AND kund_id = 1")
    results = run_concurrently(2, lambda i: register_service(registration_payload(members=2, sessions=[1])))
    assert codes(results) == Counter({"OK": 1, "CAPACITY_UNAVAILABLE": 1}), results
    assert reserved(db, 1, 1) == 8
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == 1


def test_concurrent_allocation_never_overbooks(db: Session) -> None:
    """60 families (sizes 1-4) race for 5 Kunds = 40 places."""
    only_kunds_active(db, [1, 2, 3, 4, 5])
    rng = random.Random(2151)
    sizes = [rng.randint(1, 4) for _ in range(60)]
    results = run_concurrently(
        len(sizes), lambda i: register_service(registration_payload(members=sizes[i], sessions=[1]))
    )
    c = codes(results)
    assert set(c) <= {"OK", "CAPACITY_UNAVAILABLE"}, c
    ok_sizes = [sizes[i] for i, r in enumerate(results) if isinstance(r, dict)]
    total_reserved = db.execute(text("SELECT sum(reserved_count) FROM kund_session_capacity WHERE session_id = 1")).scalar()
    assert total_reserved == sum(ok_sizes) <= 40
    assert db.execute(text("SELECT max(reserved_count) FROM kund_session_capacity")).scalar() <= 8
    # Each successful family got exactly one Kund; no family split.
    assert db.execute(text("SELECT count(*) FROM booking_sessions")).scalar() == len(ok_sizes)
    assert_capacity_consistent(db)
    # Best-fit packing under contention still leaves at most a few seats unused.
    assert total_reserved >= 36, total_reserved


def test_concurrent_overlapping_multi_session_bookings_do_not_deadlock(db: Session) -> None:
    """Families select overlapping session sets in different orders; all must succeed."""
    rng = random.Random(7)
    # 2-4 different days each: the morning, the afternoon or both sessions of each day.
    selections = [
        sorted({2 * d + 1 + s for d in rng.sample(range(4), k=rng.randint(2, 4))
                for s in rng.choice([[0], [1], [0, 1]])})
        for _ in range(40)
    ]
    sizes = [rng.randint(1, 8) for _ in range(40)]
    results = run_concurrently(
        len(selections),
        lambda i: register_service(registration_payload(members=sizes[i], sessions=selections[i])),
    )
    assert codes(results) == Counter({"OK": 40}), [r for r in results if not isinstance(r, dict)][:3]
    expected = sum(len(s) for s in selections)
    assert db.execute(text("SELECT count(*) FROM booking_sessions")).scalar() == expected
    assert_capacity_consistent(db)


def test_concurrent_multi_session_contention_is_all_or_nothing(db: Session) -> None:
    """Session 3 has room for only ONE more 4-member family; many race for sessions [1, 3]."""
    only_kunds_active(db, [1, 2])
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 8 WHERE session_id = 3 AND kund_id = 2")
    capacity_admin(db, "UPDATE kund_session_capacity SET reserved_count = 4 WHERE session_id = 3 AND kund_id = 1")
    results = run_concurrently(10, lambda i: register_service(registration_payload(members=4, sessions=[1, 3])))
    assert codes(results) == Counter({"OK": 1, "CAPACITY_UNAVAILABLE": 9}), codes(results)
    # Losers left no trace in session 1.
    assert db.execute(text("SELECT sum(reserved_count) FROM kund_session_capacity WHERE session_id = 1")).scalar() == 4
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == 1


def test_concurrent_both_session_bookings_never_overbook_either_session(db: Session) -> None:
    """Only Kunds 1-2 are active (16 places per session). Families race for the morning, the
    afternoon or both sessions of 14 Dec; neither session may be overbooked and a family that
    asked for both sessions gets both or nothing."""
    only_kunds_active(db, [1, 2])
    rng = random.Random(11)
    picks = [rng.choice([[1], [2], [1, 2], [1, 2]]) for _ in range(24)]
    sizes = [rng.randint(2, 5) for _ in range(24)]
    results = run_concurrently(
        len(picks), lambda i: register_service(registration_payload(members=sizes[i], sessions=picks[i]))
    )
    c = codes(results)
    assert set(c) <= {"OK", "CAPACITY_UNAVAILABLE"}, c
    assert c["OK"] > 0 and c["CAPACITY_UNAVAILABLE"] > 0, c  # the test really created contention
    for sid in (1, 2):
        total = db.execute(text("SELECT sum(reserved_count) FROM kund_session_capacity WHERE session_id = :s"),
                           {"s": sid}).scalar()
        assert total <= 16, (sid, total)
        assert reserved(db, sid, 1) <= 8 and reserved(db, sid, 2) <= 8
    # all-or-nothing: each booking holds exactly the sessions it asked for
    held = dict(db.execute(text(
        "SELECT b.booking_number, array_agg(bs.session_id ORDER BY bs.session_id) FROM bookings b "
        "JOIN booking_sessions bs ON bs.booking_id = b.id GROUP BY 1")).all())
    ok = {r["booking_number"]: picks[i] for i, r in enumerate(results) if isinstance(r, dict)}
    assert held == ok
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == c["OK"]
    assert_capacity_consistent(db)


def test_concurrent_duplicate_requests_with_same_idempotency_key(db: Session) -> None:
    payload = registration_payload(members=3, sessions=[1, 3])
    key = uuid.uuid4().hex
    results = run_concurrently(8, lambda i: register_service(payload, key=key))
    assert codes(results) == Counter({"OK": 8}), results
    assert len({r["booking_number"] for r in results}) == 1
    assert len({r["qr_pass"]["token"] for r in results}) == 1
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == 1
    assert db.execute(text("SELECT sum(reserved_count) FROM kund_session_capacity")).scalar() == 6


def test_concurrent_duplicate_registrations_same_mobile_without_shared_key(db: Session) -> None:
    payload = registration_payload(members=2, sessions=[1], mobile="9833333333")
    results = run_concurrently(6, lambda i: register_service(payload))  # different keys (double click)
    assert codes(results) == Counter({"OK": 1, "DUPLICATE_BOOKING": 5}), codes(results)
    assert db.execute(text("SELECT count(*) FROM bookings")).scalar() == 1


def test_concurrent_duplicate_cancellations_release_capacity_once(db: Session) -> None:
    data = register_service(registration_payload(members=5, sessions=[1, 3]))
    admin, _ = make_staff("ADMIN")
    ctx = RequestContext(actor_id=admin.id, actor_role="ADMIN")

    def cancel(_: int) -> dict[str, Any]:
        with get_sessionmaker()() as s:
            return CancellationService(s).cancel(data["booking_number"], reason="Dup cancel", session_ids=None, ctx=ctx)

    results = run_concurrently(8, cancel)
    assert all(isinstance(r, dict) for r in results), results
    assert sum(r["released_capacity"] for r in results) == 10  # 5 members x 2 sessions, once
    assert sum(1 for r in results if not r["already_cancelled"]) == 1
    assert db.execute(text("SELECT coalesce(sum(reserved_count), 0) FROM kund_session_capacity")).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM cancellation_events")).scalar() == 2
    assert_capacity_consistent(db)


def test_concurrent_cancellation_and_registration_reuse_capacity_safely(db: Session) -> None:
    only_kunds_active(db, [1])
    first = register_service(registration_payload(members=8, sessions=[1]))
    admin, _ = make_staff("ADMIN")
    ctx = RequestContext(actor_id=admin.id, actor_role="ADMIN")

    def work(i: int) -> Any:
        if i == 0:
            with get_sessionmaker()() as s:
                return CancellationService(s).cancel(first["booking_number"], reason="Free it", session_ids=None, ctx=ctx)
        return register_service(registration_payload(members=4, sessions=[1]))

    results = run_concurrently(5, work)
    assert isinstance(results[0], dict)
    # After the cancel, at most 2 families of 4 fit; whichever registrations ran
    # before the cancel committed were correctly rejected.
    assert reserved(db, 1, 1) <= 8
    assert_capacity_consistent(db)


def test_concurrent_checkin_of_same_member_records_exactly_one(db: Session) -> None:
    from app.core import clock

    data = register_service(registration_payload(members=2, sessions=[1]))
    clock.freeze(DURING_SESSION_1)
    scanners = [make_staff("SCANNER", session_id=1)[0] for _ in range(6)]

    def checkin(i: int) -> dict[str, Any]:
        with get_sessionmaker()() as s:
            return CheckinService(s).checkin(scanners[i], data["qr_pass"]["qr_payload"], member_number=1)

    results = run_concurrently(6, checkin)
    statuses = Counter(str(r["status"]) for r in results)
    assert statuses == Counter({"CHECKIN_SUCCESS": 1, "ALREADY_CHECKED_IN": 5}), statuses
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 1
