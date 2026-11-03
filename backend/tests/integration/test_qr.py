"""QR pass generation, hashing, validation, retrieval, regeneration and revocation."""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import auth, register_ok, registration_payload


def test_one_active_pass_per_booking_and_only_hash_stored(client, db: Session) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=3, sessions=[1, 3, 5])
    token = data["qr_pass"]["token"]
    rows = db.execute(text("SELECT token_hash, is_active FROM qr_passes")).all()
    assert len(rows) == 1 and rows[0][1] is True
    assert rows[0][0] == hashlib.sha256(token.encode()).hexdigest()
    # The raw token appears nowhere in the database in plain text.
    dump = db.execute(
        text(
            "SELECT string_agg(t, ' ') FROM ("
            " SELECT row_to_json(q)::text t FROM qr_passes q UNION ALL"
            " SELECT row_to_json(i)::text FROM idempotency_records i UNION ALL"
            " SELECT row_to_json(a)::text FROM audit_logs a) x"
        )
    ).scalar()
    assert token not in dump


def test_token_entropy_and_uniqueness(client) -> None:  # type: ignore[no-untyped-def]
    tokens = {register_ok(client, members=1)["qr_pass"]["token"] for _ in range(5)}
    assert len(tokens) == 5
    assert all(len(t) >= 43 for t in tokens)  # 32 bytes base64url


def test_pass_retrieval_with_token(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, members=2, sessions=[1, 3])
    r = client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["token"]})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["booking_number"] == data["booking_number"]
    assert [m["member_number"] for m in body["members"]] == [1, 2]
    assert [x["session_id"] for x in body["reservations"]] == [1, 3]
    # Full QR payload is accepted too.
    assert client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["qr_payload"]}).status_code == 200


def test_invalid_token_rejected_uniformly(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/qr/pass", json={"token": "x" * 43})
    assert r.status_code == 404 and r.json()["error"]["code"] == "INVALID_QR"


def test_qr_image_download_png_and_svg(client) -> None:  # type: ignore[no-untyped-def]
    token = register_ok(client)["qr_pass"]["token"]
    png = client.post("/api/v1/qr/pass/image", json={"token": token})
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    svg = client.post("/api/v1/qr/pass/image", json={"token": token, "format": "svg"})
    assert svg.status_code == 200 and b"<svg" in svg.content
    assert client.post("/api/v1/qr/pass/image", json={"token": "y" * 43}).status_code == 404


def test_regenerate_revokes_old_token(client, db: Session, supervisor_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client)
    old = data["qr_pass"]["token"]
    r = client.post(f"/api/v1/qr/{data['booking_number']}/regenerate", headers=auth(supervisor_token))
    assert r.status_code == 200
    new = r.json()["data"]["token"]
    assert new != old
    assert client.post("/api/v1/qr/pass", json={"token": old}).status_code == 404
    assert client.post("/api/v1/qr/pass", json={"token": new}).status_code == 200
    assert db.execute(text("SELECT count(*) FROM qr_passes WHERE is_active")).scalar() == 1
    assert db.execute(text("SELECT count(*) FROM qr_passes")).scalar() == 2  # history kept
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'QR_REGENERATED'")).scalar() == 1


def test_revoked_qr_is_rejected(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client)
    r = client.post(
        f"/api/v1/qr/{data['booking_number']}/revoke", json={"reason": "Reported lost"}, headers=auth(admin_token)
    )
    assert r.status_code == 200
    assert client.post("/api/v1/qr/pass", json={"token": data["qr_pass"]["token"]}).status_code == 404
    v = client.post("/api/v1/qr/validate", json={"token": data["qr_pass"]["token"]}, headers=auth(admin_token))
    assert v.json()["data"]["valid"] is False and v.json()["data"]["pass_active"] is False


def test_qr_validate_endpoint(client, admin_token: str) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client)
    v = client.post("/api/v1/qr/validate", json={"token": data["qr_pass"]["qr_payload"]}, headers=auth(admin_token))
    assert v.json()["data"] == {
        "valid": True, "booking_number": data["booking_number"], "booking_status": "CONFIRMED",
        "pass_active": True, "expired": False,
    }
    assert client.post("/api/v1/qr/validate", json={"token": data["qr_pass"]["token"]}).status_code == 401


def test_public_status_lookup_requires_matching_mobile(client) -> None:  # type: ignore[no-untyped-def]
    data = register_ok(client, payload=registration_payload(mobile="9844444444", sessions=[1, 3]))
    ok = client.post("/api/v1/qr/status", json={"booking_number": data["booking_number"], "primary_mobile": "9844444444"})
    assert ok.status_code == 200
    assert ok.json()["data"] == {
        "booking_number": data["booking_number"], "booking_status": "CONFIRMED", "pass_active": True,
        "member_count": 2, "confirmed_sessions": 2,
    }
    assert "Rahul" not in ok.text and "9844444444" not in ok.text
    wrong = client.post("/api/v1/qr/status", json={"booking_number": data["booking_number"], "primary_mobile": "9844444445"})
    unknown = client.post("/api/v1/qr/status", json={"booking_number": "MY26-AAAAAAAA", "primary_mobile": "9844444444"})
    assert wrong.status_code == unknown.status_code == 404
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
