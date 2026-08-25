"""Native-surface hardening (PR #64 round 11): allowlist on the count-token
endpoints, native envelopes from the app-wide handlers, RequestLog status
matching the delivered native status, and lenient credential-header
decoding. Reuses the mocked-router app fixtures of the sibling test modules.
"""

# ruff: noqa: F811  (fixtures imported from sibling modules are re-bound as parameters)
from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy import select

from tests.integration.test_anthropic_messages import (  # noqa: F401 (fixture)
    _messages_payload,
    native_client,
)
from tests.integration.test_auth_middleware import app_with_auth  # noqa: F401 (fixture)

_GEMINI_PAYLOAD = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


async def _restrict_seeded_key(allowlist: list[str]) -> None:
    from packages.db import session as session_mod
    from packages.db.models.api_key import ApiKey

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(ApiKey))).scalars().all()
        rows[0].model_allowlist = allowlist
        await s.commit()


async def _log_rows() -> list[tuple[int, str | None]]:
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    return [(r.status_code, r.error_type) for r in rows]


# ── allowlist on count-token endpoints ──


async def test_anthropic_count_tokens_enforces_the_model_allowlist(native_client):
    """The count-token endpoints never reach the engine, so they must apply
    the allowlist themselves — a restricted key must not probe denied models."""
    client, _fake, key = native_client
    await _restrict_seeded_key(["gpt-4o"])

    def body(model):
        return {"model": model, "messages": [{"role": "user", "content": "hi"}]}

    r = await client.post("/v1/messages/count_tokens", json=body("claude-opus-4"),
                          headers={"x-api-key": key})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["type"] == "permission_error"
    r = await client.post("/v1/messages/count_tokens", json=body("gpt-4o"),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    # auto is exempt, exactly as in the engine
    r = await client.post("/v1/messages/count_tokens", json=body("auto"),
                          headers={"x-api-key": key})
    assert r.status_code == 200


async def test_gemini_count_tokens_enforces_the_model_allowlist(native_client):
    client, _fake, key = native_client
    await _restrict_seeded_key(["gpt-4o"])
    r = await client.post("/v1beta/models/gemini-1.5-flash:countTokens",
                          json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["status"] == "PERMISSION_DENIED"
    r = await client.post("/v1beta/models/gpt-4o:countTokens",
                          json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 200


# ── malformed tool blocks / turns ──


async def test_tool_result_without_tool_use_id_is_native_400_not_retryable_503(native_client):
    client, fake, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(messages=[
        {"role": "user", "content": [{"type": "tool_result", "content": "x"}]},
    ]), headers={"x-api-key": key})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert "tool_use_id" in r.json()["error"]["message"]
    fake.acompletion.assert_not_awaited()


async def test_user_turn_carrying_function_call_parts_is_rejected(native_client):
    """A functionCall in a user turn used to translate to [] — the turn
    vanished from the upstream conversation with no error and no log."""
    client, fake, key = native_client
    r = await client.post(
        "/v1beta/models/gemini-1.5-flash:generateContent",
        json={"contents": [
            {"role": "user", "parts": [{"functionCall": {"name": "f", "args": {}}}]},
            {"role": "user", "parts": [{"text": "hi"}]},
        ]},
        headers={"x-goog-api-key": key},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["status"] == "INVALID_ARGUMENT"
    fake.acompletion.assert_not_awaited()


# ── app-wide handlers speak the native envelope ──


async def test_routing_level_failures_speak_the_anthropic_envelope(native_client):
    """404/405 never reach a route body; the app-wide handlers must still
    render the caller's envelope on the native surface."""
    client, _fake, key = native_client
    r = await client.get("/v1/messages", headers={"x-api-key": key})
    assert r.status_code == 405
    assert r.json()["type"] == "error"
    assert set(r.json()["error"]) == {"type", "message"}

    r = await client.post("/v1/messages/unknown", json={}, headers={"x-api-key": key})
    assert r.status_code == 404
    assert r.json()["error"]["type"] == "not_found_error"

    # an Anthropic SDK caller on any other path gets it too
    r = await client.get("/v1/nope", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    assert r.status_code == 404
    assert r.json()["error"]["type"] == "not_found_error"

    # and the OpenAI surface is unchanged
    r = await client.get("/v1/nope", headers={"Authorization": f"Bearer {key}"})
    assert r.json()["error"]["type"] == "not_found"


async def test_routing_level_failures_speak_the_google_envelope(native_client):
    client, _fake, key = native_client
    r = await client.post("/v1beta/models", json={}, headers={"x-goog-api-key": key})
    assert r.status_code == 405
    assert r.json()["error"]["code"] == 405
    assert set(r.json()["error"]) == {"code", "message", "status"}

    r = await client.get("/v1beta/anything", headers={"x-goog-api-key": key})
    assert r.status_code == 404
    assert r.json()["error"]["status"] == "NOT_FOUND"


# ── RequestLog status == delivered status ──


async def test_request_log_records_the_delivered_anthropic_status(native_client):
    """The engine says 422 for model_not_found; this surface delivers 404.
    The persisted row must show what went over the wire."""
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "model does not exist", http_status=422, error_type="model_not_found",
    ))
    r = await client.post("/v1/messages", json=_messages_payload(model="nope-1"),
                          headers={"x-api-key": key})
    assert r.status_code == 404
    assert await _log_rows() == [(404, "model_not_found")]


async def test_request_log_records_the_delivered_google_status(native_client):
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "no key", http_status=503, error_type="no_providers_configured",
    ))
    r = await client.post("/v1beta/models/gpt-4o-mini:generateContent",
                          json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 403
    assert await _log_rows() == [(403, "no_providers_configured")]


async def test_openai_surface_log_status_is_unchanged(native_client):
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "model does not exist", http_status=422, error_type="model_not_found",
    ))
    r = await client.post("/v1/chat/completions", json={
        "model": "nope-1", "messages": [{"role": "user", "content": "hi"}],
    }, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 422
    assert await _log_rows() == [(422, "model_not_found")]


# ── credential headers with non-UTF-8 bytes ──


async def test_non_utf8_credential_header_is_a_clean_401(app_with_auth):
    """A raw non-UTF-8 byte in x-api-key is an unauthenticated, remotely
    reachable input; it must end as 401, not an unhandled UnicodeDecodeError."""
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    bad = bytes([0xFF, 0xFE])
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": "/v1/protected",
        "raw_path": b"/v1/protected", "query_string": b"", "root_path": "",
        "headers": [(b"host", b"t"), (b"x-api-key", b"sk-orca-" + bad),
                    (b"anthropic-version", bad)],
        "client": ("127.0.0.1", 1), "server": ("t", 80),
    }
    await app_with_auth(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 401
