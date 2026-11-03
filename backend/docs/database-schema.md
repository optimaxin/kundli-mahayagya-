# Database schema

PostgreSQL 16 (compatible with Supabase). Migrations live in `alembic/versions/`:

* `0001_initial_schema.py`: tables, keys, CHECK/UNIQUE constraints and indexes, generated
  from `app/models` and reviewed by hand.
* `0002_integrity_triggers.py`: capacity triggers, member-count constraint trigger,
  append-only and no-delete triggers, row-level security.
* `0003_frontend_alignment.py`: AFTERNOON slot and confirmed times; member `age`, `gender`,
  `relationship`, `mobile`; optional `address`, `pincode`, `gotra`, `sankalp_purpose`;
  `kund_session_capacity.is_blocked` with a trigger that only allows blocking an empty Kund.

`alembic check` reports no drift between the models and the migrations.

## Seed data (`python -m scripts.seed_all`)

| Table | Rows | Notes |
|---|---:|---|
| `event_sessions` | **16** | ids 1-16. Odd ids are MORNING (08:00-11:00 IST), even ids are AFTERNOON (13:00-16:00 IST), 14-21 Dec 2026. |
| `kunds` | **2,151** | `kund_number` 1-2151 |
| `kund_session_capacity` | **34,416** | 16 × 2,151, `capacity = 8`, `reserved_count = 0` |

Capacity per session is 2,151 × 8 = **17,208** attendee places. Across all 16 sessions it is
**275,328** attendee-session reservations. These count places, not unique people.

## Tables

### Event and capacity

**`event_sessions`**: `id` (PK, fixed 1-16), `event_date`, `slot` (`MORNING`/`AFTERNOON`),
`start_time`, `end_time`, `status` (`SCHEDULED`/`CLOSED`/`COMPLETED`/`CANCELLED`),
`is_active`, `created_at`, `updated_at`.
Constraints: UNIQUE(`event_date`, `slot`); CHECK `end_time > start_time`.

**`kunds`**: `id` (PK), `kund_number` (UNIQUE, > 0), `is_active`, `created_at`.

**`kund_session_capacity`**: PK(`session_id`, `kund_id`), `capacity` (CHECK 1-8, default 8),
`reserved_count` (CHECK `0 <= reserved_count <= capacity`), `updated_at`.
Index `ix_ksc_best_fit (session_id, (capacity - reserved_count), kund_id) WHERE
reserved_count < capacity` is the best-fit lookup.

### Bookings

**`bookings`** (one per family): `id` (BIGINT identity), `booking_number` (UNIQUE,
`MY26-XXXXXXXX`), `coordinator_name`, `primary_mobile` (CHECK `^[6-9][0-9]{9}$`),
`secondary_mobile`, `email`, `address`, `city`, `state`, `pincode` (CHECK
`^[1-9][0-9]{5}$`), `gotra`, `sankalp_purpose`, `member_count` (CHECK 1-8), `status`
(`CONFIRMED`/`CANCELLED`), `created_at`, `updated_at`, `cancelled_at`.
UNIQUE(`id`, `member_count`) is the target of the reservation FK.
Indexes are on `primary_mobile`, `created_at` and `status`.

**`family_members`**: `id`, `booking_id` FK, `member_number` (CHECK 1-8), `full_name`,
`age` (CHECK 1-110), `gender` (`male`/`female`/`other`), `relationship`, `mobile` (optional,
format-checked), `created_at`. UNIQUE(`booking_id`, `member_number`). UNIQUE(`id`, `booking_id`) is the
target of the check-in FK.

