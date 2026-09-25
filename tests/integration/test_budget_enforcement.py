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
from sqlalchemy.ext.asyncio import AsyncSession


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


async def test_budgeted_blocking_request_sends_no_stream_options(budget_env):
    """A cap must not put a streaming-only parameter on a blocking request.

    `include_usage` only decides whether the last frame of a *stream* reports
    usage — a non-streaming completion always carries it. LiteLLM forwards the
    parameter without looking at `stream`, and OpenAI rejects it on a request
    where stream is false, so forcing it here turned every request for a
    budgeted key into an upstream 400: the cap made the endpoint unusable
    instead of enforced.
    """
    make_client, fake, factory, _root = budget_env
    key, _key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert r.status_code == 200, r.text
    assert "stream_options" not in fake.acompletion.call_args.kwargs


async def test_fail_closed_charge_is_recorded_on_the_row_it_charges(budget_env):
    """The counter and the request history are one quantity and may not diverge.

    `spent_microcents` is seeded from, and reconciled against, the sum of
    `cost_microcents`, so a fail-closed charge that only the counter saw leaves
    a key exhausted by an amount no query over its requests can reproduce.
    """
    spent, _call_args = await _budgeted_stream(
        budget_env,
        chunks=[
            {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ],
    )
    assert spent == 100_000  # the full remaining allowance

    _make_client, _fake, factory, _root = budget_env
    from sqlalchemy import select

    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        rows = (await s.execute(select(RequestLog.cost_microcents))).scalars().all()
    assert rows == [spent]


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


async def test_budgeted_stream_error_after_unmeasured_content_charges_estimate(budget_env):
    """Partial content the provider never measured must still cost something.

    The upstream dies mid-generation after a long delivery and no usage frame
    ever arrives, so nothing measures it. Charging zero — what the recorded cost
    says — would let a capped key stream unbounded tokens free of charge behind
    a flaky provider; charging the whole remaining allowance would exhaust the
    key for a failure it cannot steer. Settlement is therefore priced from the
    delivered characters, and the same number lands on the row and on the key.
    """
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    delivered = "the quick brown fox " * 2_000  # ~40k chars ≈ 10k tokens

    def _failing_stream():
        async def _gen():
            yield {"choices": [{"delta": {"content": delivered}, "finish_reason": None}]}
            raise RuntimeError("upstream exploded mid-generation")
        return _gen()

    fake.acompletion = AsyncMock(return_value=_failing_stream())

    async with await make_client(key) as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "say it again " * 400}],
            },
        ) as r:
            text = "\n".join([line async for line in r.aiter_lines()])

    assert "[DONE]" in text

    from sqlalchemy import select

    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        row = (
            await s.execute(
                select(RequestLog).where(RequestLog.api_key_id == key_id)
            )
        ).scalars().one()
    assert row.output_tokens > 0  # the delivery is recorded, not erased
    spent = await _get_spent(factory, key_id)
    assert spent == row.cost_microcents  # charged == accounted
    assert 0 < spent < 1_000_000  # not free, and not the 100-cent cap


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


async def test_budgeted_stream_disconnect_before_usage_charges_delivery(budget_env):
    """A hangup before the usage frame must cost the delivery, not the cap.

    The usage frame is the last chunk, so a user pressing stop mid-answer means
    it never arrives and nothing measured the cost. Treating that as
    cost-unknown-and-therefore-max charged the entire remaining allowance for
    reading a few sentences, which is a normal action and bricks the key
    permanently. The delivery is priced from the characters that reached the
    client, exactly as the provider-error branch does it.
    """
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    delivered = "the quick brown fox " * 200  # 4000 chars, no usage frame ever

    class _CancelBeforeUsage:
        def __init__(self):
            self._n = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            self._n += 1
            if self._n == 1:
                return {"choices": [{"delta": {"content": delivered},
                                     "finish_reason": None}]}
            # The client hangs up mid-answer: no usage frame was ever produced.
            raise asyncio.CancelledError()

        async def aclose(self):
            pass

    fake.acompletion = AsyncMock(return_value=_CancelBeforeUsage())

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

    spent = await _get_spent(factory, key_id)
    # Something real was delivered, so it is not free...
    assert spent > 0
    # ...and it is the delivery, not the 1_000_000-microcent remainder.
    assert spent == row.cost_microcents
    assert spent < 1_000_000

    # The key still works: a follow-up streaming request is served.
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


