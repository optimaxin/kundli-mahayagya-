from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, updated_at_column
from app.models.enums import EventSessionStatus, SessionSlot, sql_in


class EventSession(Base):
    """One of the 16 sessions (8 days x MORNING/AFTERNOON)."""

    __tablename__ = "event_sessions"
    __table_args__ = (
        UniqueConstraint("event_date", "slot", name="uq_event_sessions_date_slot"),
        CheckConstraint(f"slot IN {sql_in(SessionSlot)}", name="slot_valid"),
        CheckConstraint(f"status IN {sql_in(EventSessionStatus)}", name="status_valid"),
        CheckConstraint("end_time > start_time", name="time_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(10), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{EventSessionStatus.SCHEDULED.value}'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Kund(Base):
    __tablename__ = "kunds"
    __table_args__ = (CheckConstraint("kund_number > 0", name="kund_number_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    kund_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()


class KundSessionCapacity(Base):
    """Capacity of one Kund in one session. reserved_count is maintained ONLY by
    database triggers on booking_sessions (see migration 0002)."""

    __tablename__ = "kund_session_capacity"
    __table_args__ = (
        CheckConstraint("capacity BETWEEN 1 AND 8", name="capacity_range"),
        CheckConstraint("reserved_count >= 0 AND reserved_count <= capacity", name="reserved_within_capacity"),
        # Best-fit lookup: among Kunds that still have room, the one with the
        # FEWEST free seats that can still hold the whole family comes first.
        Index(
            "ix_ksc_best_fit",
            "session_id",
            text("(capacity - reserved_count)"),
            "kund_id",
            postgresql_where=text("reserved_count < capacity"),
        ),
        Index("ix_ksc_kund", "kund_id"),
    )

    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("event_sessions.id", name="fk_ksc_session"), primary_key=True
    )
    kund_id: Mapped[int] = mapped_column(Integer, ForeignKey("kunds.id", name="fk_ksc_kund"), primary_key=True)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("8"))
    reserved_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    # Per-session block set by organisers (only on an empty Kund); excluded from allocation.
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
