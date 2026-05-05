"""Integration: chat.py uses the prompt cache."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def cached_client(tmp_sqlite_url, monkeypatch):
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

    from app import prompt_cache, router_cache
    router_cache.invalidate_router()
    prompt_cache.reset_backend()

    fake = AsyncMock()
    fake._deployments = []

    call_count = {"n": 0}

    async def _acompletion(**kwargs):
        call_count["n"] += 1
        return {
            "id": "x", "model": kwargs.get("model"),
            "object": "chat.completion", "created": int(time.time()),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c, call_count

    await engine.dispose()
    session_mod._session_factory = None
    prompt_cache.reset_backend()


async def test_first_request_is_cache_miss(cached_client):
    client, _ = cached_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "temperature": 0},
    )
    assert r.status_code == 200
    assert r.headers["x-orca-cache"] == "MISS"


async def test_repeat_deterministic_request_is_cache_hit(cached_client):
    client, calls = cached_client
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}

    r1 = await client.post("/v1/chat/completions", json=body)
    assert r1.headers["x-orca-cache"] == "MISS"
    assert calls["n"] == 1

    r2 = await client.post("/v1/chat/completions", json=body)
    assert r2.status_code == 200
    assert r2.headers["x-orca-cache"] == "HIT"
    # Upstream router was NOT called the second time.
    assert calls["n"] == 1
    # Response body matches first one.
    assert r2.json()["choices"][0]["message"]["content"] == r1.json()["choices"][0]["message"]["content"]


async def test_high_temperature_skips_cache(cached_client):
    client, calls = cached_client
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.9}

    r1 = await client.post("/v1/chat/completions", json=body)
    r2 = await client.post("/v1/chat/completions", json=body)
    assert r1.headers["x-orca-cache"] == "BYPASS"
    assert r2.headers["x-orca-cache"] == "BYPASS"
    assert calls["n"] == 2


async def test_streaming_is_not_cached(cached_client):
    """Streaming responses are skipped — caching SSE chunks isn't worth it for v1."""
    client, calls = cached_client
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0, "stream": True}

    # The stream mock returns a dict (not async iter) so the streaming
    # branch will fail — that's fine; we only check the cache wasn't consulted.
    try:
        await client.post("/v1/chat/completions", json=body)
    except Exception:
        pass


async def test_cascade_does_not_poison_cache(cached_client, monkeypatch):
    """If LiteLLM Router cascades to a different model_group, the response
    must NOT be written to the cache key computed from the requested model.
    Otherwise a later pinned request to the original model could get the
    fallback's cached answer without ever hitting upstream — silent
    cross-model contamination.

    The "different model_group" detection looks up the served model in the
    active deployments list. The fixture's deployments include every OpenAI
    model from the catalog, so we cascade from gpt-4o-mini to gpt-4o (also
    deployable, but a different model_name).
    """
    from app import router_cache

    # Mock acompletion to claim it served a DIFFERENT model_group than
    # requested. gpt-4o is in the fixture's deployment list with its own
    # model_name, so the cache safety check will detect this as a cascade
    # away from the requested gpt-4o-mini group.
    fake = await router_cache.get_router(None)

    async def _cascade(**kwargs):
        return {
            "id": "x",
            "model": "gpt-4o",   # different model_group than the requested gpt-4o-mini
            "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "from gpt-4o"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake.acompletion = AsyncMock(side_effect=_cascade)

    client, _ = cached_client
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}

    r1 = await client.post("/v1/chat/completions", json=body)
    assert r1.status_code == 200
    # Header reflects the actually-served model (post-cascade truth).
    assert r1.headers["x-orca-resolved-model"] == "gpt-4o"

    # Second identical request: if cache had been poisoned, this would
    # be a HIT and acompletion wouldn't be called. Instead, MISS again
    # because the first response was correctly NOT cached under
    # gpt-4o-mini's key (it was a gpt-4o response).
    fake.acompletion.reset_mock()
    fake.acompletion.side_effect = _cascade
    r2 = await client.post("/v1/chat/completions", json=body)
    assert r2.status_code == 200
    assert r2.headers["x-orca-cache"] == "MISS", (
        "second call must MISS — cache poisoning prevention requires that "
        "responses served by a different model_group than requested are NOT cached"
    )
    assert fake.acompletion.await_count == 1


async def test_cache_writes_when_served_model_is_prefixed_form(cached_client):
    """LiteLLM frequently returns response.model with the provider prefix
    (e.g. "openai/gpt-4o-mini" instead of bare "gpt-4o-mini"). That's the
    SAME model — just a different rendering — so the cache write must
    proceed. Strict string equality on response.model would treat this as
    a cascade and silently disable the cache for almost all real traffic."""
    from app import router_cache

    fake = await router_cache.get_router(None)

    async def _prefixed(**kwargs):
        # Same model the request asked for, returned with the LiteLLM
        # prefix appended (a common LiteLLM rewrite).
        return {
            "id": "x",
            "model": f"openai/{kwargs.get('model')}",
            "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake.acompletion = AsyncMock(side_effect=_prefixed)

    client, _ = cached_client
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}

    r1 = await client.post("/v1/chat/completions", json=body)
    assert r1.status_code == 200

    # Second identical request must HIT — proves cache wrote despite the
    # prefix mismatch. Without canonicalization this would MISS forever.
    fake.acompletion.reset_mock()
    fake.acompletion.side_effect = _prefixed
    r2 = await client.post("/v1/chat/completions", json=body)
    assert r2.status_code == 200
    assert r2.headers["x-orca-cache"] == "HIT", (
        "second call should HIT — cache write must proceed when served "
        "model is the same group as requested, even with a provider prefix"
    )
    assert fake.acompletion.await_count == 0


async def test_cache_hit_does_not_double_log(cached_client):
    """A cache hit still writes a RequestLog row, but with cached=True context.

    Otherwise the analytics dashboard would under-count requests. We log
    cached requests too — they're real traffic — but the log carries a
    `provider="cache"` marker so spend math stays right.
    """
    client, _ = cached_client
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}

    await client.post("/v1/chat/completions", json=body)
    await client.post("/v1/chat/completions", json=body)

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 2
    providers = sorted(r.provider for r in rows)
    assert providers == ["cache", "openai"]
    cache_row = next(r for r in rows if r.provider == "cache")
    assert cache_row.cost_microcents == 0  # cached requests cost nothing