async def test_budgeted_stream_hangup_before_first_chunk_still_costs_the_prompt(budget_env):
    """Bailing at the first byte must not be a way to read a capped key for free.

    Pricing an unmeasured stream from what was delivered is right for a failure
    the caller cannot steer, but a disconnect is the caller's own choice, and it
    happens after `acompletion` has already sent the prompt upstream. Settling an
    empty delivery at zero made "hang up immediately" the cheapest request of
    all: the counter never moved, so the lifetime cap stopped applying entirely
    and every retry was dispatched upstream and billed there.
    """
    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)

    class _CancelBeforeAnyChunk:
        def __aiter__(self):
            return self

        async def __anext__(self):
            # The client is gone before the first delta is forwarded.
            raise asyncio.CancelledError()

        async def aclose(self):
            pass

    fake.acompletion = AsyncMock(return_value=_CancelBeforeAnyChunk())
    prompt = "a very long prompt " * 400  # 7600 chars, priced upstream

    async with await make_client(key) as c:
        try:
            async with c.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "stream": True,
                    "messages": [{"role": "user", "content": prompt}],
                },
            ) as r:
                async for _ in r.aiter_lines():
                    pass
        except Exception:
            pass

    spent = await _get_spent(factory, key_id)
    # Nothing was delivered, yet the request was not free.
    assert spent > 0
    # And it is the prompt, not the whole remaining allowance.
    assert spent < 1_000_000

    # Repeating the trick keeps charging, so the cap still closes.
    for _ in range(3):
        fake.acompletion = AsyncMock(return_value=_CancelBeforeAnyChunk())
        async with await make_client(key) as c:
            try:
                async with c.stream(
                    "POST",
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4o-mini",
                        "stream": True,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                ) as r:
                    async for _ in r.aiter_lines():
                        pass
            except Exception:
                pass
        assert await _get_spent(factory, key_id) > spent
        spent = await _get_spent(factory, key_id)


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


async def test_cancelled_during_backoff_gives_up_exactly_once(
    budget_env, monkeypatch
):
    """A request torn down between retries parks its cost once.

    The write failed, the backoff is cancelled, and the transaction is abandoned
    with the completion already delivered: the obligation has to be parked, and
    parked exactly once. The `raise` out of the give-up is what keeps the
    write-in-flight arm from running a second give-up for the same settlement —
    two warnings for one abandoned row, and a second durability probe while the
    process is going away.

    The row is a usage-less completion for a 10-cent key, so the obligation is
    the fail-closed 100_000 microcents.
    """
    from sqlalchemy import event, select

    import app.routes.chat as chat
    from packages.auth.spend import pending_parked_spend
    from packages.db.models.request_log import RequestLog

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=10)
    fake.acompletion = AsyncMock(return_value=_completion("Hello!"))

    give_ups: list[int] = []
    real_give_up = chat._give_up_settlement

    async def _count_give_ups(*args, **kwargs):
        give_ups.append(1)
        return await real_give_up(*args, **kwargs)

    monkeypatch.setattr(chat, "_give_up_settlement", _count_give_ups)

    # Aim the cancellation at the backoff and nowhere earlier: a task is
    # cancelled at its next suspension, and the handler's rollback is one, so
    # make that call a coroutine that never yields. The sleep is then the only
    # place the cancellation can land.
    from sqlalchemy.ext.asyncio import AsyncSession

    async def _suspendless_rollback(self, *args, **kwargs):
        return None

    monkeypatch.setattr(AsyncSession, "rollback", _suspendless_rollback)

    in_retry = asyncio.Event()
    failures = {"n": 0}

    def _fail_the_write(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO requests_log" in statement and failures["n"] == 0:
            failures["n"] += 1
            in_retry.set()
            raise RuntimeError("database is locked")

    sync_engine = factory.kw["bind"].sync_engine
    event.listen(sync_engine, "before_cursor_execute", _fail_the_write)

    async def _request():
        async with await make_client(key) as c:
            return await c.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o-mini",
                      "messages": [{"role": "user", "content": "hi"}]},
            )

    try:
        task = asyncio.ensure_future(_request())
        await in_retry.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        event.remove(sync_engine, "before_cursor_execute", _fail_the_write)

    assert failures["n"] == 1  # the write really did fail and start backing off
    assert give_ups == [1]  # abandoned once, not twice and not never
    async with factory() as s:
        assert not (
            await s.execute(select(RequestLog.id).where(RequestLog.api_key_id == key_id))
        ).all()
    assert await pending_parked_spend(key_id) == 100_000


