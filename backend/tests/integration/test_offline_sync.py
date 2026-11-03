"""Offline venue check-in: snapshot -> local LAN check-in -> idempotent cloud sync.

The "cloud" and the "local node" share one test database here (the offline
tables are separate from the cloud tables), and the local node's HTTP client
talks to the real FastAPI app through the TestClient.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from scripts.offline_node import CloudClient, preload, sync
from tests.conftest import DURING_SESSION_1, STAFF_PASSWORD, auth, make_staff, register_ok


@pytest.fixture
def node_mode(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "OFFLINE_NODE_MODE", True)


@pytest.fixture
def cloud(client):  # type: ignore[no-untyped-def]
    make_staff("SUPERVISOR", email="sync@example.org")
    return CloudClient("http://testserver", "sync@example.org", STAFF_PASSWORD, http=client)


def test_snapshot_contains_hashes_not_tokens(client, cloud) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=3, sessions=[1])
    snap = cloud.snapshot(1)
    assert len(snap["entries"]) == 1
    entry = snap["entries"][0]
    assert entry["booking_number"] == fam["booking_number"] and len(entry["token_hash"]) == 64
    assert fam["qr_pass"]["token"] not in json.dumps(snap)
    assert [m["member_number"] for m in entry["members"]] == [1, 2, 3]


def test_offline_checkin_and_idempotent_sync(client, db: Session, cloud, node_mode) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=3, sessions=[1])
    other = register_ok(client, members=2, sessions=[1])
    assert preload(cloud, 1) == {"roster_entries": 2, "cloud_checkins_imported": 0}
    clock.freeze(DURING_SESSION_1)
    gate1 = make_staff("SCANNER", session_id=1)[1]
    gate2 = make_staff("SCANNER", session_id=1)[1]
    qr = fam["qr_pass"]["qr_payload"]

    scan = client.post("/api/v1/offline/local/scan", json={"qr_payload": qr}, headers=auth(gate1)).json()["data"]
    assert scan["status"] == "VALID" and scan["kund_number"] == fam["reservations"][0]["kund_number"]
    r1 = client.post("/api/v1/offline/local/checkin", json={"qr_payload": qr, "member_number": 1}, headers=auth(gate1))
    assert r1.json()["data"]["status"] == "CHECKIN_SUCCESS"
    # Another gate on the same LAN server sees the duplicate.
    r2 = client.post("/api/v1/offline/local/checkin", json={"qr_payload": qr, "member_number": 1}, headers=auth(gate2))
    assert r2.json()["data"]["status"] == "ALREADY_CHECKED_IN"
    client.post("/api/v1/offline/local/checkin", json={"qr_payload": qr, "member_number": 2}, headers=auth(gate2))
    client.post("/api/v1/offline/local/checkin", json={"qr_payload": other["qr_pass"]["qr_payload"], "member_number": 1},
                headers=auth(gate1))

    # Meanwhile, member 2 of the first family was also checked in online (e.g. a 4G gate).
    online = make_staff("SCANNER", session_id=1)[1]
    client.post("/api/v1/scanner/checkin", json={"qr_payload": qr, "member_number": 2}, headers=auth(online))

    assert db.execute(text("SELECT count(*) FROM offline_checkin_events WHERE synced_at IS NULL")).scalar() == 3
    totals = sync(cloud, "venue-gate-a")
    assert totals == {"ACCEPTED": 2, "ALREADY_CHECKED_IN": 1}
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 3  # 2 offline + 1 online
    assert db.execute(text("SELECT count(*) FROM attendance_checkins WHERE source = 'OFFLINE_SYNC'")).scalar() == 2
    assert db.execute(text("SELECT count(*) FROM offline_checkin_events WHERE synced_at IS NULL")).scalar() == 0

    # Re-sending the same events (e.g. after a crash before mark_synced) is a no-op.
    events = [
        {"event_id": str(e), "session_id": 1, "booking_number": bn, "member_number": m, "checked_in_at": at.isoformat()}
        for e, bn, m, at in db.execute(
            text("SELECT event_id, booking_number, member_number, checked_in_at FROM offline_checkin_events")
        )
    ]
    again = cloud.push("venue-gate-a", events)
    assert all(r["replayed"] for r in again)
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 3


def test_sync_rejects_cancelled_reservation_for_review(client, db: Session, cloud, node_mode, admin_token) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=1, sessions=[1])
    preload(cloud, 1)
    # Cancelled in the cloud AFTER the snapshot was taken.
    client.post(f"/api/v1/bookings/{fam['booking_number']}/cancel", json={"reason": "Cancelled late"},
                headers=auth(admin_token))
    clock.freeze(DURING_SESSION_1)
    gate = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/offline/local/checkin", json={"qr_payload": fam["qr_pass"]["qr_payload"], "member_number": 1},
                    headers=auth(gate))
    assert r.json()["data"]["status"] == "CHECKIN_SUCCESS"  # documented limitation while offline
    assert sync(cloud, "venue-gate-a") == {"REJECTED": 1}
    detail = db.execute(text("SELECT sync_detail FROM offline_checkin_events")).scalar_one()
    assert "BOOKING_CANCELLED" in detail
    assert db.execute(text("SELECT count(*) FROM attendance_checkins")).scalar() == 0


def test_cloud_checkins_preloaded_prevent_offline_duplicates(client, cloud, node_mode) -> None:  # type: ignore[no-untyped-def]
    fam = register_ok(client, members=2, sessions=[1])
    clock.freeze(DURING_SESSION_1)
    online = make_staff("SCANNER", session_id=1)[1]
    client.post("/api/v1/scanner/checkin", json={"qr_payload": fam["qr_pass"]["qr_payload"], "member_number": 1},
                headers=auth(online))
    assert preload(cloud, 1)["cloud_checkins_imported"] == 1
    gate = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/offline/local/checkin", json={"qr_payload": fam["qr_pass"]["qr_payload"], "member_number": 1},
                    headers=auth(gate))
    assert r.json()["data"]["status"] == "ALREADY_CHECKED_IN"


def test_local_endpoints_disabled_in_cloud_mode(client) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(DURING_SESSION_1)
    gate = make_staff("SCANNER", session_id=1)[1]
    r = client.post("/api/v1/offline/local/scan", json={"qr_payload": "MY26." + "a" * 43}, headers=auth(gate))
    assert r.status_code == 404


def test_local_status(client, cloud, node_mode) -> None:  # type: ignore[no-untyped-def]
    register_ok(client, members=1, sessions=[1])
    preload(cloud, 1)
    with get_sessionmaker()() as s:
        from app.services.offline_sync_service import LocalNodeService

        assert LocalNodeService(s).status()["roster_entries_by_session"] == {1: 1}
