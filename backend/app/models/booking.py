from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, updated_at_column
from app.models.enums import BookingStatus, ReservationStatus, sql_in


class Booking(Base):
    """A family booking. One booking = one family = one QR pass."""

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("member_count BETWEEN 1 AND 8", name="member_count_range"),
        CheckConstraint(f"status IN {sql_in(BookingStatus)}", name="status_valid"),
        CheckConstraint("primary_mobile ~ '^[6-9][0-9]{9}$'", name="primary_mobile_format"),
        CheckConstraint(
            "secondary_mobile IS NULL OR secondary_mobile ~ '^[6-9][0-9]{9}$'", name="secondary_mobile_format"
        ),
        CheckConstraint("pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'", name="pincode_format"),
        # Target of the composite FK that pins booking_sessions.member_count to the family size.
        UniqueConstraint("id", "member_count", name="uq_bookings_id_member_count"),
        Index("ix_bookings_primary_mobile", "primary_mobile"),
        Index("ix_bookings_created_at", "created_at"),
        Index("ix_bookings_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    coordinator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    primary_mobile: Mapped[str] = mapped_column(String(10), nullable=False)
    secondary_mobile: Mapped[str | None] = mapped_column(String(10))
    email: Mapped[str | None] = mapped_column(String(254))
    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(60), nullable=False)
    pincode: Mapped[str | None] = mapped_column(String(6))
    gotra: Mapped[str | None] = mapped_column(String(60))
    sankalp_purpose: Mapped[str | None] = mapped_column(String(500))
    member_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{BookingStatus.CONFIRMED.value}'")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    members: Mapped[list[FamilyMember]] = relationship(
        back_populates="booking", order_by="FamilyMember.member_number", lazy="selectin"
    )
    sessions: Mapped[list[BookingSession]] = relationship(
        back_populates="booking", order_by="BookingSession.session_id", lazy="selectin",
        foreign_keys="BookingSession.booking_id",
        primaryjoin="Booking.id == BookingSession.booking_id",
    )


class FamilyMember(Base):
    __tablename__ = "family_members"
    __table_args__ = (
        CheckConstraint("member_number BETWEEN 1 AND 8", name="member_number_range"),
        CheckConstraint("age IS NULL OR age BETWEEN 1 AND 110", name="age_range"),
        CheckConstraint("gender IS NULL OR gender IN ('male', 'female', 'other')", name="gender_valid"),
        CheckConstraint("mobile IS NULL OR mobile ~ '^[6-9][0-9]{9}$'", name="mobile_format"),
        UniqueConstraint("booking_id", "member_number", name="uq_family_members_booking_member_number"),
        # Target of the composite FK that guarantees a checked-in member belongs to the booking.
        UniqueConstraint("id", "booking_id", name="uq_family_members_id_booking"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_family_members_booking"), nullable=False
    )
    member_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[int | None] = mapped_column(SmallInteger)
    gender: Mapped[str | None] = mapped_column(String(10))
    relationship_: Mapped[str | None] = mapped_column("relationship", String(30))
    mobile: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = created_at_column()

    booking: Mapped[Booking] = relationship(back_populates="members")


class BookingSession(Base):
    """A family's reservation of exactly one Kund in one session."""

    __tablename__ = "booking_sessions"
    __table_args__ = (
        CheckConstraint("member_count BETWEEN 1 AND 8", name="member_count_range"),
        CheckConstraint(f"status IN {sql_in(ReservationStatus)}", name="status_valid"),
        UniqueConstraint("booking_id", "session_id", name="uq_booking_sessions_booking_session"),
        UniqueConstraint("id", "booking_id", name="uq_booking_sessions_id_booking"),
        ForeignKeyConstraint(
            ["booking_id", "member_count"],
            ["bookings.id", "bookings.member_count"],
            name="fk_booking_sessions_booking_member_count",
        ),
        ForeignKeyConstraint(
            ["session_id", "kund_id"],
            ["kund_session_capacity.session_id", "kund_session_capacity.kund_id"],
            name="fk_booking_sessions_capacity",
        ),
        Index("ix_booking_sessions_session_kund", "session_id", "kund_id"),
        Index("ix_booking_sessions_session_status", "session_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_sessions_booking"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("event_sessions.id", name="fk_booking_sessions_session"), nullable=False
    )
    kund_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kunds.id", name="fk_booking_sessions_kund"), nullable=False
    )
    member_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{ReservationStatus.CONFIRMED.value}'")
    )
    created_at: Mapped[datetime] = created_at_column()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    booking: Mapped[Booking] = relationship(
        back_populates="sessions", foreign_keys=[booking_id], primaryjoin="Booking.id == BookingSession.booking_id"
    )
