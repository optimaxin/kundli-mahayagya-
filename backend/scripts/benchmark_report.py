"""Benchmark the Excel report generator (stage timings, workbook size, peak memory).

Safety
* Synthetic data is written ONLY to a local scratch database (host localhost / 127.0.0.1 /
  host.docker.internal / db) and is refused for anything else, including Supabase.
* ``--scenario none`` writes nothing: it only READS the configured database (the transaction is
  forced read-only), so it can be pointed at a real database to time the report on real data.
* No personal data is printed: only stage names, seconds and row counts.

Usage (from backend/, with DATABASE_URL pointing at a scratch DB for seeding scenarios):
    python -m scripts.benchmark_report --scenario full --kind full --runs 2 --after-event
    python -m scripts.benchmark_report --scenario none --kind daily --date 2026-12-14   # read-only

Scenarios (families of 4 members, each booking 2 sessions on different days):
    empty   no bookings (only the 16 sessions x 2,151 Kunds)
    small   8 x 100 families      (~800 families)
    medium  8 x 1,000 families    (~8,000 families)
    full    8 x 4,302 families    (every Kund-session full: 34,416 families, 275,328 attendee rows)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core import clock
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.services.reporting_service import ReportingService, StageTimer

PER_PAIR = {"empty": 0, "small": 100, "medium": 1000, "full": 4302}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal", "db"}
AFTER_EVENT = datetime(2026, 12, 22, 12, 0, tzinfo=UTC)

TRUNCATE = (
    "attendance_checkins, cancellation_events, qr_passes, booking_sessions, family_members, bookings, "
    "idempotency_records, audit_logs, report_jobs"
)

SEED_SQL = """
CREATE TEMP TABLE _pairs(p int, s1 int, s2 int) ON COMMIT DROP;
INSERT INTO _pairs VALUES (0,1,3),(1,5,7),(2,9,11),(3,13,15),(4,2,4),(5,6,8),(6,10,12),(7,14,16);

INSERT INTO bookings (id, booking_number, coordinator_name, primary_mobile, address, city, state, pincode, gotra,
                      sankalp_purpose, member_count, status)
SELECT f, 'MY26-' || upper(lpad(to_hex(f), 8, '0')), 'Bench Family ' || f, '9' || lpad(f::text, 9, '0'),
       'Bench Street', 'Agra', 'Uttar Pradesh', '282001', 'Kashyap', 'Benchmark', 4, 'CONFIRMED'
FROM generate_series(1, :n) f;

INSERT INTO family_members (booking_id, member_number, full_name, age, gender, relationship)
SELECT f, m, 'Bench Member ' || f || '-' || m, 20 + m, CASE WHEN m % 2 = 0 THEN 'female' ELSE 'male' END,
       CASE WHEN m = 1 THEN 'Self' ELSE 'Relative' END
FROM generate_series(1, :n) f CROSS JOIN generate_series(1, 4) m;

INSERT INTO booking_sessions (booking_id, session_id, kund_id, member_count, status)
SELECT f, CASE WHEN k = 1 THEN pr.s1 ELSE pr.s2 END, ((f - 1) % :per_pair) / 2 + 1, 4, 'CONFIRMED'
FROM generate_series(1, :n) f CROSS JOIN generate_series(1, 2) k JOIN _pairs pr ON pr.p = (f - 1) / :per_pair;

-- 1% of bookings are cancelled (history rows + released capacity via the trigger)
UPDATE booking_sessions SET status = 'CANCELLED', cancelled_at = now() WHERE booking_id % 100 = 0;
INSERT INTO cancellation_events (booking_session_id, booking_id, session_id, kund_id, released_member_count, reason)
SELECT id, booking_id, session_id, kund_id, member_count, 'Benchmark cancellation'
FROM booking_sessions WHERE status = 'CANCELLED';
UPDATE bookings SET status = 'CANCELLED', cancelled_at = now() WHERE id % 100 = 0;

-- 55% of members of confirmed reservations checked in
INSERT INTO attendance_checkins (event_id, booking_session_id, booking_id, member_id, source, checked_in_at)
SELECT gen_random_uuid(), bs.id, bs.booking_id, fm.id, 'ONLINE',
       timestamptz '2026-12-14 08:30+05:30' + ((fm.id % 120) * interval '1 minute')
FROM booking_sessions bs JOIN family_members fm ON fm.booking_id = bs.booking_id
WHERE bs.status = 'CONFIRMED' AND (fm.id + bs.id) % 20 < 11;
"""


def _statements(sql: str) -> list[str]:
    """Split the seed script into single statements (a prepared statement may hold only one)."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [part.strip() for part in os.linesep.join(lines).split(";") if part.strip()]


def _assert_local() -> None:
    host = make_url(get_settings().DATABASE_URL).host or ""
    if host not in LOCAL_HOSTS:
        sys.exit(f"Refusing to write synthetic data to '{host}': only a local scratch database is allowed.")
    if get_settings().is_production:
        sys.exit("Refusing to seed with APP_ENV=production.")


