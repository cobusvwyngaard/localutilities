"""Request checks for the engine (DESIGN.md §6.2).

Two layers:

* `LoopbackGuardMiddleware` wraps the whole app. It rejects any connection that is not from
  loopback, any `Host` header other than 127.0.0.1:<port> / localhost:<port> (DNS rebinding),
  answers CORS preflights for `/api/*` from allowed origins only, and adds security headers.
  It covers the UI too, because the served index.html carries the API token.
* `require_api_access` is the shared dependency every `/api/*` route uses (it is attached to
  the API router): Host, Origin allow-list and bearer token. New routes must not reimplement it.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException, Request, status

from werkbank_engine.config import Settings

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD"})

# The engine UI loads only its own files. Phase 2 (WASM, CDN cores) will need to extend this.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"cross-origin-resource-policy", b"same-origin"),
)
CORS_ALLOW_METHODS = b"GET, POST, DELETE"
CORS_ALLOW_HEADERS = b"authorization, content-type"


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _host_allowed(host: str | None, settings: Settings) -> bool:
    return host is not None and host.lower() in settings.allowed_hosts


async def _plain(send: Send, code: int, body: bytes, extra: list[tuple[bytes, bytes]] | None = None) -> None:
    headers = [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]
    headers += list(SECURITY_HEADERS) + (extra or [])
    await send({"type": "http.response.start", "status": code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class LoopbackGuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # no websockets
            return

        client = scope.get("client")
        if client is None or client[0] not in LOOPBACK_ADDRESSES:
            await _plain(send, 403, b"Forbidden: the Werkbank engine only accepts local connections.")
            return
        if not _host_allowed(_header(scope, b"host"), self.settings):
            await _plain(send, 403, b"Forbidden host.")
            return

        path: str = scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        origin = _header(scope, b"origin")
        origin_allowed = origin is not None and origin in self.settings.allowed_origins

        if is_api and scope["method"] == "OPTIONS":
            # CORS preflight (Mode B: the hosted UI calling the engine). No token is sent here.
            if not origin_allowed or _header(scope, b"access-control-request-method") is None:
                await _plain(send, 403, b"Forbidden origin.")
                return
            extra = [
                (b"access-control-allow-origin", origin.encode()),
                (b"access-control-allow-methods", CORS_ALLOW_METHODS),
                (b"access-control-allow-headers", CORS_ALLOW_HEADERS),
                (b"access-control-max-age", b"600"),
                (b"vary", b"origin"),
            ]
            if _header(scope, b"access-control-request-private-network") == "true":
                extra.append((b"access-control-allow-private-network", b"true"))
            await _plain(send, 204, b"", extra)
            return

        if is_api and origin is not None and not origin_allowed:
            await _plain(send, 403, b"Forbidden origin.")
            return
        if is_api and origin is None and scope["method"] not in SAFE_METHODS:
            await _plain(send, 403, b"Forbidden: state-changing requests need an allowed Origin header.")
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                if is_api:
                    headers.append((b"cache-control", b"no-store"))
                    if origin_allowed:
                        headers += [(b"access-control-allow-origin", origin.encode()), (b"vary", b"origin")]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def require_api_access(request: Request) -> None:
    """Shared dependency for every /api/* route: Host, Origin allow-list, bearer token."""
    settings: Settings = request.app.state.settings

    if not _host_allowed(request.headers.get("host"), settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden host.")

    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden origin.")
    if origin is None and request.method not in SAFE_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing Origin header on a state-changing request.")

    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        credentials.strip().encode(), settings.token.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or wrong token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
