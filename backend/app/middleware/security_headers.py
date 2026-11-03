"""Secure HTTP response headers."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DOCS_PREFIXES = ("/docs", "/redoc", "/openapi.json")

_API_CSP = b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
# Swagger UI / ReDoc load assets from jsdelivr.
_DOCS_CSP = (
    b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    b"https://fastapi.tiangolo.com; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, enable_hsts: bool = False) -> None:
        self.app = app
        self.enable_hsts = enable_hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        is_docs = path.startswith(_DOCS_PREFIXES)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {b"server", b"x-powered-by"}
                ]
                existing = {k.lower() for k, _ in headers}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"content-security-policy", _DOCS_CSP if is_docs else _API_CSP),
                ]
                if b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                if self.enable_hsts:
                    extra.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                headers.extend(h for h in extra if h[0] not in existing)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