def seed(scenario: str) -> None:
    _assert_local()
    per_pair = PER_PAIR[scenario]
    with get_sessionmaker()() as db:
        db.execute(text("SET LOCAL statement_timeout = 0"))  # seeding only: the bulk insert fires 68k triggers
        db.execute(text(f"TRUNCATE {TRUNCATE} RESTART IDENTITY CASCADE"))
        db.execute(text("SELECT set_config('mahayagya.capacity_admin', 'on', true)"))
        db.execute(text("UPDATE kund_session_capacity SET reserved_count = 0 WHERE reserved_count <> 0"))
        if per_pair:
            t0 = time.perf_counter()
            for statement in _statements(SEED_SQL):
                db.execute(text(statement), {"n": per_pair * 8, "per_pair": per_pair})
            db.commit()
            db.execute(text("ANALYZE"))
            print(f"seeded {per_pair * 8:,} families in {time.perf_counter() - t0:.1f}s")
        db.commit()


def peak_memory_mb() -> float | None:
    try:
        import resource  # Linux / macOS

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 1024 if sys.platform != "darwin" else peak / (1024 * 1024)
    except ImportError:
        pass
    try:  # Windows
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        c = Counters()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def run_once(kind: str, report_date: date | None, read_only: bool) -> dict:
    path = Path(tempfile.gettempdir()) / f"bench-report-{os.getpid()}.xlsx"
    timer = StageTimer()
    t_all = time.perf_counter()
    with get_sessionmaker()() as db:
        t0 = time.perf_counter()
        if read_only:
            db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SELECT 1"))
        timer.add("connect", time.perf_counter() - t0)  # pool checkout + first round trip
        ReportingService(db).build_workbook(path, kind.upper(), report_date, timer)
        db.rollback()
    total = time.perf_counter() - t_all
    size = path.stat().st_size
    path.unlink(missing_ok=True)
    return {"total_s": total, "size": size, "timer": timer}


def print_run(i: int, r: dict) -> None:
    sec = r["timer"].seconds
    sheets = ["dashboard", "family_bookings", "family_members", "session_attendance", "kund_allocation",
              "cancellations", "no_shows"]
    print(f"\n--- run {i}: total {r['total_s']:.2f}s | xlsx {r['size'] / 1024:,.0f} KB")
    print(f"{'stage':20} {'db':>8} {'write':>8} {'python':>8} {'total':>8}  rows")
    for k in sheets:
        db_s, wr, tot = sec.get(f"{k}.db", 0), sec.get(f"{k}.write", 0), sec.get(f"{k}.total", 0)
        print(f"{k:20} {db_s:8.2f} {wr:8.2f} {max(tot - db_s - wr, 0):8.2f} {tot:8.2f}  {r['timer'].counts.get(k, '')}")
    print(f"{'connect':20} {sec.get('connect', 0):8.2f}   (pool checkout + first round trip)")
    print(f"{'scope':20} {sec.get('scope.db', 0):8.2f}")
    print(f"{'workbook.create':20} {sec.get('workbook.create', 0):8.2f}")
    print(f"{'save (xlsx zip)':20} {sec.get('save', 0):8.2f}")
    all_db = sum(v for k, v in sec.items() if k.endswith(".db"))
    all_wr = sum(v for k, v in sec.items() if k.endswith(".write"))
    print(f"sum: db {all_db:.2f}s | workbook-append {all_wr:.2f}s | save {sec.get('save', 0):.2f}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=[*PER_PAIR, "none"], default="none")
    ap.add_argument("--kind", choices=["full", "daily"], default="full")
    ap.add_argument("--date", default="2026-12-14", help="event date for --kind daily")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--after-event", action="store_true", help="freeze the clock after the event (no-shows computed)")
    ap.add_argument("--json", action="store_true", help="print one JSON line per run")
    args = ap.parse_args()

    if args.scenario != "none":
        seed(args.scenario)
    if args.after_event:
        clock.freeze(AFTER_EVENT)
    report_date = date.fromisoformat(args.date) if args.kind == "daily" else None
    host = make_url(get_settings().DATABASE_URL).host
    print(f"db host: {host} | scenario: {args.scenario} | kind: {args.kind} | after-event: {args.after_event}")
    for i in range(1, args.runs + 1):
        r = run_once(args.kind, report_date, read_only=args.scenario == "none")
        if args.json:
            print(json.dumps({"run": i, "total_s": round(r["total_s"], 3), "size": r["size"], **r["timer"].report(),
                              "peak_mb": peak_memory_mb()}))
        else:
            print_run(i, r)
    mem = peak_memory_mb()
    print(f"\npeak process memory: {mem:.0f} MB" if mem else "\npeak memory: n/a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
