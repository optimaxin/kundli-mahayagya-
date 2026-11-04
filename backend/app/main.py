"""FastAPI application factory.

Run locally:   uvicorn app.main:app --reload
Production:    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 \
                   --proxy-headers --forwarded-allow-ips=<load balancer IPs>
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import get_engine, reset_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import build_registration_admission
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

API_DESCRIPTION = """
Backend for **2151 Kundiya Mahayagya** (14-21 December 2026): family registration,
best-fit Kund allocation, QR passes, per-member check-in, admin and reporting.

* All responses use the envelope `{"success": true, "data": ..., "meta": ...}` or
  `{"success": false, "error": {"code", "message", "details"}, "request_id"}`.
* Staff endpoints need `Authorization: Bearer <JWT>` from `POST /api/v1/auth/login`.
* `POST /api/v1/registrations` requires an `Idempotency-Key` header.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_JSON)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        get_engine()
        app.state.registration_admission = build_registration_admission()
        yield
        reset_engine()

    docs = settings.ENABLE_DOCS
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description=API_DESCRIPTION,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    # Order: the LAST added middleware is the OUTERMOST.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Idempotent-Replayed", "Retry-After"],
        max_age=600,
    )
    if settings.TRUSTED_HOSTS and settings.TRUSTED_HOSTS != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.ENABLE_HSTS)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
    def platform_health() -> dict[str, str]:
        """Dependency-free liveness probe at the root path, the default for Render and most load balancers.
        (Database readiness is checked by /api/v1/health/ready.)"""
        return {"status": "ok"}

    return app


app = create_app()
