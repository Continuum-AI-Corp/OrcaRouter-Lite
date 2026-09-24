"""Budget enforcement on /v1/chat/completions.

`budget_limit_cents` was loaded into KeyContext but never enforced anywhere —
a leaked key meant unbounded spend. These tests pin the new behavior: an
exhausted key gets 429 before any routing / cache / upstream work and
unbudgeted keys are unaffected. Provisioning of budgeted/allowlisted keys
is covered in the keys-authz PR.
"""

from __future__ import annotations

import asyncio
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
    from packages.db.models.api_key import ApiKey
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
        # The budget counter lives on the key, not the request-log rows, so
        # pre-load it directly to simulate prior spend.
        await s.execute(
            ApiKey.__table__.update()
            .where(ApiKey.id == key_id)
            .values(spent_microcents=ApiKey.spent_microcents + microcents)
        )
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


async def _budgeted_stream(budget_env, *, chunks, budget_limit_cents=10):
    """Drive a streaming request for a budgeted key and return its final spend."""
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=budget_limit_cents)

    async def _stream():
        for ch in chunks:
            yield ch

    fake.acompletion = AsyncMock(return_value=_stream())

    async with await make_client(key) as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
                "stream_options": {"include_usage": False},
            },
        ) as r:
            async for _ in r.aiter_lines():
                pass

    from sqlalchemy import select

    from packages.db.models.api_key import ApiKey

    async with factory() as s:
        return (
            await s.execute(select(ApiKey.spent_microcents).where(ApiKey.id == key_id))
        ).scalar_one(), fake.acompletion.call_args


async def test_budgeted_stream_without_usage_charges_remaining(budget_env):
    # A completed stream that never delivers a usage frame (client forced
    # include_usage=False, provider ignored it) must NOT bill zero — that would
    # let a capped key stream for free. Fail-closed: charge the full remaining cap.
    spent, call_args = await _budgeted_stream(
        budget_env,
        chunks=[
            {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ],
    )
    # Even though the client demanded include_usage=False, the budgeted key forces it.
    assert call_args.kwargs["stream_options"]["include_usage"] is True
    # No usage frame observed -> full cap charged.
    assert spent == 100_000


async def test_budgeted_stream_with_usage_frame_charges_actual(budget_env):
    # A usage frame was observed, so only the real (tiny) cost is charged, not the
    # full remaining allowance.
    spent, _call_args = await _budgeted_stream(
        budget_env,
        budget_limit_cents=100,
        chunks=[
            {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
            {
                "usage": {"prompt_tokens": 5000, "completion_tokens": 2000, "total_tokens": 7000},
                "choices": [{"delta": {}, "finish_reason": "stop"}],
            },
        ],
    )
    assert 0 <= spent < 100_000


async def test_budgeted_blocking_forces_include_usage(budget_env):
    # Non-streaming budgeted request also forces include_usage on, even when the
    # client omits it.
    make_client, fake, factory, _root = budget_env
    key, _key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "stream_options": {"include_usage": False},
            },
        )

    assert r.status_code == 200, r.text
    assert fake.acompletion.call_args.kwargs["stream_options"]["include_usage"] is True


async def _get_spent(factory, key_id: str) -> int:
    from sqlalchemy import select

    from packages.db.models.api_key import ApiKey

    async with factory() as s:
        return (
            await s.execute(select(ApiKey.spent_microcents).where(ApiKey.id == key_id))
        ).scalar_one()


async def test_budgeted_stream_midstream_error_charges_actual_only(budget_env):
    # A mid-stream provider error is delivered as a complete error response
    # (SSE error frame + terminal [DONE]); the log row records its ~0 cost, so
    # settlement is KNOWN and must charge the actual cost only. Before the fix,
    # usage_seen stayed False in that branch and every transient provider
    # failure permanently exhausted the key (charged cap - spent).
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=10)

    def _failing_stream():
        async def _gen():
            yield {"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]}
            raise RuntimeError("upstream exploded")
        return _gen()

    fake.acompletion = AsyncMock(return_value=_failing_stream())

    async with await make_client(key) as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        ) as r:
            text = "\n".join([line async for line in r.aiter_lines()])

    # The error response was delivered in full.
    assert "Upstream provider error" in text
    assert "[DONE]" in text
    # Only the recorded (~0) cost is charged — not the 100_000-microcent cap.
    assert await _get_spent(factory, key_id) == 0

    # The key is NOT exhausted: a follow-up streaming request is still served.
    fake.acompletion = AsyncMock(return_value=_ok_stream())
    async with await make_client(key) as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hi again"}],
            },
        ) as r2:
            assert r2.status_code == 200
            async for _ in r2.aiter_lines():
                pass