**`booking_sessions`** (a family's reservation of one Kund in one session): `id`,
`booking_id`, `session_id`, `kund_id`, `member_count`, `status` (`CONFIRMED`/`CANCELLED`),
`created_at`, `cancelled_at`.

* UNIQUE(`booking_id`, `session_id`) allows one reservation per session per family.
* FK (`booking_id`, `member_count`) → `bookings(id, member_count)`, so the reservation size
  always equals the family size.
* FK (`session_id`, `kund_id`) → `kund_session_capacity`.
* UNIQUE(`id`, `booking_id`) is the target of the check-in FK.

### QR, attendance, staff

**`qr_passes`**: `id`, `booking_id`, `token_hash` (UNIQUE, SHA-256 hex, CHECK length 64),
`is_active`, `expires_at`, `created_at`, `created_by`, `revoked_at`, `revoked_by`,
`revoked_reason`. A partial UNIQUE index on `booking_id WHERE is_active` allows one active
pass per family.

**`attendance_checkins`** (one row per member per reserved session): `id`, `event_id`
(UNIQUE UUID, for idempotent client and offline retries), `booking_session_id`,
`booking_id`, `member_id`, `scanner_id` FK `admin_users`, `source`
(`ONLINE`/`OFFLINE_SYNC`), `offline_node_id`, `checked_in_at`, `recorded_at`.

* **UNIQUE(`booking_session_id`, `member_id`)** means a member checks in once per
  reservation.
* FK (`booking_session_id`, `booking_id`) → `booking_sessions(id, booking_id)`, and
  FK (`member_id`, `booking_id`) → `family_members(id, booking_id)`. Together they make it
  impossible to record a member against another family's reservation.

**`admin_users`**: `id` (UUID), `full_name`, `email` (UNIQUE, lowercase CHECK),
`password_hash` (Argon2id), `role` (`ADMIN`/`SUPERVISOR`/`SCANNER`),
`assigned_session_id` FK, `is_active`, `token_version`, `failed_login_count`,
`locked_until`, `last_login_at`, `created_at`, `updated_at`.

### Operations

**`idempotency_records`**: `scope` + `idempotency_key` (UNIQUE), `request_hash`, `status`,
`response_status`, `response_payload` (JSONB, without the raw token), `encrypted_secret`
(Fernet-encrypted QR token for replay, purged after the TTL), `resource_id`, `created_at`,
`expires_at`.

**`audit_logs`** (append-only): `actor_id`, `actor_role`, `action`, `entity_type`,
`entity_id`, `previous_values`, `new_values` (JSONB), `request_id`, `created_at`.

**`cancellation_events`** (append-only): `booking_session_id` (**UNIQUE**, so a reservation
is cancelled exactly once), `booking_id`, `session_id`, `kund_id`,
`released_member_count`, `actor_id`, `reason`, `created_at`.

**`report_jobs`**: tracks asynchronous Excel exports.

### Offline

* `offline_roster_entries` (venue node): one row per (session, booking) with `token_hash`,
  `kund_number`, members (JSONB).
* `offline_checkin_events` (venue node): `event_id` PK, UNIQUE(`session_id`,
  `booking_number`, `member_number`), `synced_at`, `sync_result`.
* `offline_sync_receipts` (cloud): `event_id` PK and the outcome, which makes ingestion
  idempotent.

## Triggers (migration 0002)

| Trigger | Table | Behaviour |
|---|---|---|
| `trg_booking_sessions_capacity` | `booking_sessions` AFTER INSERT/UPDATE | INSERT of a CONFIRMED reservation adds `member_count` to `reserved_count`. The CONFIRMED→CANCELLED transition subtracts it, **once**. Re-activation and changes to allocation fields raise an error. |
| `trg_kund_session_capacity_guard` | `kund_session_capacity` BEFORE UPDATE | Rejects changes to `reserved_count` that do not come from the trigger above, and changes to `capacity`, unless `mahayagya.capacity_admin = on` is set for a controlled maintenance operation. |
| `trg_bookings_member_count`, `trg_family_members_member_count` | DEFERRABLE INITIALLY DEFERRED | At COMMIT, `bookings.member_count` must equal the number of `family_members` rows. |
| `trg_<table>_no_delete` | bookings, family_members, booking_sessions, qr_passes, attendance_checkins, cancellation_events, audit_logs, kunds, event_sessions, kund_session_capacity | DELETE raises an error, so historical records are kept. |
| `trg_<table>_no_update` | audit_logs, cancellation_events, attendance_checkins | These tables are append-only. |

## Invariants and where they are enforced

| Invariant | Enforced by |
|---|---|
| A Kund never exceeds 8 (or its capacity) | CHECK constraint, trigger arithmetic, allocation query |
| `reserved_count` = Σ confirmed `member_count` | Only the trigger writes it; guard trigger; reconciliation endpoint `/admin/integrity` and `scripts/verify_integrity.py` |
| Family size 1-8, members = `member_count` | CHECKs plus the deferred constraint trigger |
| Reservation size = family size | Composite FK |
| One reservation per session per family | UNIQUE |
| One active QR per family | Partial UNIQUE index |
| One check-in per member per reservation | UNIQUE |
| Check-in member belongs to the booking | Composite FKs |
| Capacity released exactly once | Status transition in the trigger, `UPDATE … WHERE status='CONFIRMED'`, UNIQUE on `cancellation_events` |
| Historical records are kept | No-delete and append-only triggers; no DELETE grant for the app role |

## Row level security

RLS is enabled on every table. No policies exist for Supabase's `anon` and `authenticated`
roles, so its auto-generated APIs return nothing. The table owner bypasses RLS.
`scripts/sql/least_privilege.sql` adds `app_all` policies for the `mahayagya_app` role.
`scripts/sql/supabase_hardening.sql` additionally revokes table privileges from `anon` and
`authenticated`.
