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
