# Load testing (k6)

> **These numbers come from one developer laptop. They are not a capacity guarantee for the event.**
> They show how the system behaves and where its limits are. Before the event, run the same
> scenarios against production-sized infrastructure (see "Before the event" below). The
> targets of 100,000 simultaneous visitors and 100,000 simultaneous registration attempts
> have **not** been tested and are **not** claimed.

## Scenarios

| Script | What it exercises |
|---|---|
| `k6/registration_normal.js` | Constant arrival rate. Families of 1-8 members, 1-3 sessions each. |
| `k6/registration_spike.js` | Ramps to `PEAK` req/s. Admission control should shed the excess with fast `503` + `Retry-After`. |
| `k6/eight_member_family.js` | 8-member families only. Each one fills a whole Kund. |
| `k6/multi_session.js` | Each family books 4-16 sessions in one atomic transaction (the widest lock scope). |
| `k6/same_kund_contention.js` | Every request is a 2-member family for the same session, so all requests compete for the same best-fit Kund. |
| `k6/duplicate_qr_scan.js` | Four scanner accounts check in random members of 50 families over and over (mostly duplicates). |
| `k6/scanner_during_registration_spike.js` | Scanner `scan` traffic while a registration spike is running. |
| `k6/resilience.js` | Steady traffic during a database restart or a network interruption (an operator triggers it by hand). |

## How to run

```bash
# 1. Start the stack with load-test overrides. This runs migrations and seeding,
#    disables per-IP rate limits and disables the check-in time window.
docker compose -f docker-compose.yml -f loadtest/docker-compose.loadtest.yml up -d --build

# 2. Create scanner accounts for session 1. The password (12+ chars with upper, lower and a digit) is read from stdin;
#    use your own value in place of <scanner-password> everywhere below.
for i in 1 2 3 4; do printf '%s' '<scanner-password>' | \
  python -m scripts.create_admin --email "scan$i@example.org" --name "Gate $i" \
         --role SCANNER --session 1 --password-stdin; done

# 3. Run the scenarios. k6 runs in Docker on the compose network.
loadtest/run_k6.sh registration_normal.js -e RATE=50 -e DURATION=60s
loadtest/run_k6.sh registration_spike.js -e PEAK=300 -e HOLD=30s
loadtest/run_k6.sh eight_member_family.js -e RATE=30
loadtest/run_k6.sh multi_session.js -e RATE=20
loadtest/run_k6.sh same_kund_contention.js -e VUS=50
SC=scan1@example.org,scan2@example.org,scan3@example.org,scan4@example.org
loadtest/run_k6.sh duplicate_qr_scan.js -e VUS=40 -e SCANNER_EMAILS=$SC -e SCANNER_PASSWORD='<scanner-password>'
loadtest/run_k6.sh scanner_during_registration_spike.js -e PEAK=200 -e SCANNER_EMAILS=$SC -e SCANNER_PASSWORD='<scanner-password>'
loadtest/run_k6.sh resilience.js -e RATE=20 -e DURATION=75s   # then: docker compose restart db

# 4. Summarise the results and check that the database is consistent.
python loadtest/summarize.py
python -m scripts.verify_integrity

# Reset booking data between runs (refuses to run in production):
LOADTEST_ALLOW_RESET=yes python -m loadtest.reset_loadtest_db
```

`run_k6.sh` writes `results/<scenario>.summary.json` (the k6 summary) and
`results/<scenario>.stats.txt`. The stats file holds API and DB CPU and memory, and
PostgreSQL connection counts, sampled every 5 s.

## Measured results (executed 2026-11-03)

**Environment:** a Windows 11 laptop with 8 logical CPUs and 12 GB RAM available to Docker
(WSL2). One API container ran 4 uvicorn workers, each with a database pool of 8 + 4 overflow
connections, admission control of 8 concurrent registrations plus a queue of 100 with a 5 s
timeout, and per-IP rate limiting disabled. PostgreSQL 16 ran in Docker on the same machine.
k6 0.54 ran in Docker on the same machine, so it competed with the API for CPU.

