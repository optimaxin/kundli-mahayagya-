"""Offline venue check-in: snapshot export, local LAN check-in, idempotent cloud sync.

Topology (see docs/architecture.md, "Offline check-in"):

    cloud API + PostgreSQL  <--- HTTPS (when available) --->  venue LOCAL server
                                                              (this same app with
                                                               OFFLINE_NODE_MODE=true
                                                               + its own PostgreSQL)
                                                                     ^   LAN / Wi-Fi
                                                         scanner devices (many)

1. Before the session, the local server PULLS a snapshot for its session:
   active QR token *hashes*, booking numbers, Kund numbers, member rosters and
   check-ins already recorded in the cloud.
2. During an outage, scanners talk only to the local server. Every check-in
   is stored durably in ``offline_checkin_events`` with a UUID event_id.
   UNIQUE(session, booking, member) gives LAN-wide duplicate prevention
   across all gates connected to that one local server.
3. When connectivity returns, the local server PUSHES unsynced events to the
   cloud. Ingestion is idempotent: each event_id gets exactly one receipt;
   re-sending returns the original outcome. Conflicts with a check-in already
   recorded online resolve to ALREADY_CHECKED_IN (the earliest stored row is
   kept, nothing is overwritten).

Limitations (documented, not hidden): two *separate* local servers that are
disconnected from each other cannot detect duplicates between them; passes
revoked or reservations cancelled after the snapshot are still accepted
locally and are flagged as REJECTED at sync time for manual review.
Registration/allocation is NEVER performed offline.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.database import run_transaction
from app.core.errors import NotFound
from app.models import (
    AdminUser,
    AttendanceCheckin,
    Booking,
    BookingSession,
    FamilyMember,
    Kund,
    OfflineCheckinEvent,
    OfflineRosterEntry,
    OfflineSyncReceipt,
    QrPass,
)
from app.models.enums import BookingStatus, CheckinResult, CheckinSource, ReservationStatus, SyncResult
from app.repositories.session_repository import SessionRepository
from app.services import session_service
from app.services.audit_service import RequestContext, audit

MAX_CLOCK_SKEW = timedelta(minutes=10)


# =========================================================== cloud side
class CloudSyncService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def export_snapshot(self, session_id: int, ctx: RequestContext) -> dict[str, Any]:
        db = self.db
        session = SessionRepository(db).get(session_id)
        if session is None:
            raise NotFound("Session not found")
        rows = db.execute(
            select(BookingSession, Booking.booking_number, Booking.status, Kund.kund_number, QrPass.token_hash)
            .join(Booking, Booking.id == BookingSession.booking_id)
            .join(Kund, Kund.id == BookingSession.kund_id)
            .join(QrPass, (QrPass.booking_id == Booking.id) & QrPass.is_active.is_(True))
            .where(BookingSession.session_id == session_id)
            .order_by(BookingSession.id)
        ).all()
        booking_ids = [bs.booking_id for bs, *_ in rows]
        members: dict[int, list[dict[str, Any]]] = {}
        if booking_ids:
            for bid, n, name in db.execute(
                select(FamilyMember.booking_id, FamilyMember.member_number, FamilyMember.full_name)
                .where(FamilyMember.booking_id.in_(booking_ids))
                .order_by(FamilyMember.booking_id, FamilyMember.member_number)
            ):
                members.setdefault(bid, []).append({"member_number": n, "full_name": name})
        entries = []
        for bs, bn, bstatus, kn, th in rows:
            status = (
                ReservationStatus.CANCELLED.value
                if bstatus == BookingStatus.CANCELLED.value
                else bs.status
            )
            entries.append(
                {"booking_number": bn, "token_hash": th, "reservation_status": status, "kund_number": kn,
                 "members": members.get(bs.booking_id, [])}
            )
        checkins = [
            {"event_id": str(eid), "booking_number": bn, "member_number": mn, "checked_in_at": at.isoformat()}
            for eid, bn, mn, at in db.execute(
                select(AttendanceCheckin.event_id, Booking.booking_number, FamilyMember.member_number,
                       AttendanceCheckin.checked_in_at)
                .join(BookingSession, BookingSession.id == AttendanceCheckin.booking_session_id)
                .join(Booking, Booking.id == AttendanceCheckin.booking_id)
                .join(FamilyMember, FamilyMember.id == AttendanceCheckin.member_id)
                .where(BookingSession.session_id == session_id)
            )
        ]
        generated = clock.now()
        version = hashlib.sha256(
            f"{session_id}:{generated.isoformat()}:{len(entries)}:{len(checkins)}".encode()
        ).hexdigest()[:32]
        audit(db, ctx, action="OFFLINE_SNAPSHOT_EXPORTED", entity_type="event_session", entity_id=session_id,
              new={"entries": len(entries), "checkins": len(checkins), "snapshot_version": version})
        db.commit()
        return {
            "session": {
                "session_id": session.id,
                "event_date": session.event_date.isoformat(),
                "slot": session.slot,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
            },
            "snapshot_version": version,
            "generated_at": generated.isoformat(),
            "entries": entries,
            "existing_checkins": checkins,
        }

    def ingest_events(self, node_id: str, events: list[dict[str, Any]], ctx: RequestContext) -> list[dict[str, Any]]:
        def work(db: Session) -> list[dict[str, Any]]:
            results = [self._ingest_one(db, node_id, ev) for ev in events]
            audit(db, ctx, action="OFFLINE_SYNC_INGESTED", entity_type="offline_node", entity_id=node_id,
                  new={k.value: sum(1 for r in results if r["result"] == k.value) for k in SyncResult})
            return results

        return run_transaction(self.db, work, label="offline_ingest")

    def _ingest_one(self, db: Session, node_id: str, ev: dict[str, Any]) -> dict[str, Any]:
        event_id: uuid.UUID = ev["event_id"]
        prior = db.get(OfflineSyncReceipt, event_id)
        if prior is not None:
            return {"event_id": event_id, "result": prior.result, "detail": prior.detail, "replayed": True}

        result, detail, checkin_id = self._apply(db, node_id, ev)
        inserted = db.execute(
            pg_insert(OfflineSyncReceipt)
            .values(event_id=event_id, node_id=node_id, result=result, detail=detail, checkin_id=checkin_id)
            .on_conflict_do_nothing()
            .returning(OfflineSyncReceipt.event_id)
        ).scalar_one_or_none()
        if inserted is None:  # a concurrent sync of the same event won the race
            prior = db.get(OfflineSyncReceipt, event_id)
            assert prior is not None
            return {"event_id": event_id, "result": prior.result, "detail": prior.detail, "replayed": True}
        return {"event_id": event_id, "result": result, "detail": detail, "replayed": False}

    def _apply(self, db: Session, node_id: str, ev: dict[str, Any]) -> tuple[str, str | None, int | None]:
        checked_at: datetime = ev["checked_in_at"]
        if checked_at > clock.now() + MAX_CLOCK_SKEW:
            return SyncResult.REJECTED.value, "checked_in_at is in the future (clock skew)", None
        booking = db.scalars(select(Booking).where(Booking.booking_number == ev["booking_number"])).first()
        if booking is None:
            return SyncResult.REJECTED.value, "Unknown booking", None
        bs = db.scalars(
            select(BookingSession).where(
                BookingSession.booking_id == booking.id, BookingSession.session_id == ev["session_id"]
            )
        ).first()
        if bs is None:
            return SyncResult.REJECTED.value, "No reservation for this session", None
        if bs.status != ReservationStatus.CONFIRMED.value or booking.status != BookingStatus.CONFIRMED.value:
            return SyncResult.REJECTED.value, "BOOKING_CANCELLED: reservation cancelled; review manually", None
        member = db.scalars(
            select(FamilyMember).where(
                FamilyMember.booking_id == booking.id, FamilyMember.member_number == ev["member_number"]
            )
        ).first()
        if member is None:
            return SyncResult.REJECTED.value, "Member does not belong to booking", None
        checkin_id = db.execute(
            pg_insert(AttendanceCheckin)
            .values(
                event_id=ev["event_id"], booking_session_id=bs.id, booking_id=booking.id, member_id=member.id,
                scanner_id=None, source=CheckinSource.OFFLINE_SYNC.value, offline_node_id=node_id,
                checked_in_at=checked_at,
            )
            .on_conflict_do_nothing()
            .returning(AttendanceCheckin.id)
        ).scalar_one_or_none()
        if checkin_id is not None:
            return SyncResult.ACCEPTED.value, None, checkin_id
        existing = db.scalars(
            select(AttendanceCheckin).where(
                AttendanceCheckin.booking_session_id == bs.id, AttendanceCheckin.member_id == member.id
            )
        ).first()
        if existing is not None and existing.event_id == ev["event_id"]:
            return SyncResult.DUPLICATE_EVENT.value, "Event already recorded", existing.id
        if existing is not None:
            return SyncResult.ALREADY_CHECKED_IN.value, "Member already checked in (earliest record kept)", existing.id
        return SyncResult.REJECTED.value, "event_id already used for a different check-in", None


# =========================================================== local side
class LocalNodeService:
    """Runs on the venue local server (OFFLINE_NODE_MODE=true)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def load_snapshot(self, snapshot: dict[str, Any]) -> dict[str, int]:
        session_id = int(snapshot["session"]["session_id"])
        version = str(snapshot["snapshot_version"])

        def work(db: Session) -> dict[str, int]:
            db.execute(delete(OfflineRosterEntry).where(OfflineRosterEntry.session_id == session_id))
            rows = [
                {"session_id": session_id, "booking_number": e["booking_number"], "token_hash": e["token_hash"],
                 "reservation_status": e["reservation_status"], "kund_number": e["kund_number"],
                 "members": e["members"], "snapshot_version": version}
                for e in snapshot["entries"]
            ]
            if rows:
                db.execute(pg_insert(OfflineRosterEntry), rows)
            imported = 0
            for c in snapshot.get("existing_checkins", []):
                res = db.execute(
                    pg_insert(OfflineCheckinEvent)
                    .values(event_id=uuid.UUID(c["event_id"]), session_id=session_id,
                            booking_number=c["booking_number"], member_number=c["member_number"],
                            checked_in_at=datetime.fromisoformat(c["checked_in_at"]), synced_at=clock.now(),
                            sync_result="FROM_CLOUD")
                    .on_conflict_do_nothing()
                    .returning(OfflineCheckinEvent.event_id)
                ).scalar_one_or_none()
                imported += res is not None
            return {"roster_entries": len(rows), "cloud_checkins_imported": imported}

        return run_transaction(self.db, work, label="offline_load")

    def _resolve(
        self, scanner: AdminUser, qr_payload: str | None, booking_number: str | None = None
    ) -> tuple[OfflineRosterEntry | None, dict[str, Any] | None]:
        if scanner.assigned_session_id is None:
            return None, {"status": CheckinResult.INVALID_SESSION, "message": "This scanner is not assigned to a session"}
        session = SessionRepository(self.db).get(scanner.assigned_session_id)
        if session is None or not session_service.checkin_window_open(session):
            return None, {"status": CheckinResult.INVALID_SESSION,
                          "message": "Check-in is not open for the assigned session at this time"}
        if qr_payload is not None:
            match = OfflineRosterEntry.token_hash == security.hash_token(security.token_from_qr_payload(qr_payload))
        else:
            match = OfflineRosterEntry.booking_number == (booking_number or "").strip().upper()
        entry = self.db.scalars(
            select(OfflineRosterEntry).where(OfflineRosterEntry.session_id == session.id, match)
        ).first()
        if entry is None:
            return None, {"status": CheckinResult.INVALID_QR,
                          "message": "QR not found in this session's offline roster"}
        if entry.reservation_status != ReservationStatus.CONFIRMED.value:
            return None, {"status": CheckinResult.BOOKING_CANCELLED, "message": "This reservation was cancelled",
                          "booking_number": entry.booking_number}
        return entry, None

    def _roster(self, entry: OfflineRosterEntry) -> list[dict[str, Any]]:
        done = dict(
            self.db.execute(
                select(OfflineCheckinEvent.member_number, OfflineCheckinEvent.checked_in_at).where(
                    OfflineCheckinEvent.session_id == entry.session_id,
                    OfflineCheckinEvent.booking_number == entry.booking_number,
                )
            ).all()
        )
        return [
            {"member_number": m["member_number"], "full_name": m["full_name"],
             "checked_in": m["member_number"] in done, "checked_in_at": done.get(m["member_number"])}
            for m in entry.members
        ]

    def scan(self, scanner: AdminUser, qr_payload: str | None, booking_number: str | None = None) -> dict[str, Any]:
        entry, error = self._resolve(scanner, qr_payload, booking_number)
        if error:
            return error
        assert entry is not None
        roster = self._roster(entry)
        return {
            "status": CheckinResult.VALID, "message": "Pass valid (offline roster)",
            "booking_number": entry.booking_number, "kund_number": entry.kund_number,
            "member_count": len(entry.members), "checked_in_count": sum(1 for r in roster if r["checked_in"]),
            "roster": roster,
        }

    def checkin(self, scanner: AdminUser, qr_payload: str | None, member_number: int,
                event_id: uuid.UUID | None = None, booking_number: str | None = None) -> dict[str, Any]:
        event_id = event_id or uuid.uuid4()

        def work(db: Session) -> dict[str, Any]:
            entry, error = self._resolve(scanner, qr_payload, booking_number)
            if error:
                return error
            assert entry is not None
            member = next((m for m in entry.members if m["member_number"] == member_number), None)
            base = {"booking_number": entry.booking_number, "kund_number": entry.kund_number,
                    "member_count": len(entry.members), "member_number": member_number}
            if member is None:
                return {**base, "status": CheckinResult.INVALID_MEMBER,
                        "message": "This member does not belong to the scanned family"}
            now = clock.now()
            inserted = db.execute(
                pg_insert(OfflineCheckinEvent)
                .values(event_id=event_id, session_id=entry.session_id, booking_number=entry.booking_number,
                        member_number=member_number, scanner_id=scanner.id, checked_in_at=now)
                .on_conflict_do_nothing()
                .returning(OfflineCheckinEvent.event_id)
            ).scalar_one_or_none()
            existing = None
            if inserted is None:
                existing = db.scalars(
                    select(OfflineCheckinEvent).where(
                        OfflineCheckinEvent.session_id == entry.session_id,
                        OfflineCheckinEvent.booking_number == entry.booking_number,
                        OfflineCheckinEvent.member_number == member_number,
                    )
                ).first()
            roster = self._roster(entry)
            common = {**base, "full_name": member["full_name"],
                      "checked_in_count": sum(1 for r in roster if r["checked_in"])}
            if inserted is not None or (existing is not None and existing.event_id == event_id):
                return {**common, "status": CheckinResult.CHECKIN_SUCCESS,
                        "message": f"Member {member_number} checked in (offline)",
                        "checked_in_at": existing.checked_in_at if existing else now, "event_id": event_id}
            return {**common, "status": CheckinResult.ALREADY_CHECKED_IN,
                    "message": f"Member {member_number} was already checked in for this session",
                    "checked_in_at": existing.checked_in_at if existing else None,
                    "event_id": existing.event_id if existing else None}

        return run_transaction(self.db, work, label="offline_checkin")

    def pending_events(self, limit: int = 500) -> list[OfflineCheckinEvent]:
        return list(
            self.db.scalars(
                select(OfflineCheckinEvent)
                .where(OfflineCheckinEvent.synced_at.is_(None))
                .order_by(OfflineCheckinEvent.created_at)
                .limit(limit)
            )
        )

    def mark_synced(self, results: list[dict[str, Any]]) -> int:
        def work(db: Session) -> int:
            n = 0
            for r in results:
                res = db.execute(
                    update(OfflineCheckinEvent)
                    .where(OfflineCheckinEvent.event_id == uuid.UUID(str(r["event_id"])),
                           OfflineCheckinEvent.synced_at.is_(None))
                    .values(synced_at=clock.now(), sync_result=r["result"], sync_detail=(r.get("detail") or "")[:200])
                )
                n += int(res.rowcount or 0)
            return n

        return run_transaction(self.db, work, label="offline_mark_synced")

    def status(self) -> dict[str, Any]:
        rows = self.db.execute(
            select(OfflineCheckinEvent.session_id, OfflineCheckinEvent.synced_at.is_(None), func.count())
            .group_by(OfflineCheckinEvent.session_id, OfflineCheckinEvent.synced_at.is_(None))
        ).all()
        roster = dict(
            self.db.execute(
                select(OfflineRosterEntry.session_id, func.count()).group_by(OfflineRosterEntry.session_id)
            ).all()
        )
        sessions: dict[int, dict[str, int]] = {}
        for sid, pending, n in rows:
            d = sessions.setdefault(sid, {"pending": 0, "synced": 0})
            d["pending" if pending else "synced"] += n
        return {"roster_entries_by_session": roster, "events_by_session": sessions}
