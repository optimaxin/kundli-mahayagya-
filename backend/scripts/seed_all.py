"""Seed sessions + Kunds + capacity and verify the expected counts. Idempotent.

Usage:  python -m scripts.seed_all
Exit code 1 if the verified counts do not match 16 / 2,151 / 34,416.
"""

from __future__ import annotations

import sys

from app.core.database import get_sessionmaker
from app.services.seed_service import seed_all


def main() -> int:
    with get_sessionmaker()() as db:
        report = seed_all(db)
    print(f"event_sessions        = {report.sessions:>6}  (expected 16)")
    print(f"kunds                 = {report.kunds:>6}  (expected 2151)")
    print(f"kund_session_capacity = {report.capacity_rows:>6}  (expected 34416)")
    print(f"rows with capacity!=8 = {report.capacity_not_eight:>6}  (expected 0)")
    print(f"rows with reserved!=0 = {report.reserved_not_zero:>6}  (0 on a fresh database)")
    if not report.expected_ok:
        print("SEED VERIFICATION FAILED", file=sys.stderr)
        return 1
    print("Seed verification OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
