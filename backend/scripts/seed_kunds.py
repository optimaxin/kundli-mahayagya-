"""Seed the 2,151 Kunds and their per-session capacity rows (capacity=8, reserved=0). Idempotent.

Run after (or before) seed_sessions; capacity rows are created for every
existing (session, kund) pair either way.

Usage:  python -m scripts.seed_kunds
"""

from __future__ import annotations

from app.core.database import get_sessionmaker
from app.services.seed_service import seed_kunds, verify_seed


def main() -> None:
    with get_sessionmaker()() as db:
        created_capacity = seed_kunds(db)
        db.commit()
        report = verify_seed(db)
    print(f"kunds={report.kunds} (expected 2151)")
    print(f"capacity rows created now={created_capacity}, total={report.capacity_rows} (expected 34416)")


if __name__ == "__main__":
    main()
