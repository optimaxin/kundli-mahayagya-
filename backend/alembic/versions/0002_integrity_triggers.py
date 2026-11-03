"""Integrity triggers, capacity guard, append-only history and row level security.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03

Database-enforced invariants added here:

1. kund_session_capacity.reserved_count is maintained ONLY by the trigger on
   booking_sessions (INSERT CONFIRMED => +member_count, CONFIRMED->CANCELLED =>
   -member_count). Any other change to reserved_count/capacity is rejected
   unless a maintenance GUC is explicitly set. Combined with the CHECK
   (reserved_count <= capacity) this makes overbooking impossible and makes a
   cancellation release capacity exactly once.
2. A reservation's allocation fields are immutable and a cancelled reservation
   cannot be re-activated.
3. bookings.member_count must equal the number of family_members rows
   (deferred constraint trigger, checked at COMMIT).
4. Historical tables are append-only / non-deletable.
5. Row level security is enabled on every table with no policies, so that if
   the database is Supabase, the auto-generated PostgREST API (anon /
   authenticated roles) cannot read or write anything. The backend connects as
   the table owner (or a role granted explicit policies, see
   scripts/sql/least_privilege.sql).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_TABLES = [
    "admin_users",
    "attendance_checkins",
    "audit_logs",
    "booking_sessions",
    "bookings",
    "cancellation_events",
    "event_sessions",
    "family_members",
    "idempotency_records",
    "kund_session_capacity",
    "kunds",
    "offline_checkin_events",
    "offline_roster_entries",
    "offline_sync_receipts",
    "qr_passes",
    "report_jobs",
]

NO_DELETE_TABLES = [
    "bookings",
    "family_members",
    "booking_sessions",
    "qr_passes",
    "attendance_checkins",
    "cancellation_events",
    "audit_logs",
    "kunds",
    "event_sessions",
    "kund_session_capacity",
]

APPEND_ONLY_TABLES = ["audit_logs", "cancellation_events", "attendance_checkins"]


def upgrade() -> None:
    # ------------------------------------------------------------------ 1
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_booking_session_capacity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            delta integer := 0;
            affected integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'CONFIRMED' THEN
                    delta := NEW.member_count;
                END IF;
            ELSIF TG_OP = 'UPDATE' THEN
                IF NEW.session_id <> OLD.session_id OR NEW.kund_id <> OLD.kund_id
                   OR NEW.member_count <> OLD.member_count OR NEW.booking_id <> OLD.booking_id THEN
                    RAISE EXCEPTION 'booking_sessions allocation fields are immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF OLD.status = 'CONFIRMED' AND NEW.status = 'CANCELLED' THEN
                    delta := -OLD.member_count;
                ELSIF OLD.status = 'CANCELLED' AND NEW.status = 'CONFIRMED' THEN
                    RAISE EXCEPTION 'a cancelled reservation cannot be re-activated'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF delta <> 0 THEN
                PERFORM set_config('mahayagya.capacity_write', 'on', true);
                UPDATE kund_session_capacity
                   SET reserved_count = reserved_count + delta,
                       updated_at = now()
                 WHERE session_id = NEW.session_id AND kund_id = NEW.kund_id;
                GET DIAGNOSTICS affected = ROW_COUNT;
                PERFORM set_config('mahayagya.capacity_write', 'off', true);
                IF affected <> 1 THEN
                    RAISE EXCEPTION 'capacity row missing for session % kund %', NEW.session_id, NEW.kund_id
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_booking_sessions_capacity
        AFTER INSERT OR UPDATE ON booking_sessions
        FOR EACH ROW EXECUTE FUNCTION fn_booking_session_capacity();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_guard_capacity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.session_id <> OLD.session_id OR NEW.kund_id <> OLD.kund_id THEN
                RAISE EXCEPTION 'capacity keys are immutable' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.reserved_count IS DISTINCT FROM OLD.reserved_count
               AND coalesce(current_setting('mahayagya.capacity_write', true), 'off') <> 'on'
               AND coalesce(current_setting('mahayagya.capacity_admin', true), 'off') <> 'on' THEN
                RAISE EXCEPTION 'reserved_count can only change through booking_sessions'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.capacity IS DISTINCT FROM OLD.capacity
               AND coalesce(current_setting('mahayagya.capacity_admin', true), 'off') <> 'on' THEN
                RAISE EXCEPTION 'capacity can only be changed by a controlled maintenance operation'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_kund_session_capacity_guard
        BEFORE UPDATE ON kund_session_capacity
        FOR EACH ROW EXECUTE FUNCTION fn_guard_capacity();
        """
    )

    # ------------------------------------------------------------------ 3
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_check_booking_member_count() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            bid bigint;
            expected integer;
            actual integer;
        BEGIN
            IF TG_TABLE_NAME = 'bookings' THEN
                bid := NEW.id;
            ELSIF TG_OP = 'DELETE' THEN
                bid := OLD.booking_id;
            ELSE
                bid := NEW.booking_id;
            END IF;
            SELECT member_count INTO expected FROM bookings WHERE id = bid;
            IF expected IS NULL THEN
                RETURN NULL;
            END IF;
            SELECT count(*) INTO actual FROM family_members WHERE booking_id = bid;
            IF actual <> expected THEN
                RAISE EXCEPTION 'booking % declares % members but has % family_members rows', bid, expected, actual
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_bookings_member_count
        AFTER INSERT OR UPDATE OF member_count ON bookings
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION fn_check_booking_member_count();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_family_members_member_count
        AFTER INSERT OR UPDATE OF booking_id OR DELETE ON family_members
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION fn_check_booking_member_count();
        """
    )

    # ------------------------------------------------------------------ 4
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_prevent_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'rows in % are historical records and cannot be deleted', TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_prevent_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'rows in % are append-only', TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;
        """
    )
    for table in NO_DELETE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION fn_prevent_delete();"
        )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION fn_prevent_update();"
        )

    # ------------------------------------------------------------------ 5
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update ON {table};")
    for table in NO_DELETE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table};")
    op.execute("DROP TRIGGER IF EXISTS trg_family_members_member_count ON family_members;")
    op.execute("DROP TRIGGER IF EXISTS trg_bookings_member_count ON bookings;")
    op.execute("DROP TRIGGER IF EXISTS trg_kund_session_capacity_guard ON kund_session_capacity;")
    op.execute("DROP TRIGGER IF EXISTS trg_booking_sessions_capacity ON booking_sessions;")
    op.execute("DROP FUNCTION IF EXISTS fn_prevent_update();")
    op.execute("DROP FUNCTION IF EXISTS fn_prevent_delete();")
    op.execute("DROP FUNCTION IF EXISTS fn_check_booking_member_count();")
    op.execute("DROP FUNCTION IF EXISTS fn_guard_capacity();")
    op.execute("DROP FUNCTION IF EXISTS fn_booking_session_capacity();")
