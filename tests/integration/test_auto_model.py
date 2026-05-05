"""End-to-end test: model="auto" resolves to a real model before routing."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def auto_client(tmp_sqlite_url, monkeypatch):
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

    captured: dict = {}

    async def _acompletion(**kwargs):
        captured["model"] = kwargs.get("model")
        return {
            "id": "x", "model": kwargs.get("model"),
            "object": "chat.completion", "created": int(time.time()),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake = AsyncMock()
    fake.acompletion = AsyncMock(side_effect=_acompletion)
    # Expose the deployments so the resolver knows what's deployable
    fake._deployments = []

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    # Provide a real-ish list of deployments for the auto resolver.
    from packages.litellm_adapter.catalog import models_for_provider
    from packages.litellm_adapter.types import ProviderDeployment

    fake._deployments = [
        ProviderDeployment(
            model_name=m.id, litellm_model=f"{m.litellm_prefix}{m.id}",
            api_key="sk-test", provider="openai",
        )
        for m in models_for_provider("openai")
    ]

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c, captured

    await engine.dispose()
    session_mod._session_factory = None


async def test_auto_resolves_to_a_real_model(auto_client):
    client, captured = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    # The resolver picked a concrete model from the OpenAI catalog
    assert captured["model"] != "auto"
    assert isinstance(captured["model"], str)
    assert captured["model"].startswith(("gpt-", "o1", "o3", "o4"))


async def test_auto_picks_vision_capable_for_image_input(auto_client):
    client, captured = auto_client
    await client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}},
                ],
            }],
        },
    )
    # The model the resolver picks must support vision.
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    chosen = CATALOG_BY_ID.get(captured["model"])
    assert chosen is not None
    assert chosen.supports_vision is True


async def test_auto_response_reports_resolved_model_to_caller(auto_client):
    """The user-facing response shows what model "auto" resolved to."""
    client, captured = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    # The resolved model is exposed via OrcaRouter's `x-orca-resolved-model`
    # header so SDKs can log/display it without parsing the body.
    assert r.headers.get("x-orca-resolved-model") == captured["model"]


async def test_auto_with_quality_strategy_picks_different_model_than_cheapest(auto_client, monkeypatch):
    """`quality` flips the auto resolver from cheapest- to most-expensive-capable."""
    client, captured = auto_client

    from app import router_cache

    # The fixture installs a fresh AsyncMock as the router; pin strategy on it.
    fake_router = await router_cache.get_router(None)  # returns the mocked fake
    fake_router.strategy = "cheapest"
    fake_router.preferred_models = []

    r1 = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r1.status_code == 200
    cheapest_pick = captured["model"]
    assert r1.headers.get("x-orca-routing-strategy") == "cheapest"

    fake_router.strategy = "quality"

    r2 = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r2.status_code == 200
    quality_pick = captured["model"]
    assert r2.headers.get("x-orca-routing-strategy") == "quality"

    # cheapest and quality should pick different ends of the OpenAI catalog.
    assert cheapest_pick != quality_pick


async def test_auto_passes_fallbacks_to_router(auto_client):
    """Auto resolution must hand LiteLLM Router a fallback chain so a 404 on
    the primary cascades to the next-cheapest candidate without surfacing an
    error. Without this, the user sees a 503 the first time the resolver
    picks a stale model."""
    client, captured = auto_client
    # Replay the captured kwargs: we need fallbacks too, so wrap the existing
    # acompletion mock to record EVERY kwarg the handler sent.
    from unittest.mock import AsyncMock

    from app import router_cache
    full_kwargs: dict = {}

    fake = await router_cache.get_router(None)

    async def _record(**kwargs):
        full_kwargs.clear()
        full_kwargs.update(kwargs)
        return {
            "id": "x", "model": kwargs.get("model"),
            "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake.acompletion = AsyncMock(side_effect=_record)

    r = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200

    # `fallbacks` should be a list with one dict mapping primary → list of others.
    fb = full_kwargs.get("fallbacks")
    assert isinstance(fb, list) and len(fb) == 1, (
        f"expected fallbacks=[{{primary: [...]}}], got {fb!r}"
    )
    assert isinstance(fb[0], dict) and len(fb[0]) == 1
    primary, alts = next(iter(fb[0].items()))
    # Primary in the fallbacks dict must match the resolved model used in the call.
    assert primary == full_kwargs["model"]
    # At least one fallback alternative — auto routing returns top-N (default 5).
    assert isinstance(alts, list) and len(alts) >= 1
    # And primary != any fallback (no self-loops).
    assert primary not in alts


async def test_auto_uses_zero_in_deployment_retries_for_immediate_cascade(auto_client):
    """When `model="auto"` is in play, the per-call num_retries should be 0
    so a dead primary cascades to the fallback immediately. Default
    num_retries=2 would retry the dead deployment 2x first, adding 30-90s
    of perceived latency before the user sees a working response."""
    from unittest.mock import AsyncMock

    from app import router_cache

    seen: dict = {}

    async def _record(**kwargs):
        seen.clear()
        seen.update(kwargs)
        return {
            "id": "x", "model": kwargs.get("model"),
            "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake = await router_cache.get_router(None)
    fake.acompletion = AsyncMock(side_effect=_record)

    client, _ = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert seen.get("num_retries") == 0


async def test_pinned_model_does_not_pass_fallbacks(auto_client):
    """When the user explicitly pins a model, we should NOT inject fallbacks —
    explicit pin means "use this exact model, don't substitute"."""
    from unittest.mock import AsyncMock

    from app import router_cache

    seen: dict = {}

    async def _record(**kwargs):
        seen.clear()
        seen.update(kwargs)
        return {
            "id": "x", "model": kwargs.get("model"),
            "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }

    fake = await router_cache.get_router(None)
    fake.acompletion = AsyncMock(side_effect=_record)

    client, _ = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert seen.get("fallbacks") is None
    # Pinned requests use the default num_retries (not the auto override).
    assert seen.get("num_retries") is None  # not overridden per-call


async def test_auto_with_allowlist_picks_only_allowed_model(auto_client, monkeypatch):
    """A key with a model_allowlist must constrain `model="auto"` to candidates
    inside the allowlist. The pre-fix code rejected `auto` outright at the
    early allowlist check (since "auto" is never literally in any allowlist),
    making auto unusable for any rate-limited / scoped key."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    from packages.db.models.api_key import ApiKey

    # Mutate the seeded API key: add a single-model allowlist.
    factory = session_mod._session_factory
    async with factory() as s:
        rows = (await s.execute(select(ApiKey))).scalars().all()
        assert len(rows) == 1
        rows[0].model_allowlist = ["gpt-4o-mini"]
        await s.commit()

    client, captured = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200, r.text
    # The resolver must have narrowed candidates to the allowlist.
    assert captured["model"] == "gpt-4o-mini"