async def test_cancelled_rollback_does_not_skip_the_give_up(
    budget_env, monkeypatch
):
    """A cancellation inside the retry handler still accounts for the cost.

    Same teardown, other delivery point: the rollback that opens the handler is
    itself an await, so it can be where the cancellation lands. An exception
    raised from inside a handler is not caught by this `try`'s other arms, so it
    used to escape straight past the give-up below — the write lost, the
    obligation unparked, and the cap reopened for exactly the key whose write
    had just failed.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    import app.routes.chat as chat
    from packages.auth.spend import pending_parked_spend

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=10)
    fake.acompletion = AsyncMock(return_value=_completion("Hello!"))

    give_ups: list[int] = []
    real_give_up = chat._give_up_settlement

    async def _count_give_ups(*args, **kwargs):
        give_ups.append(1)
        return await real_give_up(*args, **kwargs)

    rollbacks = {"n": 0}
    real_rollback = AsyncSession.rollback

    async def _cancel_the_first_rollback(self, *args, **kwargs):
        rollbacks["n"] += 1
        if rollbacks["n"] == 1:
            raise asyncio.CancelledError
        return await real_rollback(self, *args, **kwargs)

    failures = {"n": 0}

    def _fail_the_write(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO requests_log" in statement and failures["n"] == 0:
            failures["n"] += 1
            raise RuntimeError("database is locked")

    monkeypatch.setattr(chat, "_give_up_settlement", _count_give_ups)
    monkeypatch.setattr(AsyncSession, "rollback", _cancel_the_first_rollback)
    sync_engine = factory.kw["bind"].sync_engine
    from sqlalchemy import event

    event.listen(sync_engine, "before_cursor_execute", _fail_the_write)
    try:
        async with await make_client(key) as c:
            await c.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o-mini",
                      "messages": [{"role": "user", "content": "hi"}]},
            )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _fail_the_write)

    assert rollbacks["n"] >= 1  # the cancellation really did land there
    assert failures["n"] == 1
    # The cancellation is swallowed rather than escaping, so the loop keeps
    # going: the next attempt still finds the session poisoned (the failed flush
    # was never rolled back), and the real rollback at the head of that handler
    # clears it, so a later attempt lands the row and its charge. Pinned: the
    # cost is accounted for once, and no give-up was needed to do it — before
    # this the request died here with nothing billed and nothing parked.
    assert give_ups == []
    assert await _get_spent(factory, key_id) == 100_000
    assert await pending_parked_spend(key_id) == 0
    from sqlalchemy import select

    from packages.db.models.request_log import RequestLog

    async with factory() as s:
        rows = (
            await s.execute(select(RequestLog.id).where(RequestLog.api_key_id == key_id))
        ).all()
    assert len(rows) == 1


# ── Durable recovery: the park outlives the process that lost it ──────

class _AckLossSession(AsyncSession):
    """Commit for real, then report failure as if the ack never came back.

    Armed for settlement commits only — a commit carrying a `RequestLog` row.
    The row is durable while its caller still sees an exception: the case the
    retry loops' trace_id check exists for.
    """

    drop_ack = False
    drops = 0

    async def commit(self):
        settles = self.info.pop("settles_request_log", False)
        await super().commit()
        if settles and _AckLossSession.drop_ack:
            _AckLossSession.drop_ack = False
            _AckLossSession.drops += 1
            raise ConnectionError("connection dropped mid-ack")

    async def rollback(self):
        self.info.pop("settles_request_log", None)
        await super().rollback()


def _note_settlement_flush(session, flush_context, instances):
    # `commit()` runs after autoflush has already emptied `session.new`, so
    # the settlement commit is recognised here, while the row is still new.
    from packages.db.models.request_log import RequestLog

    if any(isinstance(o, RequestLog) for o in session.new):
        session.info["settles_request_log"] = True


from sqlalchemy import event as _sa_event
from sqlalchemy.orm import Session as _SyncSession

_sa_event.listen(_SyncSession, "before_flush", _note_settlement_flush)


class _WriteBlackout:
    """Fail every settlement write at the cursor — a sustained write outage.

    Reads still work, which is what makes this the dangerous shape: the key
    keeps being served on its pre-check while nothing it spends can be
    recorded — not the charge, and not even the park.
    """

    _MATCHES = (
        "INSERT INTO requests_log",
        "UPDATE api_keys SET spent_microcents",
        "INSERT INTO budget_parks",
    )

    def __init__(self, factory):
        self.active = False
        self._engine = factory.kw["bind"].sync_engine
        from sqlalchemy import event

        event.listen(self._engine, "before_cursor_execute", self._handle)

    def _handle(self, conn, cursor, statement, parameters, context, executemany):
        if self.active and any(m in statement for m in self._MATCHES):
            raise RuntimeError("database is locked")

    def close(self):
        from sqlalchemy import event

        event.remove(self._engine, "before_cursor_execute", self._handle)


def _completion(text: str, *, usage: dict | None = None) -> dict:
    response = {
        "id": "chatcmpl-blackout",
        "model": "gpt-4o-mini",
        "object": "chat.completion",
        "created": int(time.time()),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "_orca_meta": {"provider": "openai", "litellm_model": "openai/gpt-4o-mini", "latency_ms": 42},
    }
    if usage:
        response["usage"] = usage
    return response


async def _lossy_factory(factory):
    """A session factory on the same engine whose settlement commits drop acks."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(
        factory.kw["bind"], expire_on_commit=False, class_=_AckLossSession,
    )


