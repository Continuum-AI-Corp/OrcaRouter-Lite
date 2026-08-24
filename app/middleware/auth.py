"""Auth middleware — API-key validation against the api_keys table.

Single-tenant edition: drops the SaaS middleware's session-token branch,
admin lookup, and per-IP fail-closed throttle. The brute-force surface
is the operator's own machine, so the throttle would block legitimate
local development for no security benefit.

Native-protocol support: the same sk-orca-* key is accepted from every
location the major SDKs put credentials in — `Authorization: Bearer`
(OpenAI SDKs, Claude Code's ANTHROPIC_AUTH_TOKEN), `x-api-key`
(Anthropic SDK / Claude Code), `x-goog-api-key` (google-genai SDK), and
`?key=` (legacy google-generativeai style; scoped to /v1beta/ so
credentials stay out of URLs everywhere else). Auth failures render in
the error envelope the caller's SDK expects (see `_error_payload`).
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from packages.auth.key_validator import AuthError, validate_api_key
from packages.db import session as session_mod

SKIP_AUTH_PATHS: set[str] = {
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}

SKIP_AUTH_PREFIXES: tuple[str, ...] = ("/static",)

# Prefixes that REQUIRE auth; anything else (outside the public allowlist)
# is static-SPA territory. NOTE: "/v1/" does NOT match "/v1beta/..." — the
# Gemini surface needs its own entry or it would be waved through as
# "static" with no credential check at all.
GUARDED_PREFIXES: tuple[str, ...] = ("/api/", "/v1/", "/v1beta/")


def _is_public(path: str) -> bool:
    if path in SKIP_AUTH_PATHS:
        return True
    return any(path.startswith(p) for p in SKIP_AUTH_PREFIXES)


def _is_static(path: str) -> bool:
    return not any(path.startswith(p) for p in GUARDED_PREFIXES)


def _get_header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for k, v in headers:
        if k == name:
            return v.decode()
    return ""


def _extract_credential(scope) -> str | None:
    """Pull the sk-orca-* key from wherever the client's SDK put it.

    Precedence: `Authorization: Bearer` → `x-api-key` → `x-goog-api-key`
    → `?key=` (the query-param form only on /v1beta/ paths, matching the
    legacy Google SDK that uses it, so credentials-in-URL stays contained).
    An empty Bearer token (e.g. a proxy that blanks the header) falls
    through to the other locations instead of short-circuiting the chain.
    """
    headers = scope.get("headers", [])
    auth_header = _get_header(headers, b"authorization")
    if auth_header.startswith("Bearer ") and auth_header[7:]:
        return auth_header[7:]
    for name in (b"x-api-key", b"x-goog-api-key"):
        val = _get_header(headers, name)
        if val:
            return val
    if scope.get("path", "").startswith("/v1beta/"):
        qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        vals = qs.get("key")
        if vals and vals[0]:
            return vals[0]
    return None


_ANTHROPIC_ERROR_TYPES = {401: "authentication_error", 403: "permission_error"}
_GOOGLE_STATUSES = {401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 503: "UNAVAILABLE"}


def _error_payload(path: str, status: int, message: str, error_type: str) -> bytes:
    """Render the auth error in the envelope the caller's SDK expects."""
    if path.startswith("/v1/messages"):
        body: dict = {
            "type": "error",
            "error": {
                "type": _ANTHROPIC_ERROR_TYPES.get(status, "api_error"),
                "message": message,
            },
        }
    elif path.startswith("/v1beta/"):
        body = {
            "error": {
                "code": status,
                "message": message,
                "status": _GOOGLE_STATUSES.get(status, "INTERNAL"),
            }
        }
    else:
        body = {"error": {"message": message, "type": error_type}}
    return json.dumps(body).encode()


async def _send_error(send, path: str, status: int, message: str, error_type: str) -> None:
    body = _error_payload(path, status, message, error_type)
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

        raw_key = _extract_credential(scope)
        if not raw_key:
            await _send_error(
                send, path, 401,
                "Missing or invalid API key. Send it as 'Authorization: Bearer', "
                "'x-api-key', or 'x-goog-api-key'.",
                "auth_error",
            )
            return

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
            await _send_error(send, path, e.status_code, e.message, "auth_error")
            return
        except Exception:
            await _send_error(send, path, 503, "Service temporarily unavailable", "server_error")
            return

        await self.app(scope, receive, send)
