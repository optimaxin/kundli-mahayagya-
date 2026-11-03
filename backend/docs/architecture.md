# Architecture

## 1. Overview

```
             Public website (React + Vite, existing)          Staff dashboard (future)     Scanner devices
                         |                                            |                       |
                 CDN / WAF / waiting room                             |                       |
                         |                                            |                       |
                 HTTPS load balancer  ------------------------------------------------------------
                    |                     |                                                   |
         API instances (registration)   API instances (admin)            API instances (scanner) / venue local server
             FastAPI, stateless           FastAPI, stateless                 FastAPI, stateless
                    \_____________________|___________________________________/
                                          |
                          connection pooler (Supavisor / PgBouncer)
                                          |
                               PostgreSQL (Supabase or self-managed)
                                 - the single source of truth
```

* **Stateless API workers.** No session state lives in the processes. JWTs carry identity,
  and PostgreSQL holds everything else. Run as many instances as needed.
* **PostgreSQL is authoritative for Kund capacity.** Neither Redis nor any other cache takes
  part in allocation. Redis is optional and is used only for shared rate-limit counters.
* **Traffic separation.** The same codebase can be deployed as separate pools: public
  registration, staff/admin, and scanners. Scanner latency then does not suffer during
  registration spikes (see the load-test results).

## 2. Code structure (layers)

| Layer | Location | Responsibility |
|---|---|---|
| API (routes) | `app/api/v1/*.py` | HTTP concerns only: parse and validate input, check auth dependencies, shape responses. No business logic. |
| Schemas | `app/schemas/*.py` | Pydantic request/response models, validation and normalisation (mobile numbers, names, states, PIN codes). |
| Services | `app/services/*.py` | Business rules and transaction boundaries (`registration`, `allocation`, `qr`, `checkin`, `cancellation`, `offline_sync`, `reporting`, `auth`, `admin`, `audit`). |
| Repositories | `app/repositories/*.py` | Data access through parameterised SQLAlchemy 2.x statements. |
| Models | `app/models/*.py` | ORM mapping, plus constraints that are mirrored in the Alembic migrations. |
| Core | `app/core/*.py` | Config, DB engine and transaction/retry helper, security primitives, RBAC, errors, rate limiting, logging, clock. |
| Middleware | `app/middleware/*.py` | Request ID with a sanitised access log, and security headers. |

## 3. Kund allocation engine (`app/services/allocation_service.py`)

**Rules:** a family of 1-8 occupies exactly one Kund per selected session and is never
split. Selection is BEST-FIT: among active Kunds that can hold the whole family, the one
with the fewest free seats wins. Ties go to the lowest Kund number. A multi-session booking
is all-or-nothing.

**Algorithm, in one transaction:**

1. Lock the selected `event_sessions` rows in ascending id order with
   `SELECT … FOR NO KEY UPDATE`.
2. For each session in ascending order:
   `SELECT … FROM kund_session_capacity JOIN kunds … WHERE free >= family_size AND kund active
   ORDER BY free ASC, kund_id ASC LIMIT 1 FOR UPDATE OF kund_session_capacity`. This uses
   the partial expression index `ix_ksc_best_fit (session_id, capacity - reserved_count,
   kund_id) WHERE reserved_count < capacity`, so the first index entry is the answer.
3. `INSERT INTO booking_sessions`. An AFTER INSERT trigger adds `member_count` to
   `reserved_count`.
4. If any session has no Kund that fits, raise `CapacityUnavailable`. The whole transaction
   rolls back: booking, members, QR pass, idempotency record and any allocations already
   made.

**Why a session-row lock (and not `SKIP LOCKED`)?**

* Best-fit means every concurrent family wants the same "fullest Kund that fits". Row-level
  locking on capacity rows alone would make each family queue behind that hot row and then
  re-scan with a stale sort order. Serialising Kund selection per session gives an exact
  best-fit decision on fresh data.
* `SKIP LOCKED` would treat a Kund that is merely locked by another transaction as
  unavailable. That gives a wrong best-fit choice and, near full capacity, a false "sold
  out". It is deliberately not used.
* Every capacity-changing transaction (allocation and cancellation) takes the session locks
  in the same ascending order, so multi-session bookings cannot form deadlock cycles.
  `FOR NO KEY UPDATE` does not conflict with the `FOR KEY SHARE` locks that foreign-key
  checks take.