async def test_parked_spend_survives_a_real_restart(tmp_sqlite_url):
    """A lost settlement must outlive the process that lost it.

    A new engine on the same file, with no process memory carried over, still
    folds the park exactly once: the obligation lives in the database, not in
    the worker that recorded it.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.auth import spend as spend_mod
    from packages.auth.hashing import generate_api_key
    from packages.auth.spend import (
        charge_budget,
        is_exhausted,
        pending_parked_spend,
        read_spent,
        record_unsettled_spend,
    )
    from packages.db import session as session_mod
    from packages.db.engine import build_engine
    from packages.db.models.api_key import ApiKey
    from packages.db.models.base import Base

    cap = 10_000
    engine1 = build_engine(tmp_sqlite_url)
    try:
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory1 = async_sessionmaker(engine1, expire_on_commit=False)
        session_mod._session_factory = factory1

        full_key, key_hash, key_prefix = generate_api_key()
        async with factory1() as s:
            row = ApiKey(
                workspace_id="default", name="restart",
                key_hash=key_hash, key_prefix=key_prefix,
                budget_limit_cents=1,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            key_id = row.id
            await charge_budget(s, key_id, cap, 4_000)

        await record_unsettled_spend(
            trace_id="t-restart", api_key_id=key_id, microcents=3_000
        )
        assert await pending_parked_spend(key_id) == 3_000
    finally:
        await engine1.dispose()

    spend_mod._unsettled.clear()  # the machine stopped: no memory survives
    session_mod._session_factory = None

    engine2 = build_engine(tmp_sqlite_url)
    try:
        factory2 = async_sessionmaker(engine2, expire_on_commit=False)
        session_mod._session_factory = factory2
        async with factory2() as s:
            assert await is_exhausted(s, key_id, cap) is False  # 7_000 of 10_000
        async with factory2() as s:
            assert await read_spent(s, key_id) == 7_000
        assert await pending_parked_spend(key_id) == 0
        # A second pre-check must not move the same microcents a second time.
        async with factory2() as s:
            assert await is_exhausted(s, key_id, cap) is False
        async with factory2() as s:
            assert await read_spent(s, key_id) == 7_000
    finally:
        session_mod._session_factory = None
        await engine2.dispose()


async def test_park_is_visible_to_another_worker(budget_env, monkeypatch):
    """A park recorded on one worker blocks and folds on another."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.auth.spend import (
        charge_budget,
        is_exhausted,
        pending_parked_spend,
        read_spent,
        record_unsettled_spend,
    )
    from packages.db import session as session_mod

    _make_client, _fake, factory, _root = budget_env
    _key, key_id = await _make_budgeted_key(factory, budget_limit_cents=1)
    cap = 10_000
    async with factory() as s:
        await charge_budget(s, key_id, cap, 4_000)
    await record_unsettled_spend(
        trace_id="t-worker", api_key_id=key_id, microcents=3_000
    )

    worker_b = async_sessionmaker(
        factory.kw["bind"], expire_on_commit=False,
    )
    monkeypatch.setattr(session_mod, "_session_factory", worker_b)
    async with worker_b() as s:
        assert await is_exhausted(s, key_id, cap) is False
    assert await pending_parked_spend(key_id) == 0
    async with worker_b() as s:
        assert await read_spent(s, key_id) == 7_000


