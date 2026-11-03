-- =====================================================================
-- Least-privilege runtime role for the API.
-- Run ONCE as the schema owner (the role that ran the Alembic migrations),
-- after migrations. Replace the password placeholder via psql variable:
--
--   psql "$OWNER_DATABASE_URL" -v app_password="'<strong-random-password>'" \
--        -f scripts/sql/least_privilege.sql
--
-- Then set DATABASE_URL for the API to connect as mahayagya_app.
-- Migrations keep using the owner role (MIGRATIONS_DATABASE_URL).
-- =====================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mahayagya_app') THEN
    CREATE ROLE mahayagya_app LOGIN;
  END IF;
END $$;
ALTER ROLE mahayagya_app WITH PASSWORD :app_password;
ALTER ROLE mahayagya_app SET statement_timeout = '15s';

GRANT USAGE ON SCHEMA public TO mahayagya_app;
REVOKE CREATE ON SCHEMA public FROM mahayagya_app;

-- Read access everywhere the API needs it.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mahayagya_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mahayagya_app;

-- Writes: only what the application does. No DELETE on historical tables
-- (also blocked by triggers), no TRUNCATE, no DDL.
GRANT INSERT, UPDATE ON bookings, family_members, booking_sessions, qr_passes,
                        idempotency_records, admin_users, report_jobs,
                        offline_checkin_events, event_sessions TO mahayagya_app;
GRANT INSERT ON attendance_checkins, audit_logs, cancellation_events,
                offline_sync_receipts TO mahayagya_app;
-- Capacity rows: UPDATE is needed by the booking_sessions trigger (which runs
-- as the invoking role). Direct changes are still rejected by the guard trigger.
GRANT UPDATE (reserved_count, updated_at, is_blocked) ON kund_session_capacity TO mahayagya_app;
-- Offline roster is replaced per snapshot on the venue node.
GRANT INSERT, DELETE ON offline_roster_entries TO mahayagya_app;
-- Kund activation is an operational toggle.
GRANT UPDATE (is_active) ON kunds TO mahayagya_app;

-- Row level security is ENABLED on all tables (migration 0002) with no
-- policies for anon/authenticated. Give the app role explicit policies.
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version' LOOP
    EXECUTE format('DROP POLICY IF EXISTS app_all ON %I', t);
    EXECUTE format('CREATE POLICY app_all ON %I TO mahayagya_app USING (true) WITH CHECK (true)', t);
  END LOOP;
END $$;