* Lock waits are bounded by a transaction-local `lock_timeout` (5 s by default).
  Deadlock (`40P01`), lock timeout (`55P03`) and serialisation failure (`40001`) are retried
  with jittered backoff by `run_transaction`. When retries run out, the client gets a 503
  with `Retry-After`.
* Lock hold time is kept short: booking, members and the QR pass are inserted before the
  locks are taken. Measured: about 110 allocations/s for a single contended session on a
  laptop. Sessions are independent of each other.

**Defence in depth, enforced by the database even if the application had a bug:**

* `CHECK (reserved_count BETWEEN 0 AND capacity)` and `CHECK (capacity BETWEEN 1 AND 8)`.
* `reserved_count` changes only through the `booking_sessions` trigger. A guard trigger
  rejects any other update unless a maintenance setting is turned on explicitly.
* A composite FK `(booking_id, member_count) → bookings(id, member_count)` pins every
  reservation to the family size.
* A deferred constraint trigger checks at COMMIT that `bookings.member_count` equals the
  number of `family_members` rows.
* `UNIQUE (booking_id, session_id)` allows one reservation per session per booking.

## 4. Registration flow (`registration_service.py`)

1. Claim the `Idempotency-Key` with `INSERT … ON CONFLICT DO NOTHING`. If the same key is
   in flight, the second request blocks on the unique index. Once the first commits, the
   second **replays** the stored response, including the same QR token (kept encrypted for
   24 h only). If the body differs, the response is `422 IDEMPOTENCY_KEY_REUSED`. A failed
   attempt leaves no record, so a retry runs again from scratch.
2. Validate the sessions: they exist, and no date has both its morning and afternoon session
   selected (`422 ONE_SESSION_PER_DAY`).
3. Take an advisory lock on the coordinator's mobile number. If a confirmed booking already
   exists for the same mobile in the same session, or on the same day in either slot, return
   `409 DUPLICATE_BOOKING`. This protects against double clicks with different keys.
   Then check that the sessions are active, have status SCHEDULED, and are before the cut-off
   (60 min before start).
4. Insert the booking (random `MY26-XXXXXXXX` number) and its members.
5. Issue the QR pass.
6. Allocate (§3).
7. Complete the idempotency record and write the audit log, then COMMIT.

**Admission control:** each worker runs at most `REGISTRATION_MAX_CONCURRENCY`
registrations at a time. Up to `REGISTRATION_MAX_QUEUE` more wait for up to
`REGISTRATION_QUEUE_TIMEOUT_SECONDS`. Beyond that, the response is an immediate 503 with
`Retry-After`. This protects the DB pool: 100k clients never turn into 100k DB connections.

## 5. QR passes (`qr_service.py`)

* Token: `secrets.token_urlsafe(32)`, which gives 256 bits from a CSPRNG. The QR encodes
  `MY26.<token>`, which contains no PII and no database IDs.
* Only `sha256(token)` is stored (`qr_passes.token_hash`, unique). A partial unique index
  allows at most one active pass per booking. Regeneration revokes the old pass in the same
  transaction, and revoked passes are kept for history.
* Tokens are only ever sent in request bodies, never in URLs, so they do not appear in
  access logs. Unknown, revoked and expired tokens all get the same 404, so there is no
  oracle. Lookups are rate-limited per IP and per booking number.

## 6. Scanner and attendance (`checkin_service.py`)