async def test_budgeted_blocking_write_outage_still_bills_the_delivery(budget_env):
    """Spend a write outage could not record must not simply disappear.

    Three requests settle while every write — charges and park inserts alike —
    fails, so no row and no durable park survives anywhere; the obligations sit
    in memory. When the DB recovers, the next settlement re-files and pays for
    what was already delivered as well.
    """
    from sqlalchemy import select

    from packages.auth.spend import pending_parked_spend
    from packages.db.models.request_log import RequestLog

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)
    usage = {"prompt_tokens": 10_000, "completion_tokens": 5_000, "total_tokens": 15_000}
    fake.acompletion = AsyncMock(side_effect=lambda **kw: _completion("hello", usage=usage))

    async def _ask(i: int):
        async with await make_client(key) as c:
            r = await c.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o-mini",
                      "messages": [{"role": "user", "content": f"hi {i}"}]},
            )
        assert r.status_code == 200, r.text

    blackout = _WriteBlackout(factory)
    blackout.active = True
    try:
        for i in range(3):
            await _ask(i)
        assert await _get_spent(factory, key_id) == 0  # nothing was recordable
        parked = await pending_parked_spend(key_id)
        assert parked > 0  # held in memory: even the park writes failed
        blackout.active = False
        await _ask(3)
    finally:
        blackout.close()

    async with factory() as s:
        rows = (
            await s.execute(select(RequestLog).where(RequestLog.api_key_id == key_id))
        ).scalars().all()
    assert len(rows) == 1  # the three lost settlements left no rows, no doubles
    cost = rows[0].cost_microcents
    assert cost > 0
    assert await pending_parked_spend(key_id) == 0
    assert await _get_spent(factory, key_id) == 4 * cost


async def test_budgeted_stream_write_outage_still_blocks_the_next_request(budget_env):
    """The streaming loop's give-up must clamp the next request too.

    A budgeted stream with no usage frame settles fail-closed at the whole
    remaining allowance; if that commit is impossible, the amount has to keep
    counting, or the outage leaves the key uncapped and the very next request
    is served for free.
    """
    from packages.auth.spend import pending_parked_spend

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=10)

    async def _no_usage():
        yield {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    fake.acompletion = AsyncMock(return_value=_no_usage())

    payload = {
        "model": "gpt-4o-mini",
        "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    }
    blackout = _WriteBlackout(factory)
    blackout.active = True
    try:
        async with await make_client(key) as c:
            async with c.stream("POST", "/v1/chat/completions", json=payload) as r:
                assert r.status_code == 200
                async for _ in r.aiter_lines():
                    pass
        await asyncio.sleep(1.0)  # the bounded retries run out after the response
    finally:
        blackout.close()

    assert await _get_spent(factory, key_id) == 0
    assert await pending_parked_spend(key_id) == 100_000  # the full remainder, held
    fake.acompletion = AsyncMock(return_value=_completion(
        "hello", usage={"prompt_tokens": 10_000, "completion_tokens": 5_000, "total_tokens": 15_000},
    ))
    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi again"}]},
        )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["type"] == "rate_limit_error"


async def test_budgeted_blocking_commit_ack_loss_bills_the_delivery_once(
    budget_env, monkeypatch,
):
    """A commit that lands but loses its ack must bill once and park nothing."""
    from sqlalchemy import select

    from packages.auth.spend import pending_parked_spend
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)
    monkeypatch.setattr(session_mod, "_session_factory", await _lossy_factory(factory))

    _AckLossSession.drop_ack = True
    _AckLossSession.drops = 0
    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200, r.text
    assert _AckLossSession.drops == 1  # the scenario actually dropped the ack

    async with factory() as s:
        rows = (
            await s.execute(select(RequestLog).where(RequestLog.api_key_id == key_id))
        ).scalars().all()
    cost = rows[0].cost_microcents
    assert cost > 0
    assert await _get_spent(factory, key_id) == cost
    assert await pending_parked_spend(key_id) == 0  # durable, so nothing to park

    await _ask_blocking_once(make_client, key)
    assert await _get_spent(factory, key_id) == 2 * cost  # not three


async def _ask_blocking_once(make_client, key: str) -> None:
    async with await make_client(key) as c:
        r = await c.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user", "content": "hi again"}]},
        )
    assert r.status_code == 200, r.text


async def test_budgeted_stream_commit_ack_loss_bills_the_delivery_once(
    budget_env, monkeypatch,
):
    """A streaming commit that lands but loses its ack bills once, parks nothing."""
    from sqlalchemy import select

    from packages.auth.spend import pending_parked_spend
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    make_client, fake, factory, _root = budget_env
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)
    fake.acompletion = AsyncMock(return_value=_ok_stream())
    monkeypatch.setattr(session_mod, "_session_factory", await _lossy_factory(factory))

    _AckLossSession.drop_ack = True
    _AckLossSession.drops = 0
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
            assert r.status_code == 200
            async for _ in r.aiter_lines():
                pass
    await asyncio.sleep(0.5)  # the shielded retry runs out after the response
    assert _AckLossSession.drops == 1

    async with factory() as s:
        rows = (
            await s.execute(select(RequestLog).where(RequestLog.api_key_id == key_id))
        ).scalars().all()
    cost = rows[0].cost_microcents
    assert cost > 0
    assert await _get_spent(factory, key_id) == cost
    assert await pending_parked_spend(key_id) == 0
