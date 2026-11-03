# Operations runbook

## Before registration opens

1. Check that `GET /api/v1/health/ready` returns `ready` with migration `0002`, 16 sessions
   and 2,151 Kunds.
2. Run `python -m scripts.verify_integrity`. Exit code 0 is required.
3. Load-test the production topology (see `loadtest/README.md`).
4. Turn on the waiting room or queue at the CDN/WAF and confirm the per-IP limits.
5. Confirm backups: PITR is enabled, and a manual `pg_dump` has been taken and restored once
   into a scratch database.

## During registration

* Watch the 503 rate. Some `SERVICE_BUSY` responses during spikes are expected (admission
  control at work). If they persist, add API instances. Raise
  `REGISTRATION_MAX_CONCURRENCY` only if the database has headroom.
* Watch `pg_stat_activity`: connections, `wait_event_type = 'Lock'`. Long lock waits on
  `event_sessions` mean one session is the hotspot. This is expected for popular sessions
  and is bounded by `lock_timeout`.
* To close booking for a session: `PATCH /api/v1/sessions/{id} {"status": "CLOSED"}`
  (audited).
* If a Kund is unusable (for example damaged), deactivate it so it receives no new
  allocations: `UPDATE kunds SET is_active=false WHERE kund_number=…`. Families already in
  it keep their place. Contact them separately if they need to move.

## Event days: scanners

1. Create SCANNER accounts per gate (`POST /admin/users` with `assigned_session_id`) and
   move them between sessions with `PATCH /admin/users/{id}`. A scanner can only check
   people into its assigned session.
2. The check-in window opens 15 min before the start and closes 15 min after the end
   (configurable).
3. If a pass is lost, the help desk verifies identity, then calls
   `POST /qr/{booking_number}/regenerate` and shows or prints the new QR. The old QR stops
   working immediately.
4. Each member is checked in individually. A family member arriving late is checked in
   later with the same QR.

## Offline mode (internet outage at the venue)

**Before every session, while online:** run `offline_node preload --session-id N` on the
venue local server. Re-run it close to the session start so the snapshot is fresh.

**When the internet drops:**

1. Switch the scanner devices to the local server URL. All gates must use the **same**
   local server; that is what prevents duplicates across gates.
2. Keep scanning. Events are stored on the local server's disk (PostgreSQL).
3. **Do not** register, cancel or regenerate QRs during the outage. Those operations only
   exist in the cloud.

**When the connection returns:**

1. Run `offline_node sync` (repeat until it reports nothing pending). It is idempotent, so
   re-running it is always safe.
2. Review the results. `ALREADY_CHECKED_IN` is a harmless duplicate. `REJECTED` (for
   example a cancelled reservation) needs manual review:
   `SELECT * FROM offline_checkin_events WHERE sync_result='REJECTED'` on the local server.
3. Switch the scanners back to the cloud URL.

**Known limitations:** duplicates between two *separate* offline local servers cannot be
detected while they are disconnected. Passes revoked or reservations cancelled after the
last preload are still accepted locally (flagged at sync). If the local server itself
fails, events not yet synced are lost unless its disk survives, so place the local server
on a UPS and avoid storing its data on removable media.

## Cancellations

`POST /bookings/{bn}/cancel {"reason": "...", "session_ids": [..optional..]}`. Capacity is
released exactly once, and repeating the call is harmless. Reservations with check-ins
cannot be cancelled. All records stay in the database (`cancellation_events` and
`audit_logs`).

## Reports

* Daily: `POST /reports/exports {"report_type":"DAILY","report_date":"2026-12-14"}`, then
  poll and download.
* Final: `{"report_type":"FINAL"}` after the last session (21 Dec, 20:00 IST).
* No-shows appear only for sessions whose scheduled end time has passed.
* Reports never modify data. **They are not backups.**

## Backups and restore

* Managed PITR (Supabase/RDS): the primary protection. Keep at least 7 days.
* Logical backup nightly and after each event day:
  ```bash
  pg_dump --format=custom --no-owner --file mahayagya-$(date +%F).dump "$MIGRATIONS_DATABASE_URL"
  ```
  Store it encrypted, off-site, with restricted access, because it contains personal data.
* Restore drill (into a scratch database):
  ```bash
  createdb mahayagya_restore && pg_restore --no-owner -d mahayagya_restore mahayagya-YYYY-MM-DD.dump
  DATABASE_URL=postgresql+psycopg://…/mahayagya_restore python -m scripts.verify_integrity
  ```
* After the event, keep the database read-only (revoke INSERT/UPDATE from `mahayagya_app`)
  rather than deleting anything. Retention and erasure of personal data must follow the
  organisers' privacy policy.

## Incident playbooks

| Symptom | Action |
|---|---|
| Many `DATABASE_UNAVAILABLE` 503s | Check DB and pooler health and connection limits. The API recovers on its own once the DB is back (`pool_pre_ping`), and no partial bookings are possible. |
| Many `SERVICE_BUSY` 503s | Scale the API, check DB CPU and lock waits, and confirm the waiting room is on. |
| `/admin/integrity` reports `ok: false` | Stop cancellations and admin edits. Capture the report and investigate before any manual fix. Fixing `reserved_count` needs `SET mahayagya.capacity_admin = on` inside a reviewed maintenance transaction and must be logged. |
| Suspected leaked staff credentials | `PATCH /admin/users/{id} {"is_active": false}` revokes all tokens immediately. Rotate the password. Review `GET /admin/audit-logs?actor_id=…`. |
| Suspected leaked `JWT_SECRET_KEY` | Rotate the secret and redeploy. All tokens become invalid and staff log in again. |
| QR shared or forged complaint | `POST /qr/{bn}/revoke`, then `/regenerate`. A forged QR cannot pass validation without a valid token (256-bit). |

## Audit

`GET /admin/audit-logs` covers logins and failed logins, bookings created and cancelled,
booking views, mobile searches, QR regeneration and revocation, session and user changes,
report requests and downloads, and offline snapshots and syncs. Audit rows cannot be
modified or deleted.
