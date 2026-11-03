"""Rate limiting and registration admission control.

Rate limiting
    Fixed-window counters keyed by (rule, client key). The in-memory backend is
    per-process; in multi-worker / multi-instance deployments use the Redis
    backend (``RATE_LIMIT_BACKEND=redis``) and an edge WAF/CDN rate limit.
    Rate-limit state is *not* business state - PostgreSQL remains the source
    of truth for capacity.

Admission control
    A bounded semaphore in front of the registration endpoint. It caps the
    number of registrations a worker runs concurrently (protecting the DB
    connection pool) and the number waiting; excess requests get a fast 503
    with ``Retry-After`` instead of piling up.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import ServiceBusy, TooManyRequests

logger = logging.getLogger("app.ratelimit")

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


@dataclass(frozen=True)
class RateSpec:
    limit: int
    window_seconds: int

    @classmethod
    def parse(cls, spec: str) -> RateSpec:
        count, _, unit = spec.partition("/")
        unit = unit.strip().lower().rstrip("s")
        if unit not in _UNITS:
            raise ValueError(f"Invalid rate limit spec: {spec!r}")
        return cls(limit=int(count), window_seconds=_UNITS[unit])


class MemoryBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, spec: RateSpec) -> tuple[bool, int]:
        now = time.time()
        window_start = math.floor(now / spec.window_seconds) * spec.window_seconds
        reset_at = window_start + spec.window_seconds
        bucket = f"{key}:{int(window_start)}"
        with self._lock:
            count, _ = self._counters.get(bucket, (0, reset_at))
            count += 1
            self._counters[bucket] = (count, reset_at)
            if len(self._counters) > 50_000:
                self._counters = {k: v for k, v in self._counters.items() if v[1] > now}
        return count <= spec.limit, max(1, int(reset_at - now))

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


class RedisBackend:  # pragma: no cover - exercised only when Redis is configured
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, socket_timeout=0.5)

    def hit(self, key: str, spec: RateSpec) -> tuple[bool, int]:
        now = time.time()
        window_start = int(now // spec.window_seconds) * spec.window_seconds
        bucket = f"rl:{key}:{window_start}"
        try:
            pipe = self._client.pipeline()
            pipe.incr(bucket)
            pipe.expire(bucket, spec.window_seconds + 1)
            count, _ = pipe.execute()
        except Exception:  # fail open on limiter outage, but log it
            logger.warning("rate_limit_backend_unavailable")
            return True, 1
        return int(count) <= spec.limit, max(1, int(window_start + spec.window_seconds - now))

    def reset(self) -> None:
        pass


_backend: MemoryBackend | RedisBackend | None = None


def get_backend() -> MemoryBackend | RedisBackend:
    global _backend
    if _backend is None:
        settings = get_settings()
        _backend = RedisBackend(settings.REDIS_URL) if settings.RATE_LIMIT_BACKEND == "redis" else MemoryBackend()
    return _backend


def reset_rate_limits() -> None:
    get_backend().reset()


def client_ip(request: Request) -> str:
    # Run uvicorn with --proxy-headers --forwarded-allow-ips=<LB IPs> behind a proxy,
    # so request.client reflects the real client address.
    return request.client.host if request.client else "unknown"


def rate_limit(rule: str, spec_setting: str) -> Callable[[Request], None]:
    """FastAPI dependency factory: ``Depends(rate_limit("login", "RATE_LIMIT_LOGIN"))``."""

    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            return
        spec = RateSpec.parse(getattr(settings, spec_setting))
        allowed, retry_after = get_backend().hit(f"{rule}:{client_ip(request)}", spec)
        if not allowed:
            raise TooManyRequests(
                "Too many requests. Please slow down.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


def check_rate(rule: str, key: str, spec_setting: str) -> None:
    """Imperative rate check for non-IP keys (e.g. per account or per booking number)."""
    settings = get_settings()
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry_after = get_backend().hit(f"{rule}:{key}", RateSpec.parse(getattr(settings, spec_setting)))
    if not allowed:
        raise TooManyRequests("Too many attempts. Please try later.", headers={"Retry-After": str(retry_after)})


class AdmissionController:
    """Bounded concurrency + bounded queue for expensive endpoints."""

    def __init__(self, max_concurrency: int, max_queue: int, timeout_seconds: float) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)
        self._max_queue = max_queue
        self._timeout = timeout_seconds
        self._waiting = 0

    async def run(self, fn: Callable[[], Awaitable[object]]) -> object:
        if self._sem.locked() and self._waiting >= self._max_queue:
            raise ServiceBusy("Registration queue is full. Please retry shortly.", headers={"Retry-After": "5"})
        self._waiting += 1
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except TimeoutError as exc:
            raise ServiceBusy(
                "Registration is under heavy load. Please retry shortly.", headers={"Retry-After": "5"}
            ) from exc
        finally:
            self._waiting -= 1
        try:
            return await fn()
        finally:
            self._sem.release()


def build_registration_admission() -> AdmissionController:
    s = get_settings()
    return AdmissionController(
        s.REGISTRATION_MAX_CONCURRENCY, s.REGISTRATION_MAX_QUEUE, s.REGISTRATION_QUEUE_TIMEOUT_SECONDS
    )


def registration_admission(request: Request) -> AdmissionController:
    """Per-application (per event loop) controller, created lazily on app.state."""
    controller = getattr(request.app.state, "registration_admission", None)
    if controller is None:
        controller = build_registration_admission()
        request.app.state.registration_admission = controller
    return controller
