-- =====================================================================
-- Supabase-specific hardening. Run once (SQL editor or psql as `postgres`)
-- AFTER the Alembic migrations have created the tables.
--
-- Supabase exposes the `public` schema through its auto-generated REST /
-- GraphQL APIs to the `anon` and `authenticated` roles. This backend does
-- NOT use those APIs: all access goes through the FastAPI service. RLS is
-- already enabled with no policies for those roles (migration 0002); this
-- script additionally revokes their table privileges (defence in depth).
-- =====================================================================

REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;

ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

-- Verify: should return zero rows.
SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated');
