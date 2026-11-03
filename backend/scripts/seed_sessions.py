"""Seed the 16 event sessions (8 days x MORNING/AFTERNOON). Idempotent.

Usage:  python -m scripts.seed_sessions
"""

from __future__ import annotations

from app.core.database import get_sessionmaker
from app.services.seed_service import seed_sessions, verify_seed


def main() -> None:
    with get_sessionmaker()() as db:
        created_capacity = seed_sessions(db)
        db.commit()
        report = verify_seed(db)
    print(f"event_sessions={report.sessions} (expected 16)")
    print(f"capacity rows created now={created_capacity}, total={report.capacity_rows}")


if __name__ == "__main__":
    main()
