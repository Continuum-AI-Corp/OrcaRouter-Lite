"""Budget enforcement on /v1/chat/completions.

`budget_limit_cents` was loaded into KeyContext but never enforced anywhere —
a leaked key meant unbounded spend. These tests pin the new behavior: an
exhausted key gets 429 before any routing / cache / upstream work,
unbudgeted keys are unaffected, and the keys API can provision
budgeted/allowlisted child keys.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def budget_env(tmp_sqlite_url, monkeypatch):
    """Full app + seeded root key, with the router client mocked out.

    Yields (make_client, fake_client, session_factory, root_key).
    """
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")

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

    fake_client = AsyncMock()
    fake_client.acompletion = AsyncMock(
        return_value={
            "id": "chatcmpl-budget-test",
            "model": "gpt-4o-mini",
            "object": "chat.completion",
            "created": int(time.time()),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            "_orca_meta": {
                "provider": "openai",
                "litellm_model": "openai/gpt-4o-mini",
                "latency_ms": 42,
            },
        }
    )

    from app import router_cache
    router_cache.invalidate_router()

    async def _fake_get_router(_session):
        return fake_client

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    app = create_app()

    async def make_client(api_key: str):
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://t",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    yield make_client, fake_client, factory, seed.api_key

    await engine.dispose()
    session_mod._session_factory = None


async def _make_budgeted_key(
    factory, *, budget_limit_cents: int | None
) -> tuple[str, str]:
    """Insert a budgeted child key; return (plaintext_key, key_id)."""
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    full_key, key_hash, key_prefix = generate_api_key()
    async with factory() as s:
        row = ApiKey(
            workspace_id="default",
            name="budgeted",
            key_hash=key_hash,
            key_prefix=key_prefix,
            budget_limit_cents=budget_limit_cents,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return full_key, row.id


async def _add_billable_spend(factory, key_id: str, microcents: int) -> None:
    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        s.add(RequestLog(
            workspace_id="default",
            api_key_id=key_id,
            trace_id="budget-test-trace",
            model_requested="gpt-4o-mini",
            model_resolved="gpt-4o-mini",
            provider="openai",
            routing_strategy="balanced",
            input_tokens=5,
            output_tokens=2,
            cost_microcents=microcents,
            latency_ms=10,
            status_code=200,
        ))
        await s.commit()


async def test_exhausted_budget_returns_429_without_upstream_call(budget_env):
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=1)
    # Pre-load spend past the 1-cent cap (10_000 microcents).
    await _add_billable_spend(factory, key_id, microcents=20_000)

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 429, r.text
    assert r.json()["error"]["type"] == "rate_limit_error"
    fake.acompletion.assert_not_awaited()


async def test_blocked_request_writes_no_log_row(budget_env):
    make_client, _fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=1)
    await _add_billable_spend(factory, key_id, microcents=99_999)

    async with await make_client(key) as c:
        await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    from sqlalchemy import func, select

    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        count = (
            await s.execute(
                select(func.count()).select_from(RequestLog).where(
                    RequestLog.api_key_id == key_id
                )
            )
        ).scalar_one()
    assert count == 1  # only the pre-loaded history row


async def test_under_budget_key_serves_normally(budget_env):
    make_client, fake, factory, _root = budget_env
    key, _key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 200, r.text
    fake.acompletion.assert_awaited_once()


async def test_unbudgeted_root_key_unaffected(budget_env):
    make_client, fake, _factory, root = budget_env

    async with await make_client(root) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 200, r.text
    fake.acompletion.assert_awaited_once()


async def test_create_key_accepts_restrictions(budget_env):
    make_client, _fake, factory, root = budget_env

    async with await make_client(root) as c:
        r = await c.post("/v1/keys", json={
            "name": "team-a",
            "model_allowlist": ["gpt-4o-mini"],
            "budget_limit_cents": 500,
        })

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["model_allowlist"] == ["gpt-4o-mini"]
    assert body["budget_limit_cents"] == 500

    from sqlalchemy import select

    from packages.db.models.api_key import ApiKey

    async with factory() as s:
        row = (
            await s.execute(select(ApiKey).where(ApiKey.id == body["id"]))
        ).scalar_one()
    assert row.budget_limit_cents == 500
    assert row.model_allowlist == ["gpt-4o-mini"]
