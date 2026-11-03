"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.base import Base
from app.models.booking import Booking, BookingSession, FamilyMember
from app.models.event import EventSession, Kund, KundSessionCapacity
from app.models.offline import OfflineCheckinEvent, OfflineRosterEntry, OfflineSyncReceipt
from app.models.operations import (
    AdminUser,
    AttendanceCheckin,
    AuditLog,
    CancellationEvent,
    IdempotencyRecord,
    QrPass,
    ReportJob,
)

__all__ = [
    "AdminUser",
    "AttendanceCheckin",
    "AuditLog",
    "Base",
    "Booking",
    "BookingSession",
    "CancellationEvent",
    "EventSession",
    "FamilyMember",
    "IdempotencyRecord",
    "Kund",
    "KundSessionCapacity",
    "OfflineCheckinEvent",
    "OfflineRosterEntry",
    "OfflineSyncReceipt",
    "QrPass",
    "ReportJob",
]