| Scenario | Load | Requests | Throughput | p50 | p95 | p99 | Max | Outcome |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Normal registration | 50 req/s for 60 s | 3,000 | 50.0/s | 21.7 ms | 43.9 ms | 96.2 ms | 260 ms | 3,000 × 201. Error rate 0 %. |
| Eight-member families | 30 req/s for 45 s | 1,351 | 30.0/s | 19.9 ms | 27.8 ms | 35.3 ms | 85 ms | 1,351 × 201 |
| Multi-session (4-16 sessions) | 20 req/s for 45 s | 901 | 20.0/s | 44.6 ms | 82.0 ms | 106 ms | 168 ms | 901 × 201 |
| Same-Kund contention (one session) | 50 VUs, closed loop, 45 s | 4,972 | **109.7/s** | 433 ms | 651 ms | 814 ms | 1.2 s | 4,972 × 201, no overbooking. **This is the per-session serialisation ceiling.** |
| Registration spike | ramp to 300 req/s | 13,530 | 191/s offered | 40 ms | 4.79 s | 5.45 s | 7.0 s | 5,643 × 201, 259 × 409, 7,628 × 503 (shed, with `Retry-After`). No other errors. |
| Duplicate QR scanning | 40 VUs, closed loop, 45 s | 8,346 | 179/s | 139 ms | **563 ms** | 722 ms | 1.0 s | 219 successes = 219 distinct members; 8,073 `ALREADY_CHECKED_IN`. p95 threshold of 500 ms **missed**. |
| Scanner traffic during a registration spike | 50 scans/s + registrations ramping to 200/s | 10,349 | 192/s | scan: 221 ms | scan: **485 ms** | scan: 653 ms | 853 ms | All scans `VALID`. Registrations: 3,223 × 201, 4,127 × 503 shed. |
| Database restart mid-run | 20 req/s for 75 s | 1,501 | 20/s | 21.3 ms | 30.4 ms | 58.8 ms | 4.0 s | 19 × `503 DATABASE_UNAVAILABLE` during the restart. Recovered automatically. |

Resource peaks: the API reached about 350-450 % CPU (4 workers saturated) in the spike and
scanning runs. PostgreSQL peaked at about 130 % CPU in the contention run. There were at most
37 PostgreSQL connections, with no more than 31 active. The 503s in the spike runs are counted
as `reg_503_shed_by_admission` in the result files; that counter has since been renamed
`reg_503_retryable`.

Integrity after the runs: `python -m scripts.verify_integrity` returned `ok: true` after the
contention, spike and restart runs. There were no capacity mismatches and no overbooked Kunds.
In every Kund-session row, `reserved_count` equalled the sum of confirmed allocations.

## How to read these results

1. **The laptop's API CPU was the bottleneck**, not PostgreSQL. In production, add API
   instances (they are stateless) and put the rate-limit state in Redis.
2. **One session accepts roughly 110 bookings/s on this hardware.** Strict best-fit means
   every family that wants a session competes for the same "fullest Kund that fits", so the
   allocator serialises on a per-session row lock (see `docs/architecture.md`). The 16
   sessions can be allocated in parallel. For scale, one session holds 17,208 places, which
   is about 4,300 families of four. At 110/s, a session fills in about 40 s.
3. **Spike behaviour is correct but slow for queued users.** Requests above capacity waited
   in the admission queue for up to the 5 s timeout and then received a 503 with
   `Retry-After`. Nothing timed out at the TCP level and nothing was half-booked. For the
   real launch, put a waiting room or queue in front of the registration form (CDN/WAF
   level) so users are not all retrying at once.
4. **Scanners should run on their own API instances.** The scanner p95 rose to 485-563 ms
   when scanners shared CPU with registrations or with 40 aggressive closed-loop VUs. On the
   event days, point scanner devices at dedicated API instances (or at the venue local
   server).

## Before the event (not yet done)

- Run all scenarios against the production topology: the Supabase plan or managed
  PostgreSQL, N API instances behind the load balancer, Redis rate limiting, and the
  CDN/WAF.
- Increase the load step by step (for example 50 → 100 → 200 → 400 → 800 req/s). At each
  step, record throughput, p95/p99, error rate, database CPU and connections, lock waits
  (`pg_stat_activity.wait_event`) and pooler saturation.
- Repeat the database-restart and network-interruption drills on the real infrastructure,
  including a pooler restart.
- Run from several load generators. A single k6 host cannot simulate 100k users.
