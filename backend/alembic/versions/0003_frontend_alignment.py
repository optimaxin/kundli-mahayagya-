"""Align the schema with the React frontend.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04

* Sessions: MORNING 08:00-11:00 and AFTERNOON 13:00-16:00 IST (confirmed times;
  the EVENING slot is renamed AFTERNOON).
* family_members: age, gender, relationship, optional mobile.
* bookings: address, pincode, gotra and sankalp_purpose become optional.
* kund_session_capacity.is_blocked: organisers can block an EMPTY Kund for one
  session (excluded from allocation). A trigger refuses to block a Kund that
  has reservations.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- sessions -----------------------------------------------------------
    op.drop_constraint(op.f("ck_event_sessions_slot_valid"), "event_sessions", type_="check")
    op.execute(
        "UPDATE event_sessions SET slot = 'AFTERNOON', start_time = '13:00', end_time = '16:00' "
        "WHERE slot = 'EVENING'"
    )
    op.execute("UPDATE event_sessions SET start_time = '08:00', end_time = '11:00' WHERE slot = 'MORNING'")
    op.create_check_constraint(op.f("ck_event_sessions_slot_valid"), "event_sessions", "slot IN ('MORNING', 'AFTERNOON')")

    # --- family members -------------------------------------------------------
    op.add_column("family_members", sa.Column("age", sa.SmallInteger(), nullable=True))
    op.add_column("family_members", sa.Column("gender", sa.String(length=10), nullable=True))
    op.add_column("family_members", sa.Column("relationship", sa.String(length=30), nullable=True))
    op.add_column("family_members", sa.Column("mobile", sa.String(length=10), nullable=True))
    op.create_check_constraint(op.f("ck_family_members_age_range"), "family_members", "age IS NULL OR age BETWEEN 1 AND 110")
    op.create_check_constraint(
        op.f("ck_family_members_gender_valid"), "family_members", "gender IS NULL OR gender IN ('male', 'female', 'other')"
    )
    op.create_check_constraint(
        op.f("ck_family_members_mobile_format"), "family_members", "mobile IS NULL OR mobile ~ '^[6-9][0-9]{9}$'"
    )

    # --- optional booking fields --------------------------------------------
    for col in ("address", "pincode", "gotra", "sankalp_purpose"):
        op.alter_column("bookings", col, nullable=True)
    op.drop_constraint(op.f("ck_bookings_pincode_format"), "bookings", type_="check")
    op.create_check_constraint(
        op.f("ck_bookings_pincode_format"), "bookings", "pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'"
    )

    # --- per-session Kund block --------------------------------------------
    op.add_column(
        "kund_session_capacity",
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_guard_kund_block() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.is_blocked AND NOT OLD.is_blocked AND OLD.reserved_count > 0 THEN
                RAISE EXCEPTION 'cannot block a Kund that already has reservations'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.is_blocked AND NEW.reserved_count > OLD.reserved_count THEN
                RAISE EXCEPTION 'cannot allocate into a blocked Kund'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_kund_session_capacity_block BEFORE UPDATE ON kund_session_capacity "
        "FOR EACH ROW EXECUTE FUNCTION fn_guard_kund_block();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_kund_session_capacity_block ON kund_session_capacity;")
    op.execute("DROP FUNCTION IF EXISTS fn_guard_kund_block();")
    op.drop_column("kund_session_capacity", "is_blocked")
    op.drop_constraint(op.f("ck_bookings_pincode_format"), "bookings", type_="check")
    op.execute("UPDATE bookings SET address = coalesce(address, ''), gotra = coalesce(gotra, ''), "
               "sankalp_purpose = coalesce(sankalp_purpose, ''), pincode = coalesce(pincode, '999999')")
    op.create_check_constraint(op.f("ck_bookings_pincode_format"), "bookings", "pincode ~ '^[1-9][0-9]{5}$'")
    for col in ("address", "pincode", "gotra", "sankalp_purpose"):
        op.alter_column("bookings", col, nullable=False)
    for name in ("ck_family_members_mobile_format", "ck_family_members_gender_valid", "ck_family_members_age_range"):
        op.drop_constraint(op.f(name), "family_members", type_="check")
    for col in ("mobile", "relationship", "gender", "age"):
        op.drop_column("family_members", col)
    op.drop_constraint(op.f("ck_event_sessions_slot_valid"), "event_sessions", type_="check")
    op.execute(
        "UPDATE event_sessions SET slot = 'EVENING', start_time = '16:00', end_time = '20:00' WHERE slot = 'AFTERNOON'"
    )
    op.execute("UPDATE event_sessions SET start_time = '07:00' WHERE slot = 'MORNING'")
    op.create_check_constraint(op.f("ck_event_sessions_slot_valid"), "event_sessions", "slot IN ('MORNING', 'EVENING')")
