"""Check i actually enforce budget_limit_cents.

The column was loaded but never checked, so a leaked key spent freely.
I check it in execute_chat against recorded spend. The current request's
cost is logged after it finishes, so the overshoot is one request.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app
from app.seed import seed_initial_state
from packages.auth.hashing import hash_api_key
from packages.db import session as session_mod
from packages.db.models.api_key import ApiKey
from packages.db.models.request_log import RequestLog


def _mk_key(raw: str, **extra) -> ApiKey:
    return ApiKey(
        workspace_id="default",
        name=raw[-6:],
        key_hash=hash_api_key(raw),
        key_prefix="sk-orca-...." + raw[-4:],
        **extra,
    )


def _log_row(key_id: str, cost_microcents: int) -> RequestLog:
    return RequestLog(
        workspace_id="default",
        api_key_id=key_id,
        trace_id=str(uuid.uuid4()),
        model_requested="gpt-4o-mini",
        model_resolved="gpt-4o-mini",
        provider="openai",
        routing_strategy="balanced",
        input_tokens=10,
        output_tokens=5,
        cost_microcents=cost_microcents,
        latency_ms=50,
        status_code=200,
    )


@pytest.mark.asyncio
async def test_exhausted_budget_returns_429_before_upstream(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    async with factory() as s:
        await seed_initial_state(s)
        # 1 cent cap, 2 cents already spent
        spent_out = _mk_key("sk-orca-spentoutkey1", budget_limit_cents=1)
        s.add(spent_out)
        await s.flush()
        s.add(_log_row(spent_out.id, cost_microcents=20_000))
        # 1 cent cap, nothing spent yet, so it should get through
        has_room = _mk_key("sk-orca-hasroomkey1", budget_limit_cents=1)
        s.add(has_room)
        await s.commit()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer sk-orca-spentoutkey1"},
        )
        assert resp.status_code == 429
        assert "budget" in resp.json()["error"]["message"].lower()

        # nothing spent, so it gets past my gate. no providers here, so it
        # fails with 422 downstream. anything but 429 proves the gate passed.
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer sk-orca-hasroomkey1"},
        )
        assert resp.status_code != 429


@pytest.mark.asyncio
async def test_key_without_budget_is_never_blocked(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    async with factory() as s:
        seed = await seed_initial_state(s)
        s.add(_log_row(
            (await s.execute(select(ApiKey).where(ApiKey.name == "default"))).scalar_one().id,
            cost_microcents=999_999_999,
        ))
        await s.commit()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {seed.api_key}"},
        )
        # no budget set means no cap, so it fails downstream but never 429
        assert resp.status_code != 429
