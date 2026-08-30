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

import structlog

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
            # Lenient decode: a raw non-UTF-8 byte in a credential header is
            # an unauthenticated, remotely reachable input — it must end as
            # a clean 401 for a key that can never validate, not as an
            # unhandled 500 out of the middleware.
            return v.decode("utf-8", "replace")
    return ""


def _extract_credentials(scope) -> list[str]:
    """Collect the candidate sk-orca-* keys the client's SDK may have
    sent, in precedence order, deduped.

    Order: `Authorization: Bearer` → `x-api-key` → `x-goog-api-key` →
    `?key=` (the query-param form only on /v1beta/ paths, matching the
    legacy Google SDK that uses it, so credentials-in-URL stays
    contained).

    Every location is a CANDIDATE, not a commitment. The caller controls
    which header its SDK fills, but a reverse proxy or SSO gateway in
    front of it may add an `Authorization` header of its own — blank, or
    carrying the gateway's own token. Returning only the first location
    found would 401 those requests even though the caller's real key is
    sitting in `x-api-key`, so the middleware tries each in turn.
    """
    headers = scope.get("headers", [])
    candidates: list[str] = []

    def _add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    auth_header = _get_header(headers, b"authorization")
    if auth_header.startswith("Bearer "):
        _add(auth_header[7:])
    for name in (b"x-api-key", b"x-goog-api-key"):
        _add(_get_header(headers, name))
    if scope.get("path", "").startswith("/v1beta/"):
        qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        vals = qs.get("key")
        if vals:
            _add(vals[0])
    return candidates


_ANTHROPIC_ERROR_TYPES = {401: "authentication_error", 403: "permission_error"}
_GOOGLE_STATUSES = {401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 503: "UNAVAILABLE"}


def protocol_for_scope(scope) -> str:
    """Which error envelope the caller's SDK parses: "anthropic" for the
    /v1/messages surface, "gemini" for /v1beta/, else "openai".

    A request carrying `anthropic-version` (the Anthropic SDK and Claude
    Code always send it) also gets the Anthropic envelope — that is how
    GET /v1/models serves them the Anthropic listing, so its failures must
    speak the same language. The header signal is scoped to /v1 paths
    OTHER than /v1/chat/completions: an OpenAI-surface caller that happens
    to send the header must keep the OpenAI envelope and its statuses, and
    the dashboard/admin routes under /api are never rewritten."""
    path = scope.get("path", "")
    if path.startswith("/v1/messages"):
        return "anthropic"
    if path.startswith("/v1beta/"):
        return "gemini"
    if (
        path.startswith("/v1/")
        and not path.startswith("/v1/chat/completions")
        and _get_header(scope.get("headers", []), b"anthropic-version")
    ):
        return "anthropic"
    return "openai"


def _error_payload(protocol: str, status: int, message: str, error_type: str) -> bytes:
    """Render the auth error in the envelope the caller's SDK expects."""
    if protocol == "anthropic":
        body: dict = {
            "type": "error",
            "error": {
                "type": _ANTHROPIC_ERROR_TYPES.get(status, "api_error"),
                "message": message,
            },
        }
    elif protocol == "gemini":
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


async def _send_error(send, scope, status: int, message: str, error_type: str) -> None:
    body = _error_payload(protocol_for_scope(scope), status, message, error_type)
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

        candidates = _extract_credentials(scope)
        if not candidates:
            await _send_error(
                send, scope, 401,
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
        key_context = None
        auth_error: AuthError | None = None
        try:
            async with session_mod._session_factory() as session:
                # Try every candidate location before giving up — a
                # rejected proxy-injected token must not mask the caller's
                # valid key in another header. A non-AuthError (DB down,
                # decryption failure) is infrastructure, not a bad key, so
                # it aborts the whole chain below rather than falling
                # through to the next candidate.
                for raw_key in candidates:
                    try:
                        key_context = await validate_api_key(raw_key, session)
                        break
                    except AuthError as e:
                        auth_error = e
        except Exception:
            # A non-AuthError here is infrastructure (DB down, decryption
            # failure, ...). The 503 must still be observable — log the
            # traceback or the outage is undebuggable from the access log.
            structlog.get_logger().exception(
                "auth_middleware_db_failure",
                method=scope.get("method"),
                path=path,
            )
            await _send_error(send, scope, 503, "Service temporarily unavailable", "server_error")
            return

        if key_context is None:
            status = auth_error.status_code if auth_error else 401
            message = auth_error.message if auth_error else "Invalid API key"
            await _send_error(send, scope, status, message, "auth_error")
            return
        scope.setdefault("state", {})["key_context"] = key_context
        scope.setdefault("state", {})["workspace_id"] = key_context.workspace_id

        await self.app(scope, receive, send)
