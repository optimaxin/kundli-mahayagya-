from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    SCANNER = "SCANNER"


class SessionSlot(StrEnum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


class EventSessionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"  # open for booking (subject to cut-off)
    CLOSED = "CLOSED"  # booking manually closed
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ReservationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class CheckinSource(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE_SYNC = "OFFLINE_SYNC"


class CheckinResult(StrEnum):
    CHECKIN_SUCCESS = "CHECKIN_SUCCESS"
    ALREADY_CHECKED_IN = "ALREADY_CHECKED_IN"
    INVALID_QR = "INVALID_QR"
    INVALID_SESSION = "INVALID_SESSION"
    INVALID_MEMBER = "INVALID_MEMBER"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    VALID = "VALID"  # successful scan (roster returned), no check-in yet


class ReportType(StrEnum):
    DAILY = "DAILY"
    FINAL = "FINAL"


class ReportStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SyncResult(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    ALREADY_CHECKED_IN = "ALREADY_CHECKED_IN"
    REJECTED = "REJECTED"


def sql_in(enum_cls: type[StrEnum]) -> str:
    """Render ``('A', 'B')`` for CHECK constraints."""
    return "(" + ", ".join(f"'{m.value}'" for m in enum_cls) + ")"
