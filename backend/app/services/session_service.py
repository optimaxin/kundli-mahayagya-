"""Time-based rules for sessions (booking cut-off, check-in window, completion)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core import clock
from app.core.config import get_settings
from app.models import EventSession
from app.models.enums import EventSessionStatus


def starts_at(session: EventSession) -> datetime:
    return clock.local_datetime(session.event_date, session.start_time)


def ends_at(session: EventSession) -> datetime:
    return clock.local_datetime(session.event_date, session.end_time)


def booking_block_reason(session: EventSession, now: datetime | None = None) -> str | None:
    """Return why this session cannot be booked right now, or None if bookable."""
    now = now or clock.now()
    if not session.is_active:
        return "Session is not active"
    if session.status != EventSessionStatus.SCHEDULED.value:
        return f"Session is {session.status.lower()} for booking"
    cutoff = starts_at(session) - timedelta(minutes=get_settings().BOOKING_CUTOFF_MINUTES)
    if now >= cutoff:
        return "Booking for this session has closed"
    return None


MAX_FAMILY_SIZE = 8

# Public, family-specific availability states. They deliberately carry no numbers: the public site
# must not learn how many places are left, only whether THIS family can be seated together.
AVAILABLE = "AVAILABLE"  # at least one Kund can hold the whole family
NOT_FOR_THIS_FAMILY = "NOT_FOR_THIS_FAMILY"  # places remain, but no single Kund fits this family
FULL = "FULL"  # no Kund has even one free place: no family of any valid size can book
CLOSED = "CLOSED"  # not open for booking (inactive, closed, past the cut-off)


def family_availability(*, booking_open: bool, largest_free_block: int, family_size: int) -> str:
    """Classify one session for one family size.

    ``largest_free_block`` is the most free places in any single usable Kund of the session. A family
    fits only if one Kund can take ALL its members, so the total number of free places is irrelevant:
    a Kund with one place left is eligible for a family of 1 but not for a family of 2, and is never
    treated as "full" while it can still take a smaller family.

    Informational only. The authoritative check is the locked best-fit allocation at booking time.
    """
    if not 1 <= family_size <= MAX_FAMILY_SIZE:
        raise ValueError("family_size must be between 1 and 8")
    if not booking_open:
        return CLOSED
    if largest_free_block <= 0:
        return FULL
    if largest_free_block < family_size:
        return NOT_FOR_THIS_FAMILY
    return AVAILABLE


def checkin_window_open(session: EventSession, now: datetime | None = None) -> bool:
    settings = get_settings()
    if not settings.ENFORCE_CHECKIN_WINDOW:
        return True
    now = now or clock.now()
    opens = starts_at(session) - timedelta(minutes=settings.CHECKIN_OPENS_MINUTES_BEFORE)
    closes = ends_at(session) + timedelta(minutes=settings.CHECKIN_CLOSES_MINUTES_AFTER)
    return opens <= now <= closes


def is_completed(session: EventSession, now: datetime | None = None) -> bool:
    """A session is complete only once its scheduled end time has passed.

    No-shows are computed only for completed sessions. (An admin marking a
    session COMPLETED early does not make no-shows computable early.)
    """
    now = now or clock.now()
    return now >= ends_at(session)


def last_event_day_end() -> datetime:
    s = get_settings()
    last_day = s.EVENT_START_DATE + timedelta(days=s.EVENT_DAYS - 1)
    return clock.local_datetime(last_day, s.AFTERNOON_END)
