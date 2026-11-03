#!/usr/bin/env bash
# Run one k6 scenario in Docker against the compose stack and record results.
#   loadtest/run_k6.sh <scenario.js> [extra k6 args, e.g. -e RATE=50]
# Results: loadtest/results/<scenario>.summary.json and <scenario>.stats.txt (CPU/mem samples)
set -euo pipefail
cd "$(dirname "$0")/.."
SCENARIO="$1"; shift
NAME="${SCENARIO%.js}"
NETWORK="${NETWORK:-mahayagya_default}"
BASE_URL="${BASE_URL:-http://api:8000}"
mkdir -p loadtest/results
STATS="loadtest/results/${NAME}.stats.txt"
: > "$STATS"

( while true; do
    docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' mahayagya-api-1 mahayagya-db-1 >> "$STATS" 2>/dev/null || true
    docker compose exec -T db psql -U "${POSTGRES_USER:-mahayagya}" -d "${POSTGRES_DB:-mahayagya}" -Atc \
      "select 'pg_connections=' || count(*) || ' active=' || count(*) filter (where state='active') from pg_stat_activity where datname=current_database()" >> "$STATS" 2>/dev/null || true
    sleep 5
  done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT

MSYS_NO_PATHCONV=1 docker run --rm -i --network "$NETWORK" \
  -v "$(pwd)/loadtest:/lt" grafana/k6:0.54.0 run -q \
  -e BASE_URL="$BASE_URL" "$@" \
  --summary-export "/lt/results/${NAME}.summary.json" \
  --summary-trend-stats "avg,med,p(95),p(99),max" \
  "/lt/k6/${SCENARIO}"
