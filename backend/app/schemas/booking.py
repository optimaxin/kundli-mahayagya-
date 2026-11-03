from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.registration import MemberOut
from app.utils import validators as v


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_date: date
    slot: str
    start_time: time
    end_time: time
    status: str
    is_active: bool


class SessionAvailabilityOut(SessionOut):
    total_capacity: int
    reserved: int
    remaining: int
    kunds_empty: int
    kunds_full: int
    kunds_blocked: int = 0
    largest_family_bookable: int = Field(..., description="Largest family size that still fits in one Kund")
    booking_open: bool


class BookingReservationOut(BaseModel):
    booking_session_id: int
    session_id: int
    event_date: date
    slot: str
    kund_number: int
    member_count: int
    status: str
    created_at: datetime
    cancelled_at: datetime | None
    checked_in_count: int
    first_checked_in_at: datetime | None = None
    checked_in_by: str | None = None


class BookingSummaryOut(BaseModel):
    booking_number: str
    coordinator_name: str
    primary_mobile_masked: str
    city: str
    state: str
    member_count: int
    status: str
    session_count: int
    created_at: datetime


class BookingDetailOut(BaseModel):
    booking_number: str
    status: str
    coordinator_name: str
    primary_mobile: str
    secondary_mobile: str | None
    email: str | None
    address: str | None
    city: str
    state: str
    pincode: str | None
    gotra: str | None
    sankalp_purpose: str | None
    member_count: int
    members: list[MemberOut]
    reservations: list[BookingReservationOut]
    qr_pass_active: bool
    qr_pass_expires_at: datetime | None
    created_at: datetime
    cancelled_at: datetime | None


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., examples=["Family requested cancellation"])
    session_ids: list[int] | None = Field(
        None, description="Cancel only these sessions; omit to cancel every session of the booking"
    )

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return v.validate_free_text(value, field="Reason", min_len=3, max_len=500)

    @field_validator("session_ids")
    @classmethod
    def _sessions(cls, value: list[int] | None) -> list[int] | None:
        if value is not None:
            if not value:
                raise ValueError("session_ids must not be empty when provided")
            if len(value) != len(set(value)):
                raise ValueError("session_ids must be unique")
        return value


class CancelledReservationOut(BaseModel):
    session_id: int
    kund_number: int
    released_member_count: int


class CancelOut(BaseModel):
    booking_number: str
    booking_status: str
    already_cancelled: bool
    cancelled: list[CancelledReservationOut]
    released_capacity: int
    remaining_confirmed_sessions: int


class CheckinOut(BaseModel):
    event_id: uuid.UUID
    booking_number: str
    session_id: int
    member_number: int
    full_name: str
    kund_number: int
    checked_in_at: datetime
    source: str
    scanner_id: uuid.UUID | None


class FamilyMemberOut(BaseModel):
    booking_number: str
    member_number: int
    full_name: str
    age: int | None = None
    gender: str | None = None
    relationship: str | None = None
    booking_status: str
