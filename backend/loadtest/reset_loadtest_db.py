"""Reset booking data between load-test runs. NEVER run against production.

Guarded: refuses unless LOADTEST_ALLOW_RESET=yes and APP_ENV != production.
Usage:  LOADTEST_ALLOW_RESET=yes python -m loadtest.reset_loadtest_db
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_sessionmaker

TABLES = (
    "attendance_checkins, cancellation_events, qr_passes, booking_sessions, family_members, bookings, "
    "idempotency_records, audit_logs, report_jobs, offline_checkin_events, offline_roster_entries, "
    "offline_sync_receipts"
)


def main() -> int:
    if os.environ.get("LOADTEST_ALLOW_RESET") != "yes" or get_settings().is_production:
        print("Refusing: set LOADTEST_ALLOW_RESET=yes and use a non-production database.", file=sys.stderr)
        return 2
    with get_sessionmaker()() as db:
        db.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        db.execute(text("SELECT set_config('mahayagya.capacity_admin', 'on', true)"))
        db.execute(text("UPDATE kund_session_capacity SET reserved_count = 0 WHERE reserved_count <> 0"))
        db.commit()
    print("Load-test data reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
