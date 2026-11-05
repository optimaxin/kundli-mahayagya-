from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.security import validate_password_strength
from app.models.enums import Role
from app.utils import validators as v


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - not a secret
    expires_at: datetime
    role: str


class StaffUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    email: str
    role: str
    assigned_session_id: int | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=256)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, value: str) -> str:
        validate_password_strength(value)
        return value


class StaffPasswordReset(BaseModel):
    """ADMIN sets a new password for a SCANNER/SUPERVISOR account (e.g. a volunteer forgot theirs)."""

    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(..., max_length=256)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, value: str) -> str:
        validate_password_strength(value)
        return value


class StaffUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str
    email: EmailStr
    password: str = Field(..., max_length=256)
    role: Role
    assigned_session_id: int | None = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return v.validate_person_name(value, field="Full name")

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        validate_password_strength(value)
        return value

    @model_validator(mode="after")
    def _scanner_session(self) -> StaffUserCreate:
        if self.role != Role.SCANNER and self.assigned_session_id is not None:
            raise ValueError("Only SCANNER accounts can be assigned to a session")
        return self


class StaffUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = None
    is_active: bool | None = None
    assigned_session_id: int | None = Field(None, description="Set for SCANNER accounts")
    clear_assigned_session: bool = False

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_person_name(value, field="Full name")
