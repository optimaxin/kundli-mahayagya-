"""Database engine, session factory and transaction helpers.

PostgreSQL is the single source of truth for Kund capacity. Writes that touch
capacity go through :func:`run_transaction`, which

* applies a transaction-local ``lock_timeout`` so that lock contention fails
  fast instead of piling up connections,
* retries the whole unit of work on transient concurrency errors
  (deadlock, serialization failure, lock timeout) with jittered backoff,
* never retries business errors (``AppError``) and always rolls back on error.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import ServiceBusy

logger = logging.getLogger("app.db")

T = TypeVar("T")

TRANSIENT_SQLSTATES = {
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "55P03",  # lock_not_available (lock_timeout)
}

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def build_engine(url: str | None = None, **overrides: Any) -> Engine:
    settings = get_settings()
    connect_args: dict[str, Any] = {"application_name": "mahayagya-api"}
    if settings.DB_DISABLE_PREPARED_STATEMENTS:
        # Required behind PgBouncer/Supavisor in transaction mode.
        connect_args["prepare_threshold"] = None
    kwargs: dict[str, Any] = dict(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
        echo=settings.DB_ECHO,
        connect_args=connect_args,
    )
    kwargs.update(overrides)
    engine = create_engine(url or settings.DATABASE_URL, **kwargs)

    statement_timeout = int(settings.DB_STATEMENT_TIMEOUT_MS)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - trivial
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {statement_timeout}")
            cur.execute("SET TIME ZONE 'UTC'")
        dbapi_conn.commit()

    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = build_engine()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine() -> None:
    """Dispose the global engine (used by tests and graceful shutdown)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def sqlstate_of(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(exc, "sqlstate", None)


def is_transient(exc: BaseException) -> bool:
    return sqlstate_of(exc) in TRANSIENT_SQLSTATES


def set_local_lock_timeout(db: Session, ms: int | None = None) -> None:
    value = str(ms if ms is not None else get_settings().DB_LOCK_TIMEOUT_MS)
    db.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": value})


def run_transaction(
    db: Session,
    work: Callable[[Session], T],
    *,
    retries: int | None = None,
    lock_timeout_ms: int | None = None,
    label: str = "tx",
) -> T:
    """Run ``work`` inside a transaction, committing on success.

    The callable must be safe to re-run from scratch (it is re-executed on
    transient errors after a full rollback).
    """
    max_retries = get_settings().ALLOCATION_MAX_RETRIES if retries is None else retries
    attempt = 0
    while True:
        try:
            # Start every attempt from fresh database state (objects loaded by an
            # earlier, rolled-back attempt or an earlier transaction are expired).
            db.expire_all()
            set_local_lock_timeout(db, lock_timeout_ms)
            result = work(db)
            db.commit()
            return result
        except DBAPIError as exc:
            db.rollback()
            if is_transient(exc):
                if attempt < max_retries:
                    attempt += 1
                    delay = min(0.05 * (2**attempt), 1.0) * (0.5 + random.random())  # noqa: S311 - retry jitter, not crypto
                    logger.warning(
                        "transient_db_error_retry",
                        extra={"label": label, "attempt": attempt, "sqlstate": sqlstate_of(exc)},
                    )
                    time.sleep(delay)
                    continue
                raise ServiceBusy(
                    "The system is busy processing other requests. Please retry shortly.",
                    headers={"Retry-After": "2"},
                ) from exc
            raise
        except BaseException:
            db.rollback()
            raise
