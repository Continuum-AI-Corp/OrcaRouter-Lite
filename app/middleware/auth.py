"""Auth middleware — bearer-token validation against the api_keys table.

Single-tenant edition: drops the SaaS middleware's session-token branch,
admin lookup, and per-IP fail-closed throttle. The brute-force surface
is the operator's own machine, so the throttle would block legitimate
local development for no security benefit.
"""

from __future__ import annotations

import json

import structlog

from packages.auth.key_validator import AuthError, validate_api_key
from packages.db import session as session_mod

logger = structlog.get_logger()

SKIP_AUTH_PATHS: set[str] = {
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}

SKIP_AUTH_PREFIXES: tuple[str, ...] = ("/static",)


def _is_public(path: str) -> bool:
    if path in SKIP_AUTH_PATHS:
        return True
    return any(path.startswith(p) for p in SKIP_AUTH_PREFIXES)


def _is_static(path: str) -> bool:
    return not (path.startswith("/api/") or path.startswith("/v1/"))


def _get_header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for k, v in headers:
        if k == name:
            return v.decode()
    return ""


async def _send_error(send, status: int, message: str, error_type: str) -> None:
    body = json.dumps({"error": {"message": message, "type": error_type}}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if _is_public(path) or _is_static(path):
            await self.app(scope, receive, send)
            return

        auth_header = _get_header(scope.get("headers", []), b"authorization")
        if not auth_header.startswith("Bearer "):
            await _send_error(send, 401, "Missing or invalid Authorization header", "auth_error")
            return

        raw_key = auth_header[7:]

        # Use the session factory directly with `async with` so the
        # session is GUARANTEED to close on every exit path (success,
        # AuthError, generic Exception). The previous
        # `async for s in get_session(): break` pattern relied on
        # Python's implicit generator cleanup, which is timing-fragile:
        # in error paths the session could linger until GC and slowly
        # exhaust the connection pool under load.
        if session_mod._session_factory is None:
            from app.config import get_settings
            session_mod.init_session_factory(get_settings().database_url)
        try:
            async with session_mod._session_factory() as session:
                key_context = await validate_api_key(raw_key, session)
            scope.setdefault("state", {})["key_context"] = key_context
            scope.setdefault("state", {})["workspace_id"] = key_context.workspace_id
        except AuthError as e:
            await _send_error(send, e.status_code, e.message, "auth_error")
            return
        except Exception:
            # A DB failure during key validation must be visible — without
            # this log the operator only sees unexplained 503s.
            logger.exception("auth_middleware_error", path=path)
            await _send_error(send, 503, "Service temporarily unavailable", "server_error")
            return

        await self.app(scope, receive, send)
