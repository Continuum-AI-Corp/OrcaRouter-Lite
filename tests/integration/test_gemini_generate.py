"""/v1beta Gemini ingress — generateContent / streamGenerateContent (S7-S9).

Real app + mocked LiteLLM router. Covers: x-goog-api-key and ?key= auth
(and ?key= being scoped to /v1beta only), native error envelopes, blocking
+ streaming translation (alt=sse and JSON-array aggregation), schema-enum
normalization reaching the engine, model listing, and auto routing.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest


def _openai_response(**kwargs) -> dict:
    return {
        "id": "chatcmpl-1",
        "model": kwargs.get("model", "gemini-1.5-flash"),
        "object": "chat.completion",
        "created": int(time.time()),
        "choices": [{
            "index": 0,
            "message": kwargs.get(
                "message", {"role": "assistant", "content": "Hello world"}
            ),
            "finish_reason": kwargs.get("finish_reason", "stop"),
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        "_orca_meta": {"provider": "google", "latency_ms": 9},
    }


def _stream_chunks() -> list[dict]:
    now = int(time.time())
    return [
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gemini-1.5-flash", "created": now,
            "choices": [{"index": 0,
                         "delta": {"role": "assistant", "content": "Hello"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gemini-1.5-flash", "created": now,
            "choices": [{"index": 0, "delta": {"content": " world"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gemini-1.5-flash", "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            "_orca_meta": {"provider": "google", "latency_ms": 9},
        },
    ]


@pytest.fixture
async def native_client(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app import router_cache
    router_cache.invalidate_router()

    async def _stream_iter(chunks):
        for c in chunks:
            yield c

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(_stream_chunks())
        return _openai_response(model=kwargs.get("model", "gemini-1.5-flash"))

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t",
    ) as c:
        yield c, fake, seed.api_key

    await engine.dispose()
    session_mod._session_factory = None


_PAYLOAD = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


def _sse_frames(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


# ── auth ──


async def test_x_goog_api_key_authenticates(native_client):
    client, _, key = native_client
    r = await client.post("/v1beta/models/gemini-1.5-flash:generateContent",
                          json=_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 200


async def test_query_param_key_authenticates_on_v1beta(native_client):
    client, _, key = native_client
    r = await client.post(
        f"/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
        json=_PAYLOAD,
    )
    assert r.status_code == 200


async def test_query_param_key_is_rejected_outside_v1beta(native_client):
    """?key= is scoped to /v1beta — it must NOT authenticate OpenAI paths."""
    client, _, key = native_client
    r = await client.get(f"/v1/models?key={key}")
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "auth_error"  # OpenAI envelope there


async def test_missing_key_renders_google_envelope(native_client):
    client, _, _ = native_client
    r = await client.post("/v1beta/models/gemini-1.5-flash:generateContent",
                          json=_PAYLOAD)
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == 401
    assert err["status"] == "UNAUTHENTICATED"


# ── blocking ──


async def test_generate_content_shape_and_engine_body(native_client):
    client, fake, key = native_client
    r = await client.post(
        "/v1beta/models/gemini-1.5-flash:generateContent",
        json={
            **_PAYLOAD,
            "systemInstruction": {"parts": [{"text": "be brief"}]},
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 99},
        },
        headers={"x-goog-api-key": key},
    )
    assert r.status_code == 200
    body = r.json()
    (cand,) = body["candidates"]
    assert cand["content"] == {"role": "model", "parts": [{"text": "Hello world"}]}
    assert cand["finishReason"] == "STOP"
    assert body["usageMetadata"]["promptTokenCount"] == 4
    assert body["usageMetadata"]["candidatesTokenCount"] == 2
    assert body["modelVersion"] == "gemini-1.5-flash"

    kwargs = fake.acompletion.call_args.kwargs
    assert kwargs["model"] == "gemini-1.5-flash"
    assert kwargs["messages"][0] == {"role": "system", "content": "be brief"}
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 99


async def test_function_declaration_enums_normalized_before_engine(native_client):
    client, fake, key = native_client
    r = await client.post(
        "/v1beta/models/gemini-1.5-flash:generateContent",
        json={
            **_PAYLOAD,
            "tools": [{"functionDeclarations": [{
                "name": "get_weather",
                "parameters": {"type": "OBJECT",
                               "properties": {"city": {"type": "STRING"}}},
            }]}],
        },
        headers={"x-goog-api-key": key},
    )
    assert r.status_code == 200
    params = fake.acompletion.call_args.kwargs["tools"][0]["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["city"]["type"] == "string"


async def test_tool_call_response_becomes_function_call_part(native_client):
    client, fake, key = native_client

    async def _tool_response(**kwargs):
        return _openai_response(
            message={
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "get_weather",
                                 "arguments": '{"city": "SF"}'},
                }],
            },
            finish_reason="tool_calls",
        )

    fake.acompletion = AsyncMock(side_effect=_tool_response)
    r = await client.post("/v1beta/models/gemini-1.5-flash:generateContent",
                          json=_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 200
    parts = r.json()["candidates"][0]["content"]["parts"]
    assert parts == [{"functionCall": {"name": "get_weather",
                                       "args": {"city": "SF"}}}]


async def test_invalid_request_renders_google_envelope(native_client):
    client, _, key = native_client
    r = await client.post(
        "/v1beta/models/gemini-1.5-flash:generateContent",
        json={**_PAYLOAD, "generationConfig": {"candidateCount": 3}},
        headers={"x-goog-api-key": key},
    )
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["status"] == "INVALID_ARGUMENT"
    assert "candidateCount" in err["message"]


async def test_post_without_action_colon_is_native_404(native_client):
    client, _, key = native_client
    r = await client.post("/v1beta/models/gemini-1.5-flash",
                          json=_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 404
    assert r.json()["error"]["status"] == "NOT_FOUND"


async def test_unknown_action_is_native_404(native_client):
    client, _, key = native_client
    r = await client.post("/v1beta/models/gemini-1.5-flash:embedContent",
                          json=_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 404
    assert r.json()["error"]["status"] == "NOT_FOUND"


# ── streaming ──


async def test_stream_alt_sse_frames_and_request_log(native_client):
    client, _, key = native_client
    r = await client.post(
        "/v1beta/models/gemini-1.5-flash:streamGenerateContent?alt=sse",
        json=_PAYLOAD, headers={"x-goog-api-key": key},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "[DONE]" not in r.text
    assert "event:" not in r.text  # Gemini SSE is data-only frames

    frames = _sse_frames(r.text)
    texts = [
        f["candidates"][0]["content"]["parts"][0]["text"]
        for f in frames
        if f["candidates"][0]["content"]["parts"]
    ]
    assert "".join(texts) == "Hello world"
    final = frames[-1]
    assert final["candidates"][0]["finishReason"] == "STOP"
    assert final["usageMetadata"]["totalTokenCount"] == 6

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_streaming is True
    assert rows[0].output_tokens == 2
    assert rows[0].status_code == 200


async def test_stream_without_alt_sse_aggregates_json_array(native_client):
    client, _, key = native_client
    r = await client.post(
        "/v1beta/models/gemini-1.5-flash:streamGenerateContent",
        json=_PAYLOAD, headers={"x-goog-api-key": key},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    chunks = r.json()
    assert isinstance(chunks, list)
    assert chunks[-1]["candidates"][0]["finishReason"] == "STOP"
    assert "usageMetadata" in chunks[-1]


# ── model listing + auto ──


async def test_list_models_gemini_shape(native_client):
    client, _, key = native_client
    r = await client.get("/v1beta/models", headers={"x-goog-api-key": key})
    assert r.status_code == 200
    models = r.json()["models"]
    assert len(models) > 0
    assert all(m["name"].startswith("models/") for m in models)
    assert "generateContent" in models[0]["supportedGenerationMethods"]


async def test_get_single_model_and_native_404(native_client):
    client, _, key = native_client
    from packages.litellm_adapter.catalog import CATALOG

    known = CATALOG[0].id
    r = await client.get(f"/v1beta/models/{known}", headers={"x-goog-api-key": key})
    assert r.status_code == 200
    assert r.json()["name"] == f"models/{known}"

    r = await client.get("/v1beta/models/not-a-model-xyz",
                         headers={"x-goog-api-key": key})
    assert r.status_code == 404
    assert r.json()["error"]["status"] == "NOT_FOUND"


async def test_model_auto_resolves_through_gemini_ingress(native_client):
    client, fake, key = native_client

    from packages.litellm_adapter.catalog import models_for_provider
    from packages.litellm_adapter.types import ProviderDeployment

    fake._deployments = [
        ProviderDeployment(
            model_name=m.id, litellm_model=f"{m.litellm_prefix}{m.id}",
            api_key="sk-test", provider="openai",
        )
        for m in models_for_provider("openai")
    ]
    r = await client.post("/v1beta/models/auto:generateContent",
                          json=_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 200
    assert r.headers["x-orca-requested-model"] == "auto"
    assert r.headers["x-orca-resolved-model"] != "auto"
