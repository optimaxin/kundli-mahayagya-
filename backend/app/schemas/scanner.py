from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _PassRef(BaseModel):
    """A pass is identified by its QR payload (normal) OR by the printed booking
    number (manual fallback when the camera fails). Exactly one is required."""

    model_config = ConfigDict(extra="forbid")
    qr_payload: str | None = Field(None, min_length=20, max_length=200)
    booking_number: str | None = Field(None, min_length=6, max_length=20)
    session_id: int | None = Field(
        None, ge=1, le=16,
        description="ADMIN/SUPERVISOR only (required for them). SCANNER accounts must NOT send it: "
        "their session comes from the account.",
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> _PassRef:
        if (self.qr_payload is None) == (self.booking_number is None):
            raise ValueError("Provide exactly one of qr_payload or booking_number")
        return self


class ScanIn(_PassRef):
    pass


class CheckinIn(_PassRef):
    member_number: int = Field(..., ge=1, le=8)
    event_id: uuid.UUID | None = Field(
        None, description="Client-generated id; re-sending the same id is idempotent"
    )


class ManualCheckinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: int = Field(..., ge=1, le=16)
    member_numbers: list[int] | None = Field(None, description="Omit to mark every member present")


class RosterMemberOut(BaseModel):
    member_number: int
    full_name: str
    age: int | None = None
    gender: str | None = None
    checked_in: bool
    checked_in_at: datetime | None


class ScannerSessionOut(BaseModel):
    session_id: int
    event_date: date
    slot: str
    start_time: time
    end_time: time


class BookedSessionOut(BaseModel):
    session_id: int
    event_date: date
    slot: str
    status: str


class ScanResultOut(BaseModel):
    status: str = Field(..., description="VALID | INVALID_QR | INVALID_SESSION | BOOKING_CANCELLED")
    reason: str | None = Field(
        None,
        description="SCANNER_UNASSIGNED | SESSION_INACTIVE | UNKNOWN_PASS | PASS_REVOKED | BOOKING_CANCELLED | "
        "RESERVATION_CANCELLED | NO_RESERVATION | SESSION_NOT_OPEN | SESSION_OVER | ALL_CHECKED_IN",
    )
    message: str
    session: ScannerSessionOut | None = None
    booking_number: str | None = None
    coordinator_name: str | None = None
    primary_mobile_masked: str | None = None
    kund_number: int | None = None
    member_count: int | None = None
    checked_in_count: int | None = None
    roster: list[RosterMemberOut] | None = None
    booked_sessions: list[BookedSessionOut] | None = None


class CheckinResultOut(BaseModel):
    status: str = Field(
        ...,
        description="CHECKIN_SUCCESS | ALREADY_CHECKED_IN | INVALID_QR | INVALID_SESSION | "
        "INVALID_MEMBER | BOOKING_CANCELLED",
    )
    reason: str | None = None
    message: str
    booking_number: str | None = None
    kund_number: int | None = None
    member_number: int | None = None
    full_name: str | None = None
    checked_in_at: datetime | None = None
    event_id: uuid.UUID | None = None
    checked_in_count: int | None = None
    member_count: int | None = None


class ScannerMeOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    role: str
    session: ScannerSessionOut | None
    checkin_window_open: bool
