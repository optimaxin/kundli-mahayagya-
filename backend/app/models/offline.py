"""Tables for offline venue check-in.

* ``offline_roster_entries`` and ``offline_checkin_events`` are used on the
  venue LOCAL server (OFFLINE_NODE_MODE=true). They exist in every deployment
  (same migrations everywhere) but stay empty in the cloud.
* ``offline_sync_receipts`` is used in the CLOUD to make event ingestion
  idempotent: re-sending the same event_id returns the original outcome.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column


class OfflineRosterEntry(Base):
    __tablename__ = "offline_roster_entries"
    __table_args__ = (
        UniqueConstraint("session_id", "token_hash", name="uq_offline_roster_session_token"),
        UniqueConstraint("session_id", "booking_number", name="uq_offline_roster_session_booking"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    booking_number: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reservation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    kund_number: Mapped[int] = mapped_column(Integer, nullable=False)
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(64), nullable=False)
    loaded_at: Mapped[datetime] = created_at_column()


class OfflineCheckinEvent(Base):
    __tablename__ = "offline_checkin_events"
    __table_args__ = (
        # LAN-wide duplicate prevention while the venue is offline.
        UniqueConstraint(
            "session_id", "booking_number", "member_number", name="uq_offline_checkin_session_booking_member"
        ),
        Index("ix_offline_checkin_events_unsynced", "synced_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    booking_number: Mapped[str] = mapped_column(String(20), nullable=False)
    member_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scanner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_result: Mapped[str | None] = mapped_column(String(32))
    sync_detail: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()


class OfflineSyncReceipt(Base):
    __tablename__ = "offline_sync_receipts"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(200))
    checkin_id: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = created_at_column()