def _ok_stream():
    async def _gen():
        yield {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
        yield {
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            "choices": [{"delta": {}, "finish_reason": "stop"}],
        }
    return _gen()


async def test_budgeted_blocking_without_usage_charges_remaining(budget_env):
    # A budgeted key whose provider ignores the forced include_usage and returns
    # a usage-less completion has an unknown cost. Mirroring the streaming rule,
    # the blocking path must fail closed and charge the full remaining allowance
    # — otherwise the delivered completion costs nothing and the cap is bypassed.
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=10)

    fake.acompletion = AsyncMock(return_value={
        "id": "chatcmpl-no-usage",
        "model": "gpt-4o-mini",
        "object": "chat.completion",
        "created": int(time.time()),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }],
    })

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 200, r.text
    assert await _get_spent(factory, key_id) == 100_000  # 10 cents, fail-closed


async def test_budgeted_blocking_httpexception_charges_recorded_cost(budget_env):
    # A budgeted blocking request whose upstream call raised HTTPException never
    # received a completion (response == {}, status_code never left 200). The
    # fail-closed remaining-charge rule applies only to *delivered* usage-less
    # completions — charging the cap here would repeat the mid-stream-error bug
    # class on the blocking path. The key must be charged its recorded ~0 cost.
    from fastapi import HTTPException

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=10)

    fake.acompletion = AsyncMock(
        side_effect=HTTPException(status_code=429, detail="upstream rate limit")
    )

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 429, r.text
    assert await _get_spent(factory, key_id) == 0


async def test_budgeted_blocking_with_usage_charges_actual(budget_env):
    # Control for the test above: a blocking response WITH usage must charge only
    # the recorded cost (never the remaining allowance) — no over-charging.
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )

    assert r.status_code == 200, r.text  # fixture response carries usage

    from sqlalchemy import select

    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        row_cost = (
            await s.execute(
                select(RequestLog.cost_microcents).where(
                    RequestLog.api_key_id == key_id
                )
            )
        ).scalar_one()
    assert await _get_spent(factory, key_id) == row_cost


async def test_budgeted_stream_disconnect_after_usage_charges_actual(budget_env):
    """Measured spend must not be re-opened by a later hang-up.

    The usage frame arrives, then the client disconnects. Cost is therefore
    KNOWN (the row records it), so settlement charges that cost. Keying the
    fail-closed rule on stream completion instead charged the whole remaining
    allowance for a request whose tokens were already accounted for.
    """
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    class _CancelAfterUsage:
        def __init__(self):
            self._n = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            self._n += 1
            if self._n == 1:
                return {"choices": [{"delta": {"content": "hi"},
                                     "finish_reason": None}]}
            if self._n == 2:
                return {
                    "usage": {
                        "prompt_tokens": 100_000,
                        "completion_tokens": 50_000,
                        "total_tokens": 150_000,
                    },
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                }
            # Mirrors Starlette cancelling the response task on http.disconnect.
            raise asyncio.CancelledError()

        async def aclose(self):
            pass

    fake.acompletion = AsyncMock(return_value=_CancelAfterUsage())

    async with await make_client(key) as c:
        try:
            async with c.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            ) as r:
                async for _ in r.aiter_lines():
                    pass
        except Exception:
            pass  # the injected cancel may surface to the test transport

    from sqlalchemy import select

    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        row = (
            await s.execute(
                select(RequestLog).where(RequestLog.api_key_id == key_id)
            )
        ).scalars().one()
    assert row.status_code == 499
    assert row.error_type == "client_disconnect"
    assert row.cost_microcents > 0
    spent = await _get_spent(factory, key_id)
    assert spent == row.cost_microcents
    # The disconnect is not a cost-unknown bail: it must not exhaust the key.
    assert spent < 1_000_000  # cap is 100 cents = 1_000_000 microcents


async def test_budgeted_blocking_commit_failure_persists_row_and_charge(budget_env):
    """A transient write failure must drop neither the row nor the charge.

    The blocking path retries with a FRESH ORM object (the failed attempt's
    INSERT was rolled back) and skips the retry when the trace_id is already
    durable, so the atomic row+charge unit lands exactly once.
    """
    from sqlalchemy import event, select

    from packages.db.models.request_log import RequestLog

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    # Fail the log INSERT once, at the cursor: by the time commit runs, the
    # row is already flushed (the budget UPDATE autoflushes it), so this is the
    # only seam that reproduces a real "database is locked" mid-write.
    sync_engine = factory.kw["bind"].sync_engine
    failures = {"n": 0}

    def _fail_first_log_insert(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO requests_log" in statement and failures["n"] == 0:
            failures["n"] += 1
            raise RuntimeError("database is locked")

    event.listen(sync_engine, "before_cursor_execute", _fail_first_log_insert)
    try:
        async with await make_client(key) as c:
            r = await c.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o-mini",
                      "messages": [{"role": "user", "content": "hi"}]},
            )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _fail_first_log_insert)

    assert r.status_code == 200, r.text
    assert failures["n"] == 1  # the retry is what saved the write
    async with factory() as s:
        rows = (
            await s.execute(select(RequestLog).where(RequestLog.api_key_id == key_id))
        ).scalars().all()
    assert len(rows) == 1  # never doubled
    assert await _get_spent(factory, key_id) == rows[0].cost_microcents