* For a SCANNER account the session always comes from `admin_users.assigned_session_id`; a
  client-supplied `session_id` is rejected. ADMIN/SUPERVISOR (the admin console's scanner tab) must
  name the session explicitly, and every check-in records who made it.
* A typed Pass ID (booking number) is accepted as a camera fallback. It still requires an active pass,
  has a tighter per-scanner rate limit, and the roster lets the volunteer verify names against photo ID.
* Scan: QR → pass → booking → reservation for the scanner's session → roster with
  per-member check-in state and the Kund number.
* Check-in: re-validate everything, then `INSERT … ON CONFLICT DO NOTHING` against
  `UNIQUE (booking_session_id, member_id)`. Concurrent scans of the same member yield exactly
  one `CHECKIN_SUCCESS`; the others get `ALREADY_CHECKED_IN`. Composite FKs guarantee that
  the member and the reservation belong to the same booking.
* An optional client `event_id` makes retries idempotent.
* Check-in is accepted only within the session window (15 min before start until 15 min
  after end, configurable).

## 7. Offline check-in (`offline_sync_service.py`, `scripts/offline_node.py`)

```
 cloud API + DB  <──── HTTPS when available ────>  venue LOCAL server (same app, OFFLINE_NODE_MODE=true,
                                                    its own PostgreSQL, on the venue LAN/Wi-Fi)
                                                            ^           ^           ^
                                                         gate 1      gate 2      gate N   (scanner devices)
```

1. **Preload** (before each session, while online): `offline_node.py preload --session-id N`
   pulls a snapshot. It contains active QR token hashes (never raw tokens), booking numbers,
   reservation status, Kund numbers, member rosters and the check-ins already recorded in the
   cloud.
2. **Local operation:** scanners use `/api/v1/offline/local/scan|checkin` on the local
   server. Each check-in is stored durably with a UUID `event_id`.
   `UNIQUE (session_id, booking_number, member_number)` prevents duplicates across all gates
   connected to that one local server.
3. **Sync** (when the connection returns, repeatable, cron-safe):
   `offline_node.py sync` pushes unsynced events in batches of up to 500. The cloud records
   exactly one receipt per `event_id` (`offline_sync_receipts`). Re-sending an event returns
   the original outcome. A conflict with an online check-in resolves to
   `ALREADY_CHECKED_IN`; the earliest stored row is kept and nothing is overwritten.
   Reservations that were cancelled after the snapshot come back as `REJECTED` and are
   kept for manual review.

**Limitations (by design, also documented in the runbook):**

* Duplicate detection during an outage covers only gates connected to the **same** local
  server. Two separate local servers that are cut off from each other cannot detect each
  other's duplicates. Use one local server per venue.
* Passes revoked, or reservations cancelled, after the snapshot are still accepted while
  offline. They are flagged at sync time.
* **No registration or allocation happens offline.** Capacity has one authority, the cloud
  database. Allocating offline would need a separate capacity-partitioning design, which
  this project does not implement.

## 8. Security architecture

| Concern | Control |
|---|---|
| Passwords | Argon2id (`argon2-cffi`), rehash on login if parameters change, strength policy (≥ 12 chars, upper, lower, digit). |
| Tokens | HS256 JWT with `iss`/`aud`/`exp`/`nbf`/`jti` and an explicit algorithm allow-list. On every request the user is reloaded and `is_active`, `role` and `token_version` must match, so deactivation, logout and password changes take effect immediately. |
| Brute force | Per-IP and per-account login rate limits. Account lockout after 5 failures for 15 min. Pass lookups are rate-limited per IP and per booking number. |
| RBAC | `require_roles(...)` dependencies. The permission matrix is in `app/core/permissions.py` and in the API docs. |
| Input | Pydantic schemas with `extra="forbid"`, Unicode-aware validators, length limits. Markup characters are rejected in free text. Validation errors never echo the submitted values. |
| SQL injection | Only parameterised SQLAlchemy statements. No string-built SQL from user input. |
| PII in logs | The access log records route templates without query strings. A JSON formatter redacts PII-like keys. A test asserts that no mobile, email, name or token appears in logs. |
| PII exposure | Public endpoints return availability and masked data only. Mobile search is privileged and audited, and viewing full booking details is audited too. |
| Headers | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, optional HSTS, and the `Server` header is removed. |
| CORS | Explicit allow-list; production refuses `*`. |
| Secrets | Environment variables only. Production start-up fails if the JWT secret or encryption key is a default or empty. `.env` is git-ignored, and a test scans the repository for credential patterns. |
| DB privileges | `scripts/sql/least_privilege.sql` creates `mahayagya_app` with DML only: no DELETE on history, no TRUNCATE, no DDL. RLS is enabled on every table (Supabase PostgREST cannot read anything). Verified end to end. |
| History | Bookings, members, reservations, passes, check-ins, cancellations and audit logs cannot be deleted (triggers). Check-ins, cancellations and audit logs are append-only. |
| Spreadsheet export | Cells starting with `= + - @` are prefixed with `'` to block formula injection. |

## 9. Time

All rules read time through `app.core.clock`, which is UTC internally and converts with the
`Asia/Kolkata` event timezone. Tests freeze the clock to exercise booking cut-off, check-in
windows and no-show computation.
