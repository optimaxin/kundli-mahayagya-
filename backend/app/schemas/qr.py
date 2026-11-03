from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils import validators as v
from app.utils.identifiers import normalize_booking_number


class PassTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=20, max_length=200, description="Pass token or full QR payload")


class PassImageIn(PassTokenIn):
    format: Literal["png", "svg"] = "png"
    scale: int = Field(8, ge=2, le=20)


class PassMemberOut(BaseModel):
    member_number: int
    full_name: str


class PassReservationOut(BaseModel):
    session_id: int
    event_date: date
    slot: str
    start_time: time
    end_time: time
    kund_number: int
    status: str
    checked_in_count: int
    first_checked_in_at: datetime | None


class PassOut(BaseModel):
    booking_number: str
    booking_status: str
    coordinator_name: str
    primary_mobile_masked: str
    city: str
    pass_active: bool
    expires_at: datetime
    qr_payload: str
    created_at: datetime
    member_count: int
    members: list[PassMemberOut]
    reservations: list[PassReservationOut]


class PassStatusLookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_number: str = Field(..., max_length=20)
    primary_mobile: str

    @field_validator("booking_number")
    @classmethod
    def _bn(cls, value: str) -> str:
        return normalize_booking_number(value)

    @field_validator("primary_mobile")
    @classmethod
    def _mobile(cls, value: str) -> str:
        return v.normalize_mobile(value, field="Primary mobile")


class PassStatusOut(BaseModel):
    booking_number: str
    booking_status: str
    pass_active: bool
    member_count: int
    confirmed_sessions: int


class PassIssuedOut(BaseModel):
    booking_number: str
    token: str
    qr_payload: str
    expires_at: datetime
    note: str = "Shown once. The previous pass for this booking has been revoked."


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return v.validate_free_text(value, field="Reason", min_len=3, max_len=200)
