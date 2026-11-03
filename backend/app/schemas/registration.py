from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.utils import validators as v


class CoordinatorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., examples=["Rahul Sharma"])
    primary_mobile: str = Field(..., examples=["9876543210"])
    secondary_mobile: str | None = Field(None, examples=[""])
    email: EmailStr | None = Field(None, examples=["rahul@example.com"])
    address: str | None = Field(None, examples=["12 Civil Lines"])
    city: str = Field(..., examples=["Agra"])
    state: str = Field(..., examples=["Uttar Pradesh"])
    pincode: str | None = Field(None, examples=["282001"])
    gotra: str | None = Field(None, examples=["Bharadwaj"])
    sankalp_purpose: str | None = Field(None, examples=["Family wellbeing"])

    @field_validator("address", "pincode", "gotra", "sankalp_purpose", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return v.validate_person_name(value, field="Coordinator name")

    @field_validator("primary_mobile")
    @classmethod
    def _primary_mobile(cls, value: str) -> str:
        return v.normalize_mobile(value, field="Primary mobile")

    @field_validator("secondary_mobile", mode="before")
    @classmethod
    def _secondary_mobile(cls, value: Any) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return v.normalize_mobile(str(value), field="Secondary mobile")

    @field_validator("email", mode="before")
    @classmethod
    def _email_blank(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("address")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_free_text(value, field="Address", min_len=3, max_len=300)

    @field_validator("city")
    @classmethod
    def _city(cls, value: str) -> str:
        return v.validate_person_name(value, field="City")

    @field_validator("state")
    @classmethod
    def _state(cls, value: str) -> str:
        return v.canonical_state(value)

    @field_validator("pincode")
    @classmethod
    def _pincode(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_pincode(value)

    @field_validator("gotra")
    @classmethod
    def _gotra(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_person_name(value, field="Gotra")

    @field_validator("sankalp_purpose")
    @classmethod
    def _sankalp(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_free_text(value, field="Sankalp purpose", min_len=2, max_len=500)

    @model_validator(mode="after")
    def _distinct_mobiles(self) -> CoordinatorIn:
        if self.secondary_mobile and self.secondary_mobile == self.primary_mobile:
            raise ValueError("Secondary mobile must be different from the primary mobile")
        return self


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(..., examples=["Priya Sharma"])
    age: int = Field(..., ge=1, le=110, examples=[34])
    gender: Literal["male", "female", "other"] = Field(..., examples=["female"])
    relationship: str | None = Field(None, examples=["Spouse"], description="Self, Spouse, Parent, Child, ...")
    mobile: str | None = Field(None, examples=[""])

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return v.validate_person_name(value, field="Member name")

    @field_validator("relationship", mode="before")
    @classmethod
    def _relationship(cls, value: Any) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        value = v.clean_text(str(value))
        if len(value) > 30 or not all(ch.isalpha() or ch in " /-" for ch in value):
            raise ValueError("Relationship must be up to 30 letters")
        return value

    @field_validator("mobile", mode="before")
    @classmethod
    def _mobile(cls, value: Any) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return v.normalize_mobile(str(value), field="Member mobile")


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "coordinator": {
                    "name": "Rahul Sharma",
                    "primary_mobile": "9876543210",
                    "secondary_mobile": "",
                    "email": "rahul@example.com",
                    "address": "12 Civil Lines",
                    "city": "Agra",
                    "state": "Uttar Pradesh",
                    "pincode": "282001",
                    "gotra": "Bharadwaj",
                    "sankalp_purpose": "Family wellbeing",
                },
                "members": [
                    {"full_name": "Rahul Sharma", "age": 38, "gender": "male", "relationship": "Self"},
                    {"full_name": "Priya Sharma", "age": 35, "gender": "female", "relationship": "Spouse"},
                ],
                "selected_sessions": [1, 2, 3],
            }
        },
    )

    coordinator: CoordinatorIn
    members: list[MemberIn]
    selected_sessions: list[int]

    @field_validator("members")
    @classmethod
    def _members(cls, value: list[MemberIn]) -> list[MemberIn]:
        if not value:
            raise ValueError("At least 1 family member is required")
        if len(value) > 8:
            raise ValueError("A family can register at most 8 members")
        seen: set[str] = set()
        for m in value:
            key = m.full_name.casefold()
            if key in seen:
                raise ValueError("Each family member must be listed only once (duplicate name)")
            seen.add(key)
        return value

    @field_validator("selected_sessions")
    @classmethod
    def _sessions(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("Select at least one session")
        if len(value) != len(set(value)):
            raise ValueError("Each session may be selected only once")
        if len(value) > 16:
            raise ValueError("At most 16 sessions can be selected")
        if any(s < 1 for s in value):
            raise ValueError("Session ids must be positive integers")
        return sorted(value)


# ------------------------------------------------------------------- output
class MemberOut(BaseModel):
    member_number: int
    full_name: str
    age: int | None = None
    gender: str | None = None
    relationship: str | None = None


class ReservationOut(BaseModel):
    session_id: int
    event_date: date
    slot: str
    start_time: time
    end_time: time
    kund_number: int
    member_count: int
    status: str


class QrPassOut(BaseModel):
    token: str | None = Field(
        None, description="Opaque pass token. Shown ONLY in this response; store it or the QR image safely."
    )
    qr_payload: str | None = Field(None, description="Exact text to encode in the QR code (no personal data).")
    expires_at: datetime
    image_endpoint: str = Field(..., description="POST the token here to download the QR image (PNG/SVG).")
    note: str | None = None


class RegistrationOut(BaseModel):
    booking_number: str
    status: str
    coordinator_name: str
    primary_mobile_masked: str
    member_count: int
    members: list[MemberOut]
    reservations: list[ReservationOut]
    qr_pass: QrPassOut
    created_at: datetime
