"""Audit logging and request context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.misc_repositories import AuditRepository


@dataclass(frozen=True)
class RequestContext:
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None
    request_id: str | None = None

    @classmethod
    def system(cls, request_id: str | None = None) -> RequestContext:
        return cls(actor_id=None, actor_role="SYSTEM", request_id=request_id)


def audit(
    db: Session,
    ctx: RequestContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None,
    previous: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
) -> None:
    """Write an audit row in the caller's transaction (atomic with the change).

    Audit payloads must not contain raw secrets; personal data is limited to
    what an authorised reviewer needs (booking numbers, ids, statuses).
    """
    AuditRepository(db).add(
        actor_id=ctx.actor_id,
        actor_role=ctx.actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        previous_values=previous,
        new_values=new,
        request_id=ctx.request_id,
    )