async def test_auto_with_allowlist_returns_403_when_no_intersection(auto_client):
    """If capable models exist but none are in the key's allowlist, return 403
    (not 422). 403 says "you can't use this here", which is the right signal
    for the operator to either widen the allowlist or rotate the key."""
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.api_key import ApiKey

    factory = session_mod._session_factory
    async with factory() as s:
        rows = (await s.execute(select(ApiKey))).scalars().all()
        # An allowlist of made-up names — no auto candidate will match.
        rows[0].model_allowlist = ["model-that-does-not-exist"]
        await s.commit()

    client, _ = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 403, r.text
    # Error message must point at the allowlist, not capability — these are
    # different debug paths for the operator.
    assert "allowlist" in r.text.lower()


async def test_pinned_request_with_empty_allowlist_is_denied(auto_client):
    """An empty model_allowlist=[] means "deny all models" — operator's
    explicit lock-down. A pinned request must 403 instead of routing.

    Pre-fix code used `if kc.model_allowlist:` (truthiness), which treated
    [] as "no allowlist set" and let every model through. This silently
    inverted the operator's security intent."""
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.api_key import ApiKey

    factory = session_mod._session_factory
    async with factory() as s:
        rows = (await s.execute(select(ApiKey))).scalars().all()
        rows[0].model_allowlist = []   # explicit deny-all
        await s.commit()

    client, _ = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 403, r.text


async def test_auto_with_empty_allowlist_returns_403(auto_client):
    """Same lock-down semantics for `model="auto"`: explicit empty allowlist
    means no model is allowed, even if many are deployable + capable."""
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.api_key import ApiKey

    factory = session_mod._session_factory
    async with factory() as s:
        rows = (await s.execute(select(ApiKey))).scalars().all()
        rows[0].model_allowlist = []
        await s.commit()

    client, _ = auto_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 403, r.text


async def test_auto_returns_422_not_403_when_allowlist_set_but_no_capable_model(tmp_sqlite_url, monkeypatch):
    """Edge case: key has an allowlist AND no capable model exists at all.
    The error should still be 422 (capability problem), not 403 (allowlist
    problem) — the allowlist is irrelevant when there's nothing to allow.

    Pre-fix code returned 403 because it conflated empty-after-allowlist with
    no-allowed-model, even when the real issue was no capable deployment."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    # No provider keys → no deployable models at all.
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
        # Set an allowlist so the 403/422 distinction is exercised.
        from sqlalchemy import select
        from packages.db.models.api_key import ApiKey
        rows = (await s.execute(select(ApiKey))).scalars().all()
        rows[0].model_allowlist = ["gpt-4o-mini"]
        await s.commit()

    from app import router_cache
    router_cache.invalidate_router()

    fake = AsyncMock()
    fake.acompletion = AsyncMock()
    fake._deployments = []  # nothing deployable

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
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        )

    # Must be 422 — there's no capable model. The allowlist is irrelevant
    # when the underlying problem is "no deployable model exists".
    assert r.status_code == 422, r.text

    await engine.dispose()
    session_mod._session_factory = None


async def test_auto_returns_422_when_no_capable_model_is_deployable(tmp_sqlite_url, monkeypatch):
    """If no provider keys cover the required capabilities, surface a clear 422."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    # No OPENAI_API_KEY, no provider keys at all → nothing deployable.
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
    fake = AsyncMock()
    fake.acompletion = AsyncMock()
    fake._deployments = []  # nothing deployable

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
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 422
    assert "no deployable" in r.text.lower() or "no model" in r.text.lower()
    fake.acompletion.assert_not_awaited()

    await engine.dispose()
    session_mod._session_factory = None
