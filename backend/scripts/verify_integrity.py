"""Reconcile capacity and booking invariants (read-only). Exit 1 on any mismatch.

Usage:  python -m scripts.verify_integrity
"""

from __future__ import annotations

import json

from app.core.database import get_sessionmaker
from app.services.admin_service import AdminService
from app.services.seed_service import verify_seed


def main() -> int:
    with get_sessionmaker()() as db:
        seed = verify_seed(db)
        report = AdminService(db).integrity_report()
    report["seed"] = seed.__dict__
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] and seed.expected_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
