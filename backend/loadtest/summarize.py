"""Print a compact table from loadtest/results/*.summary.json (k6 --summary-export)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def row(name: str, data: dict) -> str:
    m = data["metrics"]
    reqs = m.get("http_reqs", {})
    dur = m.get("http_req_duration", {})
    failed = m.get("http_req_failed", {})
    checks = m.get("checks", {})
    counters = {k: int(v.get("count", 0)) for k, v in m.items() if k.startswith(("reg_", "checkin_"))}
    return (
        f"{name:34} reqs={int(reqs.get('count', 0)):6d} rate={reqs.get('rate', 0):7.1f}/s "
        f"med={dur.get('med', 0):7.1f}ms p95={dur.get('p(95)', 0):7.1f}ms p99={dur.get('p(99)', 0):7.1f}ms "
        f"max={dur.get('max', 0):8.1f}ms failed={100 * failed.get('value', 0):5.2f}% "
        f"checks={100 * checks.get('value', 0):6.2f}% {counters}"
    )


if __name__ == "__main__":
    files = sorted(RESULTS.glob("*.summary.json")) if len(sys.argv) == 1 else [Path(a) for a in sys.argv[1:]]
    for f in files:
        print(row(f.name.replace(".summary.json", ""), json.loads(f.read_text())))
