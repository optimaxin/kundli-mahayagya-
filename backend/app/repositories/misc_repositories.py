"""Smaller repositories: QR passes, staff users, audit log, idempotency records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import clock
from app.models import AdminUser, AuditLog, IdempotencyRecord, QrPass
from app.models.enums import IdempotencyStatus


class QrRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def by_hash(self, token_hash: str) -> QrPass | None:
        return self.db.scalars(select(QrPass).where(QrPass.token_hash == token_hash)).first()

    def active_for_booking(self, booking_id: int) -> QrPass | None:
        return self.db.scalars(
            select(QrPass).where(QrPass.booking_id == booking_id, QrPass.is_active.is_(True))
        ).first()

    def deactivate_for_booking(self, booking_id: int, *, actor_id: uuid.UUID | None, reason: str) -> int:
        result = self.db.execute(
            update(QrPass)
            .where(QrPass.booking_id == booking_id, QrPass.is_active.is_(True))
            .values(is_active=False, revoked_at=clock.now(), revoked_by=actor_id, revoked_reason=reason)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)

    def insert(self, *, booking_id: int, token_hash: str, expires_at: datetime, actor_id: uuid.UUID | None) -> int:
        return self.db.execute(
            insert(QrPass)
            .values(booking_id=booking_id, token_hash=token_hash, expires_at=expires_at, created_by=actor_id)
            .returning(QrPass.id)
        ).scalar_one()


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> AdminUser | None:
        return self.db.get(AdminUser, user_id)

    def by_email(self, email: str, *, for_update: bool = False) -> AdminUser | None:
        stmt = select(AdminUser).where(AdminUser.email == email.lower())
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.scalars(stmt).first()

    def list(self, *, role: str | None, offset: int, limit: int) -> tuple[int, list[AdminUser]]:
        stmt = select(AdminUser)
        if role:
            stmt = stmt.where(AdminUser.role == role)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        return total, list(self.db.scalars(stmt.order_by(AdminUser.created_at).offset(offset).limit(limit)))


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, **values: Any) -> None:
        self.db.execute(insert(AuditLog).values(**values))

    def list(
        self,
        *,
        action: str | None,
        entity_type: str | None,
        entity_id: str | None,
        actor_id: uuid.UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[int, list[AuditLog]]:
        stmt = select(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if actor_id:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list(self.db.scalars(stmt.order_by(AuditLog.id.desc()).offset(offset).limit(limit)))
        return total, rows


class IdempotencyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def claim(self, *, scope: str, key: str, request_hash: str, expires_at: datetime) -> int | None:
        """Insert a PROCESSING record. Returns its id, or None if the key already exists.

        If another in-flight transaction inserted the same key, PostgreSQL makes
        this INSERT wait for it to commit or roll back, so concurrent duplicates
        are serialised and never both proceed.
        """
        stmt = (
            pg_insert(IdempotencyRecord)
            .values(
                scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING.value,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=[IdempotencyRecord.scope, IdempotencyRecord.idempotency_key])
            .returning(IdempotencyRecord.id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get(self, *, scope: str, key: str) -> IdempotencyRecord | None:
        return self.db.scalars(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope, IdempotencyRecord.idempotency_key == key
            )
        ).first()

    def complete(
        self,
        record_id: int,
        *,
        response_status: int,
        payload: dict[str, Any],
        encrypted_secret: str | None,
        resource_id: int | None,
    ) -> None:
        self.db.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record_id)
            .values(
                status=IdempotencyStatus.COMPLETED.value,
                response_status=response_status,
                response_payload=payload,
                encrypted_secret=encrypted_secret,
                resource_id=resource_id,
            )
            .execution_options(synchronize_session=False)
        )

    def purge_secrets(self) -> int:
        """Drop encrypted replay secrets and expired records (run periodically)."""
        now = clock.now()
        result = self.db.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.expires_at < now, IdempotencyRecord.encrypted_secret.is_not(None))
            .values(encrypted_secret=None)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)
