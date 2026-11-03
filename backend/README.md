# 2151 Kundiya Mahayagya: registration and event management backend

A FastAPI + PostgreSQL backend for the eight-day **2151 Kundiya Mahayagya**
(14–21 December 2026). It covers family registration, best-fit Kund allocation, family QR
passes, per-member check-in (online and offline), admin operations, and Excel reporting.

* 16 sessions (8 days × MORNING 08:00–11:00 / AFTERNOON 13:00–16:00 IST) · 2,151 Kunds · 8 members per Kund
* 17,208 attendee places per session; 275,328 attendee-session places in total
* A family of 1–8 gets **one Kund per selected session** (never split, best-fit),
  **one QR pass** for all its sessions, and each member is **checked in individually**

The backend is independent of the frontend. It exposes a versioned REST API (`/api/v1`)
that the existing React + Vite website can use later.

## Contents

* [Quick start](#quick-start)
* [Running the tests](#running-the-tests)
* [Project layout](#project-layout)
* [Connecting Supabase later](#connecting-supabase-later)
* [Integrating the React + Vite frontend](#integrating-the-react--vite-frontend-separate-phase)
* [Status: completed, incomplete, limitations](#status)
* Documentation: [architecture](docs/architecture.md) · [database schema](docs/database-schema.md) ·
  [API](docs/api-documentation.md) · [deployment](docs/deployment.md) ·
  [operations runbook](docs/operations-runbook.md) · [load tests](loadtest/README.md)

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic · PostgreSQL 16 (psycopg 3)
· Argon2id · PyJWT · segno (QR) · openpyxl · pytest + HTTPX · Docker Compose · k6

## Quick start

Prerequisites: Python 3.12+, Docker (for PostgreSQL).

```bash
cd backend

# 1. Python environment
python -m venv .venv
. .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 2. Configuration (the dev defaults work as-is; no Supabase needed)
cp .env.example .env

# 3. Start PostgreSQL (creates the 'mahayagya' and 'mahayagya_test' databases)
docker compose up -d db

# 4. Run the database migrations
alembic upgrade head

# 5. Seed the 16 sessions, 2,151 Kunds and 34,416 capacity rows (idempotent, verifies counts)
python -m scripts.seed_all
#    (or individually: python -m scripts.seed_sessions ; python -m scripts.seed_kunds)

# 6. Create the first administrator (the password is prompted for, never passed as an argument)
python -m scripts.create_admin --email admin@example.org --name "Event Admin"
#    For automation: printf '%s' "$ADMIN_PASSWORD" | python -m scripts.create_admin --email ... --name ... --password-stdin

# 7. Start the API
uvicorn app.main:app --reload
```

* Swagger UI: **http://localhost:8000/docs** (ReDoc: `/redoc`, spec: `/openapi.json` and
  [docs/openapi.json](docs/openapi.json)). Click **Authorize** and log in with the admin
  credentials to try the staff endpoints.
* Health: `GET /api/v1/health/ready`.
* Everything in Docker instead: `docker compose up -d --build`, then
  `docker compose exec api alembic upgrade head`,
  `docker compose exec api python -m scripts.seed_all`, and
  `docker compose exec api python -m scripts.create_admin --email … --name …`.

Try a registration:

```bash
curl -s -X POST http://localhost:8000/api/v1/registrations \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $(python -c 'import uuid;print(uuid.uuid4())')" \
  -d '{"coordinator":{"name":"Rahul Sharma","primary_mobile":"9876543210","secondary_mobile":"",
       "email":"rahul@example.com","address":"12 Civil Lines","city":"Agra","state":"Uttar Pradesh",
       "pincode":"282001","gotra":"Bharadwaj","sankalp_purpose":"Family wellbeing"},
       "members":[{"full_name":"Rahul Sharma","age":38,"gender":"male","relationship":"Self"},
                  {"full_name":"Priya Sharma","age":35,"gender":"female","relationship":"Spouse"}],
       "selected_sessions":[1,2,3]}'
```

## Running the tests

The suite runs against a **real PostgreSQL** database. Nothing is mocked and no SQLite is
used. By default it uses `mahayagya_test` on the Docker database; override this with
`TEST_DATABASE_URL`. The schema is rebuilt with Alembic and seeded once per run.

```bash
docker compose up -d db
pytest                       # all tests
pytest tests/concurrency     # multi-threaded PostgreSQL concurrency tests only
pytest tests/security        # authn/authz, rate limits, headers, PII and secret hygiene
ruff check .                 # lint
```

**Last executed result: 185 passed** (2026-11-04, PostgreSQL 16, Python 3.12.5). By folder:

| Folder | What is verified |
|---|---|
| `tests/integration/test_database.py` | Exactly 16 / 2,151 / 34,416 rows, all capacity 8 and reserved 0; DB rejects direct capacity edits, overbooking, member-count mismatches, cross-family check-ins, deletes of history and edits to audit logs; RLS is on |
| `tests/integration/test_registration.py` | 1-member and 8-member families, multi-session bookings, invalid session, more than 8 members, validation messages, idempotent replay (same booking and token), key reuse, duplicate mobile, **one session per day** (never both slots of a date, also across a mobile's bookings, switchable), **full rollback of a failed multi-session booking**, cut-off |
| `tests/integration/test_allocation.py` | Best-fit (the spec's Kund 101 example and a fullest-fit sequence), empty Kund fallback, never split, no Kund available, inactive Kunds, per-session independence, never above 8 |
| `tests/concurrency/test_concurrency.py` | Two families racing for the last 2 places (exactly one wins); 60 families racing for 40 places (no overbooking); 40 overlapping multi-session bookings (no deadlock failures); all-or-nothing under contention; concurrent duplicate idempotency keys; double-click duplicates; concurrent duplicate cancellations (released once); cancellation racing registration; 6 scanners checking in the same member (exactly one success) |
| `tests/integration/test_qr.py` | One active pass, only the hash stored, the token not in the DB, entropy, retrieval, PNG/SVG, regenerate and revoke, validation, public status lookup |
| `tests/integration/test_scanner.py` | Assigned-session enforcement, roster, per-member check-in, duplicate rejection, a member can check in to another session, invalid member/QR/session, cancelled bookings, time window, roles, idempotent `event_id` |
| `tests/integration/test_cancellation.py` | Released exactly once, duplicate cancellation, history preserved, partial cancellation, freed capacity reused best-fit, no cancellation after check-in, permissions |
| `tests/integration/test_reports.py` | All 7 sheets, attendance accuracy, **no-shows only after completion**, formula-injection guard, records unchanged, async export API |
| `tests/integration/test_admin.py` | Dashboard totals, availability, Kund allocation, search, audited mobile search, filters, sorting and pagination, user management, integrity |
| `tests/integration/test_offline_sync.py` | Snapshot holds hashes only, LAN duplicate prevention across gates, idempotent sync and replay, conflict with online check-ins, cancelled-after-snapshot rejection |
| `tests/security/test_security.py` | 401 on every staff endpoint, 403 by role, forged / `alg=none` / expired / role-escalated tokens, lockout, rate limits, security headers, CORS, production config guard, SQL injection, **no PII in logs**, no secrets in the repo, retryable 503 on DB outage |
| `tests/integration/test_frontend_contract.py` | What the React frontend relies on: optional coordinator fields, member age/gender/relationship, 08–11 / 13–16 sessions, ±15 min window, manual pass-ID entry, staff scanning with an explicit session, manual entry, Kund map and per-session block, dashboard analytics, booking search/expand |
| `tests/unit/test_units.py` | Validators, booking numbers, tokens, hashing, JWT, encryption, rate limiter, schemas |

Load tests (k6) and their measured results: [loadtest/README.md](loadtest/README.md).

## Project layout

```
backend/
├── app/
│   ├── main.py                 # app factory, middleware, routers
│   ├── core/                   # config, database (+ retrying transactions), security, permissions,
│   │                           # errors, rate limiting + admission control, logging, clock
│   ├── models/                 # SQLAlchemy models (event, booking, operations, offline)
│   ├── schemas/                # Pydantic request/response models + validation
│   ├── repositories/           # data access (parameterised queries only)
│   ├── services/               # registration, allocation, qr, checkin, cancellation,
│   │                           # offline_sync, reporting, auth, admin, audit, seed, session rules
│   ├── api/v1/                 # thin route handlers
│   ├── middleware/             # request id / access log, security headers
│   └── utils/                  # validators, identifiers, masking
├── alembic/versions/           # 0001 schema, 0002 triggers + RLS
├── scripts/                    # seed_sessions, seed_kunds, seed_all, create_admin,
│   │                           # offline_node, verify_integrity
│   └── sql/                    # least_privilege.sql, supabase_hardening.sql, init-test-db.sql
├── tests/                      # unit, integration, concurrency, security
├── loadtest/                   # k6 scenarios, runner, results, compose override
├── docs/                       # architecture, schema, API, deployment, runbook, openapi.json
├── Dockerfile, docker-compose.yml, docker-entrypoint.sh
├── .env.example, requirements*.txt, pyproject.toml, pytest.ini, alembic.ini
```

## Connecting Supabase later

You only need to change configuration. The full procedure is in
[docs/deployment.md §3](docs/deployment.md#3-connecting-supabase-when-the-credentials-are-available).
In short:

1. Set `MIGRATIONS_DATABASE_URL` to the Supabase direct or session connection string
   (`?sslmode=require`), then run `alembic upgrade head` and `python -m scripts.seed_all`.
2. Run `scripts/sql/supabase_hardening.sql` and `scripts/sql/least_privilege.sql`.
3. Set `DATABASE_URL` to the **transaction pooler** URL (port 6543) for the `mahayagya_app`
   user, plus `DB_DISABLE_PREPARED_STATEMENTS=true`.
4. `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` exist in
   `.env.example` as placeholders only. The backend does not need them, and the service-role
   key must never reach a browser.

## Integrating the React + Vite frontend (separate phase)

* Add the site origin to `CORS_ALLOWED_ORIGINS`.
* Registration page: use `GET /api/v1/sessions` for availability and
  `largest_family_bookable`, then `POST /api/v1/registrations` with one
  `crypto.randomUUID()` Idempotency-Key per submit attempt (reuse it on retries). Show the
  per-field validation errors from `error.details`.
* Confirmation page: show the booking number, Kunds and sessions, then render the QR with
  `POST /api/v1/qr/pass/image {token}`. Never put the token in a URL.
* "My pass" page: `POST /api/v1/qr/pass {token}`. Status check:
  `POST /api/v1/qr/status {booking_number, primary_mobile}`.
* The admin dashboard and the scanner PWA use `POST /api/v1/auth/login` (JWT bearer).
* Details: [docs/api-documentation.md → Frontend integration notes](docs/api-documentation.md#frontend-integration-notes-react--vite-a-separate-phase).

## Status

### Completed and verified by executed tests

* Normalised PostgreSQL schema (16 tables), Alembic migrations (up/down verified,
  `alembic check` clean), and idempotent seeds (16 / 2,151 / 34,416).
* Database-enforced invariants: capacity maintained by triggers, overbooking impossible,
  member-count consistency, append-only and non-deletable history, RLS.
* Registration API: validation, idempotency (with encrypted short-lived replay of the QR
  token), duplicate-mobile guard, atomic multi-session allocation, admission control.
* Best-fit allocation engine with row locks, consistent lock ordering, lock timeouts and
  retries, verified under real concurrency.
* QR passes: 256-bit tokens, SHA-256 at rest, one active pass per family, regenerate and
  revoke, PNG/SVG, pass lookup.
* Scanner and attendance: server-side session assignment, per-member check-in,
  `UNIQUE(booking_session_id, member_id)`, the six status codes, idempotent `event_id`.
* Cancellation: exactly-once capacity release, idempotent, audited, history preserved.
* Offline: snapshot, venue local server endpoints, durable local events, idempotent cloud
  sync with receipts, and the `offline_node.py` CLI.
* Admin APIs: dashboard, availability, Kund allocation, search (audited mobile search),
  booking details, staff and scanner management, audit logs, integrity reconciliation.
* Excel reporting: 7 sheets, daily and final, asynchronous jobs, no-shows only after
  completion, formula-injection safe.
* Security: Argon2id, JWT with immediate revocation, RBAC, lockout, rate limits, security
  headers, CORS allow-list, PII-safe logging, production config guard, least-privilege
  role (verified by running real flows as `mahayagya_app`).
* Docker image and Compose stack (built and run), `.env.example`, documentation, OpenAPI
  export.
* k6 scenarios for all 9 requested situations, executed on a laptop with the results
  recorded.

### Not done or incomplete

* **Production-scale load testing.** 100k simultaneous visitors and registrations have not
  been tested and are not claimed. The laptop numbers are in `loadtest/README.md`.
* **Supabase connection.** It has not been exercised because the credentials will be
  provided later. Only standard PostgreSQL features are used, and the switch is documented.
* **OTP or SMS verification** for self-service pass recovery or cancellation. No
  SMS/WhatsApp provider is integrated. Lost passes are re-issued by the help desk
  (`/qr/{bn}/regenerate`). Families cannot cancel by themselves; staff cancel for them.
* **Notifications** (SMS, email, WhatsApp confirmation with the QR) are not implemented.
* **Frontend integration**: out of scope for this phase, by design.
* **Report storage across several instances**: reports are written to the local
  `REPORTS_DIR` volume. Multi-instance deployments need shared or object storage (for
  example Supabase Storage).
* **Scheduled jobs** (idempotency secret purge, integrity checks, `offline_node sync`) are
  provided as an endpoint and scripts. Wiring them into cron or a scheduler is a deployment
  task.

### Known limitations

* Kund selection is **serialised per session** to guarantee exact best-fit. One session
  measured about 110 bookings/s on a laptop; the 16 sessions run in parallel.
* The in-memory rate limiter works per process. Use the Redis backend and WAF limits when
  running more than one instance.
* Offline mode: no duplicate detection between two **separate** disconnected local servers.
  Revocations and cancellations made after the snapshot are only caught at sync time. No
  registration happens offline.
* No-shows are computed from the scheduled end time. If an admin marks a session COMPLETED
  early, no-shows still are not computed early.
* A booking's family members cannot be edited after confirmation (cancel and re-register
  instead). This keeps the capacity and roster invariants simple and auditable.
