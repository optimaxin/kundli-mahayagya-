"""Close the 14 December 2026 MORNING session (08:00-11:00) to new bookings.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16

Data-only migration: no schema change. It reuses the existing session-level closure
(``event_sessions.status = 'CLOSED'``, the same state the admin ``PATCH /sessions/{id}`` sets), which the
booking validation and the allocation service already refuse. The public site shows such a session as
"सत्र पूर्ण" / "Session Full" with a lock.

* Only that one session is touched: ``event_date = 2026-12-14 AND slot = 'MORNING'``. Every other date and
  the 14 December AFTERNOON session are unaffected.
* Only NEW bookings are blocked. No booking, reservation, QR pass, check-in, audit or capacity row is read
  or written, so existing families keep their valid passes and can still be checked in.
* Idempotent: it only changes a row that is still SCHEDULED, so re-running it is a no-op, and it never
  overrides a status an administrator has since set (e.g. COMPLETED). It writes one audit row only when it
  actually closes the session.
* If the database is empty (migrated before ``seed_all``), nothing matches. ``seed_sessions`` then creates
  that session already CLOSED (see ``app/services/seed_service.py``), so a fresh environment is locked too.

Downgrade is deliberately a no-op: a rollback must never silently re-open a closed session. To re-open it
on purpose, an ADMIN sends ``PATCH /api/v1/sessions/1 {"status": "SCHEDULED"}``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCKED_EVENT_DATE = "2026-12-14"
LOCKED_SLOT = "MORNING"

LOCK_SQL = f"""
WITH locked AS (
    UPDATE event_sessions
       SET status = 'CLOSED', updated_at = now()
     WHERE event_date = DATE '{LOCKED_EVENT_DATE}'
       AND slot = '{LOCKED_SLOT}'
       AND status = 'SCHEDULED'
 RETURNING id
)
INSERT INTO audit_logs (actor_role, action, entity_type, entity_id, previous_values, new_values)
SELECT 'SYSTEM', 'SESSION_UPDATED', 'event_session', id::text,
       '{{"status": "SCHEDULED"}}'::jsonb,
       '{{"status": "CLOSED", "reason": "Session full: closed to new bookings (migration 0004)"}}'::jsonb
  FROM locked
"""


def upgrade() -> None:
    op.execute(LOCK_SQL)


def downgrade() -> None:
    # Intentionally empty: see the module docstring.
    pass
