"""QR passes, attendance, staff users, idempotency, audit, cancellations, reports."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, updated_at_column
from app.models.enums import (
    CheckinSource,
    IdempotencyStatus,
    ReportStatus,
    ReportType,
    Role,
    sql_in,
)


class QrPass(Base):
    __tablename__ = "qr_passes"
    __table_args__ = (
        CheckConstraint("char_length(token_hash) = 64", name="token_hash_sha256"),
        # At most one ACTIVE pass per family booking.
        Index(
            "uq_qr_passes_one_active_per_booking",
            "booking_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_qr_passes_booking", "booking_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_qr_passes_booking"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revoked_reason: Mapped[str | None] = mapped_column(String(200))


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(f"role IN {sql_in(Role)}", name="role_valid"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("ix_admin_users_role", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("event_sessions.id", name="fk_admin_users_assigned_session")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class AttendanceCheckin(Base):
    """One row per family member per reserved session. Never one row per family."""

    __tablename__ = "attendance_checkins"
    __table_args__ = (
        UniqueConstraint("booking_session_id", "member_id", name="uq_attendance_checkins_session_member"),
        CheckConstraint(f"source IN {sql_in(CheckinSource)}", name="source_valid"),
        # The reservation must belong to the same booking...
        ForeignKeyConstraint(
            ["booking_session_id", "booking_id"],
            ["booking_sessions.id", "booking_sessions.booking_id"],
            name="fk_attendance_checkins_booking_session",
        ),
        # ...and so must the member.
        ForeignKeyConstraint(
            ["member_id", "booking_id"],
            ["family_members.id", "family_members.booking_id"],
            name="fk_attendance_checkins_member",
        ),
        Index("ix_attendance_checkins_booking", "booking_id"),
        Index("ix_attendance_checkins_checked_in_at", "checked_in_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    booking_session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    booking_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_attendance_checkins_scanner")
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{CheckinSource.ONLINE.value}'")
    )
    offline_node_id: Mapped[str | None] = mapped_column(String(64))
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = created_at_column()


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_records_scope_key"),
        CheckConstraint(f"status IN {sql_in(IdempotencyStatus)}", name="status_valid"),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Short-lived encrypted secret needed to replay the response (the raw QR token);
    # cleared by the purge job after IDEMPOTENCY_TTL_HOURS.
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    """Append-only (UPDATE/DELETE blocked by trigger)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor", "actor_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_role: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    previous_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


class CancellationEvent(Base):
    """Append-only. UNIQUE(booking_session_id) makes a reservation cancellable exactly once."""

    __tablename__ = "cancellation_events"
    __table_args__ = (
        UniqueConstraint("booking_session_id", name="uq_cancellation_events_booking_session"),
        Index("ix_cancellation_events_booking", "booking_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("booking_sessions.id", name="fk_cancellation_events_booking_session"), nullable=False
    )
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_cancellation_events_booking"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kund_id: Mapped[int] = mapped_column(Integer, nullable=False)
    released_member_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_cancellation_events_actor")
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class ReportJob(Base):
    __tablename__ = "report_jobs"
    __table_args__ = (
        CheckConstraint(f"report_type IN {sql_in(ReportType)}", name="type_valid"),
        CheckConstraint(f"status IN {sql_in(ReportStatus)}", name="status_valid"),
        Index("ix_report_jobs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    report_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_report_jobs_requested_by")
    )
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
