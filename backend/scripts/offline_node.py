"""Venue local-server tooling (run ON the local server, OFFLINE_NODE_MODE=true).

Commands:
    preload --session-id N   Pull the roster snapshot for session N from the cloud
                             API and load it into the local database.
    sync [--batch 200]       Push unsynced local check-in events to the cloud
                             (idempotent; safe to re-run / run from cron).
    status                   Show local roster/event counts.

Cloud credentials come from the environment: CLOUD_API_BASE_URL,
CLOUD_SYNC_EMAIL, CLOUD_SYNC_PASSWORD (a SUPERVISOR account), OFFLINE_NODE_ID.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.services.offline_sync_service import LocalNodeService


class CloudClient:
    def __init__(self, base_url: str, email: str, password: str, *, http: httpx.Client | None = None) -> None:
        self._client = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self._credentials = {"email": email, "password": password}
        self._token = ""
        self._login()

    def _login(self) -> None:
        resp = self._client.post("/api/v1/auth/login", json=self._credentials)
        resp.raise_for_status()
        self._token = resp.json()["data"]["access_token"]

    def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        """Send with the bearer token; re-login once if the token has expired."""
        for attempt in (1, 2):
            resp = self._client.request(method, url, headers={"Authorization": f"Bearer {self._token}"}, **kw)
            if resp.status_code == 401 and attempt == 1:
                self._login()
                continue
            resp.raise_for_status()
            return resp
        raise AssertionError("unreachable")  # pragma: no cover

    def snapshot(self, session_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/offline/snapshot/{session_id}").json()["data"]

    def push(self, node_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resp = self._request("POST", "/api/v1/offline/sync/checkins", json={"node_id": node_id, "events": events})
        return resp.json()["data"]

    def close(self) -> None:
        self._client.close()


def preload(client: CloudClient, session_id: int) -> dict[str, int]:
    snapshot = client.snapshot(session_id)
    with get_sessionmaker()() as db:
        return LocalNodeService(db).load_snapshot(snapshot)


def sync(client: CloudClient, node_id: str, batch: int = 200) -> dict[str, int]:
    totals: dict[str, int] = {}
    with get_sessionmaker()() as db:
        service = LocalNodeService(db)
        while True:
            pending = service.pending_events(batch)
            if not pending:
                break
            events = [
                {
                    "event_id": str(e.event_id),
                    "session_id": e.session_id,
                    "booking_number": e.booking_number,
                    "member_number": e.member_number,
                    "checked_in_at": e.checked_in_at.isoformat(),
                }
                for e in pending
            ]
            db.rollback()
            results = client.push(node_id, events)
            service.mark_synced(results)
            for r in results:
                totals[r["result"]] = totals.get(r["result"], 0) + 1
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preload")
    p.add_argument("--session-id", type=int, required=True)
    s = sub.add_parser("sync")
    s.add_argument("--batch", type=int, default=200)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.cmd == "status":
        with get_sessionmaker()() as db:
            print(json.dumps(LocalNodeService(db).status(), indent=2, default=str))
        return 0

    if not (settings.CLOUD_API_BASE_URL and settings.CLOUD_SYNC_EMAIL and settings.CLOUD_SYNC_PASSWORD):
        print("CLOUD_API_BASE_URL, CLOUD_SYNC_EMAIL and CLOUD_SYNC_PASSWORD must be set", file=sys.stderr)
        return 2
    try:
        client = CloudClient(settings.CLOUD_API_BASE_URL, settings.CLOUD_SYNC_EMAIL, settings.CLOUD_SYNC_PASSWORD)
    except httpx.HTTPError as exc:
        print(f"Cloud unreachable or login failed: {type(exc).__name__}. Retry when online.", file=sys.stderr)
        return 1
    try:
        if args.cmd == "preload":
            print(json.dumps(preload(client, args.session_id)))
        else:
            if not settings.OFFLINE_NODE_ID:
                print("OFFLINE_NODE_ID must be set", file=sys.stderr)
                return 2
            print(json.dumps(sync(client, settings.OFFLINE_NODE_ID, args.batch)))
    except httpx.HTTPError as exc:
        print(f"Cloud request failed: {type(exc).__name__}. Nothing was lost; re-run later.", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
