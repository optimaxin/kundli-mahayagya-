"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-03 22:29:36.398723

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tables, keys, constraints and indexes (generated from app.models, reviewed).
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('actor_role', sa.String(length=16), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('previous_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('new_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_actor', 'audit_logs', ['actor_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)
    op.create_table('bookings',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('booking_number', sa.String(length=20), nullable=False),
    sa.Column('coordinator_name', sa.String(length=100), nullable=False),
    sa.Column('primary_mobile', sa.String(length=10), nullable=False),
    sa.Column('secondary_mobile', sa.String(length=10), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('address', sa.String(length=300), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('state', sa.String(length=60), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=False),
    sa.Column('gotra', sa.String(length=60), nullable=False),
    sa.Column('sankalp_purpose', sa.String(length=500), nullable=False),
    sa.Column('member_count', sa.SmallInteger(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default=sa.text("'CONFIRMED'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("pincode ~ '^[1-9][0-9]{5}$'", name=op.f('ck_bookings_pincode_format')),
    sa.CheckConstraint("primary_mobile ~ '^[6-9][0-9]{9}$'", name=op.f('ck_bookings_primary_mobile_format')),
    sa.CheckConstraint("secondary_mobile IS NULL OR secondary_mobile ~ '^[6-9][0-9]{9}$'", name=op.f('ck_bookings_secondary_mobile_format')),
    sa.CheckConstraint("status IN ('CONFIRMED', 'CANCELLED')", name=op.f('ck_bookings_status_valid')),
    sa.CheckConstraint('member_count BETWEEN 1 AND 8', name=op.f('ck_bookings_member_count_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings')),
    sa.UniqueConstraint('booking_number', name=op.f('uq_bookings_booking_number')),
    sa.UniqueConstraint('id', 'member_count', name='uq_bookings_id_member_count')
    )
    op.create_index('ix_bookings_created_at', 'bookings', ['created_at'], unique=False)
    op.create_index('ix_bookings_primary_mobile', 'bookings', ['primary_mobile'], unique=False)
    op.create_index('ix_bookings_status', 'bookings', ['status'], unique=False)
    op.create_table('event_sessions',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('slot', sa.String(length=10), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default=sa.text("'SCHEDULED'"), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("slot IN ('MORNING', 'EVENING')", name=op.f('ck_event_sessions_slot_valid')),
    sa.CheckConstraint("status IN ('SCHEDULED', 'CLOSED', 'COMPLETED', 'CANCELLED')", name=op.f('ck_event_sessions_status_valid')),
    sa.CheckConstraint('end_time > start_time', name=op.f('ck_event_sessions_time_order')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event_sessions')),
    sa.UniqueConstraint('event_date', 'slot', name='uq_event_sessions_date_slot')
    )
    op.create_table('idempotency_records',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('scope', sa.String(length=50), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('response_status', sa.SmallInteger(), nullable=True),
    sa.Column('response_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('encrypted_secret', sa.Text(), nullable=True),
    sa.Column('resource_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('PROCESSING', 'COMPLETED')", name=op.f('ck_idempotency_records_status_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_records')),
    sa.UniqueConstraint('scope', 'idempotency_key', name='uq_idempotency_records_scope_key')
    )
    op.create_index('ix_idempotency_records_expires_at', 'idempotency_records', ['expires_at'], unique=False)
    op.create_table('kunds',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('kund_number', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('kund_number > 0', name=op.f('ck_kunds_kund_number_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kunds')),
    sa.UniqueConstraint('kund_number', name=op.f('uq_kunds_kund_number'))
    )
    op.create_table('offline_checkin_events',
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('booking_number', sa.String(length=20), nullable=False),
    sa.Column('member_number', sa.SmallInteger(), nullable=False),
    sa.Column('scanner_id', sa.Uuid(), nullable=True),
    sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sync_result', sa.String(length=32), nullable=True),
    sa.Column('sync_detail', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_offline_checkin_events')),
    sa.UniqueConstraint('session_id', 'booking_number', 'member_number', name='uq_offline_checkin_session_booking_member')
    )
    op.create_index('ix_offline_checkin_events_unsynced', 'offline_checkin_events', ['synced_at'], unique=False)
    op.create_table('offline_roster_entries',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('booking_number', sa.String(length=20), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('reservation_status', sa.String(length=16), nullable=False),
    sa.Column('kund_number', sa.Integer(), nullable=False),
    sa.Column('members', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('snapshot_version', sa.String(length=64), nullable=False),
    sa.Column('loaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_offline_roster_entries')),
    sa.UniqueConstraint('session_id', 'booking_number', name='uq_offline_roster_session_booking'),
    sa.UniqueConstraint('session_id', 'token_hash', name='uq_offline_roster_session_token')
    )
    op.create_table('offline_sync_receipts',
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('node_id', sa.String(length=64), nullable=False),
    sa.Column('result', sa.String(length=32), nullable=False),
    sa.Column('detail', sa.String(length=200), nullable=True),
    sa.Column('checkin_id', sa.BigInteger(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_offline_sync_receipts'))
    )
    op.create_table('admin_users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('assigned_session_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('token_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('failed_login_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('ADMIN', 'SUPERVISOR', 'SCANNER')", name=op.f('ck_admin_users_role_valid')),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_admin_users_email_lowercase')),
    sa.ForeignKeyConstraint(['assigned_session_id'], ['event_sessions.id'], name='fk_admin_users_assigned_session'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_users')),
    sa.UniqueConstraint('email', name=op.f('uq_admin_users_email'))
    )
    op.create_index('ix_admin_users_role', 'admin_users', ['role'], unique=False)
    op.create_table('family_members',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('booking_id', sa.BigInteger(), nullable=False),
    sa.Column('member_number', sa.SmallInteger(), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('member_number BETWEEN 1 AND 8', name=op.f('ck_family_members_member_number_range')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name='fk_family_members_booking'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_family_members')),
    sa.UniqueConstraint('booking_id', 'member_number', name='uq_family_members_booking_member_number'),
    sa.UniqueConstraint('id', 'booking_id', name='uq_family_members_id_booking')
    )
    op.create_table('kund_session_capacity',
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('kund_id', sa.Integer(), nullable=False),
    sa.Column('capacity', sa.SmallInteger(), server_default=sa.text('8'), nullable=False),
    sa.Column('reserved_count', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('capacity BETWEEN 1 AND 8', name=op.f('ck_kund_session_capacity_capacity_range')),
    sa.CheckConstraint('reserved_count >= 0 AND reserved_count <= capacity', name=op.f('ck_kund_session_capacity_reserved_within_capacity')),
    sa.ForeignKeyConstraint(['kund_id'], ['kunds.id'], name='fk_ksc_kund'),
    sa.ForeignKeyConstraint(['session_id'], ['event_sessions.id'], name='fk_ksc_session'),
    sa.PrimaryKeyConstraint('session_id', 'kund_id', name=op.f('pk_kund_session_capacity'))
    )
    op.create_index('ix_ksc_best_fit', 'kund_session_capacity', ['session_id', sa.text('(capacity - reserved_count)'), 'kund_id'], unique=False, postgresql_where=sa.text('reserved_count < capacity'))
    op.create_index('ix_ksc_kund', 'kund_session_capacity', ['kund_id'], unique=False)
    op.create_table('qr_passes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('booking_id', sa.BigInteger(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.Uuid(), nullable=True),
    sa.Column('revoked_reason', sa.String(length=200), nullable=True),
    sa.CheckConstraint('char_length(token_hash) = 64', name=op.f('ck_qr_passes_token_hash_sha256')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name='fk_qr_passes_booking'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_qr_passes')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_qr_passes_token_hash'))
    )
    op.create_index('ix_qr_passes_booking', 'qr_passes', ['booking_id'], unique=False)
    op.create_index('uq_qr_passes_one_active_per_booking', 'qr_passes', ['booking_id'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('booking_sessions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('booking_id', sa.BigInteger(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('kund_id', sa.Integer(), nullable=False),
    sa.Column('member_count', sa.SmallInteger(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default=sa.text("'CONFIRMED'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('CONFIRMED', 'CANCELLED')", name=op.f('ck_booking_sessions_status_valid')),
    sa.CheckConstraint('member_count BETWEEN 1 AND 8', name=op.f('ck_booking_sessions_member_count_range')),
    sa.ForeignKeyConstraint(['booking_id', 'member_count'], ['bookings.id', 'bookings.member_count'], name='fk_booking_sessions_booking_member_count'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name='fk_booking_sessions_booking'),
    sa.ForeignKeyConstraint(['kund_id'], ['kunds.id'], name='fk_booking_sessions_kund'),
    sa.ForeignKeyConstraint(['session_id', 'kund_id'], ['kund_session_capacity.session_id', 'kund_session_capacity.kund_id'], name='fk_booking_sessions_capacity'),
    sa.ForeignKeyConstraint(['session_id'], ['event_sessions.id'], name='fk_booking_sessions_session'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_sessions')),
    sa.UniqueConstraint('booking_id', 'session_id', name='uq_booking_sessions_booking_session'),
    sa.UniqueConstraint('id', 'booking_id', name='uq_booking_sessions_id_booking')
    )
    op.create_index('ix_booking_sessions_session_kund', 'booking_sessions', ['session_id', 'kund_id'], unique=False)
    op.create_index('ix_booking_sessions_session_status', 'booking_sessions', ['session_id', 'status'], unique=False)
    op.create_table('report_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('report_type', sa.String(length=16), nullable=False),
    sa.Column('report_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("report_type IN ('DAILY', 'FINAL')", name=op.f('ck_report_jobs_type_valid')),
    sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name=op.f('ck_report_jobs_status_valid')),
    sa.ForeignKeyConstraint(['requested_by'], ['admin_users.id'], name='fk_report_jobs_requested_by'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_jobs'))
    )
    op.create_index('ix_report_jobs_created_at', 'report_jobs', ['created_at'], unique=False)
    op.create_table('attendance_checkins',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('booking_session_id', sa.BigInteger(), nullable=False),
    sa.Column('booking_id', sa.BigInteger(), nullable=False),
    sa.Column('member_id', sa.BigInteger(), nullable=False),
    sa.Column('scanner_id', sa.Uuid(), nullable=True),
    sa.Column('source', sa.String(length=16), server_default=sa.text("'ONLINE'"), nullable=False),
    sa.Column('offline_node_id', sa.String(length=64), nullable=True),
    sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('ONLINE', 'OFFLINE_SYNC')", name=op.f('ck_attendance_checkins_source_valid')),
    sa.ForeignKeyConstraint(['booking_session_id', 'booking_id'], ['booking_sessions.id', 'booking_sessions.booking_id'], name='fk_attendance_checkins_booking_session'),
    sa.ForeignKeyConstraint(['member_id', 'booking_id'], ['family_members.id', 'family_members.booking_id'], name='fk_attendance_checkins_member'),
    sa.ForeignKeyConstraint(['scanner_id'], ['admin_users.id'], name='fk_attendance_checkins_scanner'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_checkins')),
    sa.UniqueConstraint('booking_session_id', 'member_id', name='uq_attendance_checkins_session_member'),
    sa.UniqueConstraint('event_id', name=op.f('uq_attendance_checkins_event_id'))
    )
    op.create_index('ix_attendance_checkins_booking', 'attendance_checkins', ['booking_id'], unique=False)
    op.create_index('ix_attendance_checkins_checked_in_at', 'attendance_checkins', ['checked_in_at'], unique=False)
    op.create_table('cancellation_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('booking_session_id', sa.BigInteger(), nullable=False),
    sa.Column('booking_id', sa.BigInteger(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('kund_id', sa.Integer(), nullable=False),
    sa.Column('released_member_count', sa.SmallInteger(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['admin_users.id'], name='fk_cancellation_events_actor'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name='fk_cancellation_events_booking'),
    sa.ForeignKeyConstraint(['booking_session_id'], ['booking_sessions.id'], name='fk_cancellation_events_booking_session'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cancellation_events')),
    sa.UniqueConstraint('booking_session_id', name='uq_cancellation_events_booking_session')
    )
    op.create_index('ix_cancellation_events_booking', 'cancellation_events', ['booking_id'], unique=False)



def downgrade() -> None:
    # Tables, keys, constraints and indexes (generated from app.models, reviewed).
    op.drop_index('ix_cancellation_events_booking', table_name='cancellation_events')
    op.drop_table('cancellation_events')
    op.drop_index('ix_attendance_checkins_checked_in_at', table_name='attendance_checkins')
    op.drop_index('ix_attendance_checkins_booking', table_name='attendance_checkins')
    op.drop_table('attendance_checkins')
    op.drop_index('ix_report_jobs_created_at', table_name='report_jobs')
    op.drop_table('report_jobs')
    op.drop_index('ix_booking_sessions_session_status', table_name='booking_sessions')
    op.drop_index('ix_booking_sessions_session_kund', table_name='booking_sessions')
    op.drop_table('booking_sessions')
    op.drop_index('uq_qr_passes_one_active_per_booking', table_name='qr_passes', postgresql_where=sa.text('is_active'))
    op.drop_index('ix_qr_passes_booking', table_name='qr_passes')
    op.drop_table('qr_passes')
    op.drop_index('ix_ksc_kund', table_name='kund_session_capacity')
    op.drop_index('ix_ksc_best_fit', table_name='kund_session_capacity', postgresql_where=sa.text('reserved_count < capacity'))
    op.drop_table('kund_session_capacity')
    op.drop_table('family_members')
    op.drop_index('ix_admin_users_role', table_name='admin_users')
    op.drop_table('admin_users')
    op.drop_table('offline_sync_receipts')
    op.drop_table('offline_roster_entries')
    op.drop_index('ix_offline_checkin_events_unsynced', table_name='offline_checkin_events')
    op.drop_table('offline_checkin_events')
    op.drop_table('kunds')
    op.drop_index('ix_idempotency_records_expires_at', table_name='idempotency_records')
    op.drop_table('idempotency_records')
    op.drop_table('event_sessions')
    op.drop_index('ix_bookings_status', table_name='bookings')
    op.drop_index('ix_bookings_primary_mobile', table_name='bookings')
    op.drop_index('ix_bookings_created_at', table_name='bookings')
    op.drop_table('bookings')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_table('audit_logs')

