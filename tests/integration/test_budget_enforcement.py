"""Check i actually enforce budget_limit_cents.

The column was loaded but never checked, so a leaked key spent freely.
I hold against it in execute_chat before the upstream call and hand the
hold back once the real cost is in the log.
"""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from structlog.testing import capture_logs

from app.main import create_app
from app.routes import chat
from app.seed import seed_initial_state
from packages.auth.hashing import hash_api_key
from packages.db import session as session_mod
from packages.db.models.api_key import ApiKey
from packages.db.models.budget_hold import BudgetHold
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


def _claim_in_thread(url: str, kc, body, model: str) -> int:
    """Claim on its own event loop, so the writers really overlap.

    Twenty coroutines on one loop don't: they queue up and sqlite sees
    them one at a time, so a read-then-write check looks perfectly safe.
    A thread each means twenty connections racing for the same cap.
    """
    from app.routes.chat import _BudgetHold, _estimate_reserve_microcents

    async def _run() -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from packages.db.engine import build_engine

        engine = build_engine(url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                hold = _BudgetHold(db)
                try:
                    await hold.acquire(kc, body, [model])
                except HTTPException:
                    return 0  # refused
                return _estimate_reserve_microcents(body, [model])
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_requests_arriving_together_cannot_all_claim_the_cap(tmp_sqlite_url, monkeypatch):
    """Twenty at once must not each get to spend the whole cap.

    Reading the total and then comparing it lets every caller read an
    empty ledger and all walk through it. One INSERT..SELECT can't: the
    writer lock makes the second caller wait for the first one's row.
    """
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.schemas import ChatCompletionRequest
    from packages.auth.types import KeyContext
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    async with factory() as s:
        await seed_initial_state(s)
        key = _mk_key("sk-orca-parallelkey1", budget_limit_cents=1)
        s.add(key)
        await s.commit()
        key_id = key.id
    await engine.dispose()

    body = ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
    )
    kc = KeyContext(
        key_id=key_id, workspace_id="default", name="parallel", budget_limit_cents=1
    )

    with ThreadPoolExecutor(max_workers=20) as pool:
        claimed = list(
            pool.map(
                lambda _: _claim_in_thread(tmp_sqlite_url, kc, body, "gpt-4o-mini"),
                range(20),
            )
        )

    cap = 10_000  # budget_limit_cents=1, in microcents
    # > 0 so the cap isn't just refusing everything, <= cap so twenty
    # callers can't each reserve the whole thing
    assert 0 < sum(claimed) <= cap


@pytest.mark.asyncio
async def test_a_stream_beats_its_hold(tmp_sqlite_url, monkeypatch):
    """The beat runs inside the chunk loop, where unit tests can't reach it.

    Interval set to zero so every chunk writes one. A broken UPDATE would
    not fail the request — heartbeat swallows its own errors so a slow
    budget can't kill a working stream — so the warning is the only trace.
    """
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from app import config as cfg
    from app import router_cache

    cfg.get_settings.cache_clear()

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
        s.add(_mk_key("sk-orca-streambeatkey1", budget_limit_cents=100))
        await s.commit()

    async def _chunks():
        yield {
            "id": "c", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
            "created": 0,
            "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}],
        }
        yield {
            "id": "c", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
            "created": 0,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            "_orca_meta": {"provider": "openai", "latency_ms": 12},
        }

    fake_client = AsyncMock()
    fake_client.acompletion = AsyncMock(return_value=_chunks())
    monkeypatch.setattr(router_cache, "get_router", AsyncMock(return_value=fake_client))
    monkeypatch.setattr(chat, "_HOLD_HEARTBEAT", timedelta(0))

    app = create_app()
    with capture_logs() as logs:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://t",
        ) as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
                headers={"Authorization": "Bearer sk-orca-streambeatkey1"},
            )

    assert resp.status_code == 200
    assert "[DONE]" in resp.text
    assert [e for e in logs if e.get("event") == "budget_hold_heartbeat_failed"] == []

    # the stream owns the hold until the log row is in, then hands it back
    async with factory() as s:
        assert (await s.execute(select(BudgetHold))).scalars().all() == []
    await engine.dispose()
