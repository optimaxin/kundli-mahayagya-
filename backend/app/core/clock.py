"""Single source of "now" for the application.

All business rules that depend on time (booking cut-off, check-in windows,
no-show calculation, QR expiry) read the time through :func:`now` so that tests
can freeze the clock deterministically.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import get_settings

_frozen: datetime | None = None


def now() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    if _frozen is not None:
        return _frozen
    return datetime.now(UTC)


def freeze(at: datetime | None) -> None:
    """Freeze the clock (tests only). Pass ``None`` to unfreeze."""
    global _frozen
    if at is not None and at.tzinfo is None:
        raise ValueError("frozen time must be timezone-aware")
    _frozen = at.astimezone(UTC) if at is not None else None


def event_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().EVENT_TIMEZONE)


def local_datetime(d: date, t: time) -> datetime:
    """Combine an event-local date and time into an aware UTC datetime."""
    return datetime.combine(d, t, tzinfo=event_tz()).astimezone(UTC)


def today_local() -> date:
    return now().astimezone(event_tz()).date()
