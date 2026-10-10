"""Budget enforcement in the request path — the cap actually stops traffic.

`ApiKey.budget_limit_cents` is a hard lifetime cap: a key at its cap must be
rejected with 429, and a request that is served must leave the counter moved by
exactly what it cost. Both halves matter, because a cap that is checked but never
charged would re-grant every exhausted key on the next restart.

Real app, real SQLite, a mocked router — the same shape as the log-durability
tests, so these cover the same paths (streaming and blocking) end to end.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from packages.auth.spend import MICROCENTS_PER_CENT
from packages.db import session as session_mod
from packages.db.engine import build_engine
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base
from packages.db.models.budget_park import BudgetPark
from packages.db.models.request_log import RequestLog


def _mark_log_flush(session, _flush_context, _instances) -> None:
    """Flag a flush that carries a RequestLog, so its commit can be failed.

    Read from `.new` inside commit() instead would miss it: the budget charge
    runs an UPDATE first and that autoflushes the pending INSERT, so by the time
    commit() runs the row is no longer "new".
    """
    if any(isinstance(o, RequestLog) for o in session.new):
        session._carrying_log = True


class _FailingCommitSession(AsyncSession):
    """AsyncSession that fails the commit of a session carrying a RequestLog.

    The auth middleware shares this factory and commits no log row, so it is
    untouched.
    """

    async def commit(self):
        if getattr(self.sync_session, "_carrying_log", False):
            raise OperationalError("COMMIT", {}, Exception("database is locked"))
        return await super().commit()


def _chunks() -> list[dict]:
    now = int(time.time())
    return [
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {"content": "Hello"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        },
    ]


async def _stream_iter():
    for chunk in _chunks():
        yield chunk


def _blocking_response() -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion",
        "model": "gpt-4o-mini", "created": int(time.time()),
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Hello there"},
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        "_orca_meta": {"cost_usd": 0.0001},
    }


@pytest.fixture
async def budget_app(tmp_sqlite_url, monkeypatch):
    """App with a real DB, a mocked router, and one key with a lifetime cap."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from app import config as cfg
    cfg.get_settings.cache_clear()

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from packages.auth.hashing import generate_api_key
    full_key, key_hash, key_prefix = generate_api_key()
    key = ApiKey(
        workspace_id="default",
        name="budgeted",
        key_hash=key_hash,
        key_prefix=key_prefix,
        budget_limit_cents=1,  # 1 cent = 10_000 microcents
    )
    async with factory() as s:
        s.add(key)
        await s.commit()

    from app import router_cache
    router_cache.invalidate_router()

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter()
        return _blocking_response()

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)
    monkeypatch.setattr("app.routes.chat._LOG_COMMIT_BACKOFF_S", (0.0, 0.0))

    from app.main import create_app
    app = create_app()

    # Scoped to this test: the listener is on the global Session class, so it
    # must not outlive the fixture.
    event.listen(Session, "before_flush", _mark_log_flush)
    try:
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
            headers={"Authorization": f"Bearer {full_key}"},
        ) as client:
            yield client, factory, key.id
    finally:
        event.remove(Session, "before_flush", _mark_log_flush)
        session_mod._session_factory = None
        await engine.dispose()


async def _chat(client, *, stream: bool = False) -> dict:
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": stream,
        },
    )
    return {"status": r.status_code, "body": r.text}


async def _spent(factory, key_id) -> int:
    async with factory() as s:
        value = await s.scalar(select(ApiKey.spent_microcents).where(ApiKey.id == key_id))
    return int(value or 0)


async def _log_rows(factory) -> list[RequestLog]:
    async with factory() as s:
        return list((await s.execute(select(RequestLog))).scalars().all())


async def _park_rows(factory) -> list[BudgetPark]:
    async with factory() as s:
        return list((await s.execute(select(BudgetPark))).scalars().all())


async def test_request_under_the_cap_is_served_and_charged(budget_app):
    """A blocking request records its measured cost against the cap."""
    client, factory, key_id = budget_app

    result = await _chat(client)

    assert result["status"] == 200
    assert await _spent(factory, key_id) > 0
    rows = await _log_rows(factory)
    assert len(rows) == 1
    assert rows[0].cost_microcents > 0
    assert rows[0].input_tokens == 4 and rows[0].output_tokens == 2


async def test_exhausted_key_is_rejected_with_429(budget_app):
    """A key at its cap is refused before any upstream call is made."""
    client, factory, key_id = budget_app

    async with factory() as s:
        await s.execute(
            ApiKey.__table__.update()
            .where(ApiKey.id == key_id)
            .values(spent_microcents=1 * MICROCENTS_PER_CENT)
        )
        await s.commit()

    result = await _chat(client)

    assert result["status"] == 429
    assert "budget exhausted" in result["body"]
    # Nothing was served, so nothing new was recorded.
    assert await _log_rows(factory) == []


async def test_stream_under_the_cap_is_served_and_charged(budget_app):
    """The streaming path charges the measured cost, same as the blocking path."""
    client, factory, key_id = budget_app

    result = await _chat(client, stream=True)

    assert result["status"] == 200
    assert "data: [DONE]" in result["body"]
    spent = await _spent(factory, key_id)
    assert spent > 0
    rows = await _log_rows(factory)
    assert len(rows) == 1
    assert rows[0].cost_microcents == spent
    assert rows[0].is_streaming is True


async def test_charge_and_log_row_land_in_one_transaction(budget_app):
    """The counter and the row move together, so a logged cost is a charged cost."""
    client, factory, key_id = budget_app

    await _chat(client)

    spent = await _spent(factory, key_id)
    rows = await _log_rows(factory)
    assert rows[0].cost_microcents == spent


@pytest.fixture
async def failing_app(tmp_sqlite_url, monkeypatch):
    """Same as budget_app, but every request-log commit fails."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from app import config as cfg
    cfg.get_settings.cache_clear()

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=_FailingCommitSession, expire_on_commit=False)
    session_mod._session_factory = factory

    from packages.auth.hashing import generate_api_key
    full_key, key_hash, key_prefix = generate_api_key()
    key = ApiKey(
        workspace_id="default",
        name="budgeted",
        key_hash=key_hash,
        key_prefix=key_prefix,
        budget_limit_cents=1,
    )
    async with factory() as s:
        s.add(key)
        await s.commit()

    from app import router_cache
    router_cache.invalidate_router()

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter()
        return _blocking_response()

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)
    monkeypatch.setattr("app.routes.chat._LOG_COMMIT_BACKOFF_S", (0.0, 0.0))

    from app.main import create_app
    app = create_app()

    # Scoped to this test: the listener is on the global Session class, so it
    # must not outlive the fixture.
    event.listen(Session, "before_flush", _mark_log_flush)
    try:
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
            headers={"Authorization": f"Bearer {full_key}"},
        ) as client:
            yield client, factory, key.id
    finally:
        event.remove(Session, "before_flush", _mark_log_flush)
        session_mod._session_factory = None
        await engine.dispose()


async def test_a_settlement_that_cannot_be_recorded_is_parked(failing_app):
    """The row and the charge die together, so the cost is parked against the cap.

    Without this, a settlement that fails after every retry leaves the key's cap
    open for a delivery that was served.
    """
    client, factory, key_id = failing_app

    result = await _chat(client, stream=True)

    assert result["status"] == 200
    assert "data: [DONE]" in result["body"]

    parked = await _park_rows(factory)
    assert len(parked) == 1
    assert parked[0].api_key_id == key_id
    assert parked[0].microcents > 0
    # The row never landed, so the counter did not move.
    assert await _spent(factory, key_id) == 0
    assert await _log_rows(factory) == []


async def test_a_parked_charge_counts_against_the_cap_on_the_next_request(budget_app):
    """A parked obligation is read by the pre-check and blocks dispatch.

    The park is created through the same public entry point the settlement path
    uses (`record_unsettled_spend`), then a real request is sent through
    `execute_chat`. If the pre-check did not fold the park into the key's spend,
    this request would be served and the counter would move by only its own
    cost — so a 200 here is the regression this test exists to catch.
    """
    client, factory, key_id = budget_app

    from packages.auth.spend import record_unsettled_spend

    # Larger than the key's 10,000-microcent cap, so the debt alone must refuse
    # the request.
    await record_unsettled_spend(
        trace_id="parked-larger-than-cap",
        api_key_id=str(key_id),
        microcents=50_000,
    )
    parked = await _park_rows(factory)
    assert len(parked) == 1
    assert parked[0].microcents == 50_000

    result = await _chat(client)

    assert result["status"] == 429
    assert "budget exhausted" in result["body"]
    # The request was never dispatched, so it recorded nothing of its own.
    assert await _log_rows(factory) == []


async def test_an_unpriceable_completion_is_not_charged_the_whole_cap(
    budget_app, monkeypatch
):
    """A model absent from the catalog has no price, but one request must not
    consume the key's entire remaining lifetime budget."""
    client, factory, key_id = budget_app

    # Countable tokens with no price any tier can reach: the model is not in the
    # catalog and no LiteLLM cost was attached.
    unpriced = {
        "id": "chatcmpl-1", "object": "chat.completion",
        "model": "my-private-model", "created": int(time.time()),
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Hello there"},
        }],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }

    from app import router_cache

    fake = AsyncMock()
    fake.acompletion = AsyncMock(side_effect=lambda **kwargs: unpriced)
    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    result = await _chat(client)

    assert result["status"] == 200
    spent = await _spent(factory, key_id)
    cap = 1 * MICROCENTS_PER_CENT
    # Fail closed, but bounded: the cap is not consumed by a single request.
    assert 0 < spent < cap
    # The row records the same amount the counter moved by.
    rows = await _log_rows(factory)
    assert rows[0].cost_microcents == spent


def _unmeasured_chunks(*, content: str, tool_calls: list | None = None) -> list[dict]:
    """A stream with no `usage` frame — the delivery is the only pricing signal.

    This is the path `_unmeasured_charge` owns: the provider sent characters
    through `delta.content` (and optionally `delta.tool_calls`) and then ended
    with `finish_reason: "stop"` — no token counts ever arrived, so the charge
    is computed from what the client was delivered, exactly as the blocking
    path does.
    """
    now = int(time.time())
    frames: list[dict] = []
    if content:
        frames.append({
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {"content": content},
                         "finish_reason": None}],
        })
    if tool_calls:
        frames.append({
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {"tool_calls": tool_calls},
                         "finish_reason": None}],
        })
    frames.append({
        "id": "chatcmpl-1", "object": "chat.completion.chunk",
        "model": "gpt-4o-mini", "created": now,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    return frames


async def _stream_iter_from(chunks):
    for c in chunks:
        yield c


@pytest.mark.parametrize(
    "chunks_fixture",
    [
        pytest.param(
            lambda: _unmeasured_chunks(content="Hello there"),
            id="content-only",
        ),
        pytest.param(
            lambda: _unmeasured_chunks(
                content="Tool call: ",
                tool_calls=[{"index": 0, "id": "call_1", "type": "function",
                             "function": {"name": "who", "arguments": ""}}],
            ),
            id="content-plus-tool-call",
        ),
    ],
)
async def test_unmeasured_streaming_delivery_is_priced_not_wholesaled(
    budget_app, monkeypatch, chunks_fixture
):
    """A streamed delivery that carries no usage frame must be priced per the
    characters the client received — never the whole remaining budget.

    Regression for the P1: the old whole-remainder charge (`cap - spent`)
    would consume the entire key on a single request. The P2: streamed
    tool-call arguments were not counted as delivered content. Both are fixed
    in `app/routes/chat.py` (`_unmeasured_charge` + the streaming delta loop),
    and this locks the behavior at the integration boundary.
    """
    client, factory, key_id = budget_app

    from app import router_cache

    fake = AsyncMock()
    fake.acompletion = AsyncMock(
        return_value=_stream_iter_from(chunks_fixture())
    )

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    result = await _chat(client, stream=True)

    assert result["status"] == 200
    spent = await _spent(factory, key_id)
    cap = 1 * MICROCENTS_PER_CENT
    # Bounded: the charge is proportional to delivery size, not cap size.
    assert 0 < spent < cap
    rows = await _log_rows(factory)
    assert rows[0].cost_microcents == spent


async def test_measured_but_unpriceable_stream_is_floored_not_zero(
    budget_app, monkeypatch
):
    """A stream with countable tokens but no priceable model charges the floor.

    Regression for the P1: the streaming settlement returned the row's 0 cost
    untouched when usage was countable, so a custom/unlisted model streamed at
    zero recorded cost forever. The blocking twin floors such completions at 1
    microcent; the stream must do the same.
    """
    client, factory, key_id = budget_app

    now = int(time.time())
    chunks = [
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "my-private-model", "created": now,
            "choices": [{"index": 0, "delta": {"content": "Hello there"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "my-private-model", "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                      "total_tokens": 30},
        },
    ]

    from app import router_cache

    fake = AsyncMock()
    fake.acompletion = AsyncMock(return_value=_stream_iter_from(chunks))

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    # Request the unlisted model directly: both the requested and the served
    # id must miss the catalog, or Tier 2 prices the request normally and the
    # floor is never exercised.
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "my-private-model",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    spent = await _spent(factory, key_id)
    cap = 1 * MICROCENTS_PER_CENT
    # Fail closed, but bounded: the cap advances without being consumed whole.
    assert 0 < spent < cap
    rows = await _log_rows(factory)
    assert rows[0].cost_microcents == spent


def _blocking_response_with(*, model: str, content: str | None, usage: dict) -> dict:
    now = int(time.time())
    return {
        "id": "chatcmpl-1", "object": "chat.completion",
        "model": model, "created": now,
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": content},
        }],
        "usage": usage,
    }


async def _chat_with_model(client, model: str, *, stream: bool = False) -> dict:
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": stream,
        },
    )
    return {"status": r.status_code, "body": r.text}


async def test_zero_usage_with_delivered_content_is_estimated(budget_app, monkeypatch):
    """Zero usage frames with real content fall back to the estimator.

    Settlement matrix cell: a provider that reports `0` tokens for a delivered
    completion must not settle at zero — the charge comes from the delivery.
    """
    client, factory, key_id = budget_app

    from app import router_cache

    fake = AsyncMock()
    fake.acompletion = AsyncMock(
        return_value=_blocking_response_with(
            model="gpt-4o-mini", content="Hello there",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    )

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    result = await _chat(client)

    assert result["status"] == 200
    spent = await _spent(factory, key_id)
    cap = 1 * MICROCENTS_PER_CENT
    assert 0 < spent < cap
    rows = await _log_rows(factory)
    assert rows[0].cost_microcents == spent


async def test_empty_completion_with_zero_usage_charges_nothing(budget_app, monkeypatch):
    """Zero usage with a genuinely empty completion settles at zero.

    Settlement matrix cell: nothing delivered means nothing to charge. The
    estimator must not invent a completion from an empty response.
    """
    client, factory, key_id = budget_app

    from app import router_cache

    fake = AsyncMock()
    fake.acompletion = AsyncMock(
        return_value=_blocking_response_with(
            model="gpt-4o-mini", content="",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    )

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    result = await _chat(client)

    assert result["status"] == 200
    assert await _spent(factory, key_id) == 0


async def test_upstream_failure_before_delivery_charges_nothing(budget_app, monkeypatch):
    """A fault that delivered nothing charges nothing.

    Settlement matrix cell: failures before any content are not billable, for
    either path. The prompt may have gone upstream, but with no delivery and
    no measurement there is no honest charge.
    """
    client, factory, key_id = budget_app

    from app import router_cache

    fake = AsyncMock()
    fake.acompletion = AsyncMock(side_effect=RuntimeError("upstream down"))

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    for stream in (False, True):
        result = await _chat(client, stream=stream)
        assert result["status"] != 200
    assert await _spent(factory, key_id) == 0


async def test_zero_cap_rejects_everything(budget_app):
    """A zero budget limit rejects all requests, including free models.

    Product contract: `budget_limit_cents=0` means no lifetime spend is
    authorized, so dispatch is refused up front. A negative limit behaves the
    same (it authorizes even less); an absent limit means uncapped.
    """
    client, factory, key_id = budget_app

    async with factory() as s:
        row = await s.get(ApiKey, key_id)
        row.budget_limit_cents = 0
        await s.commit()

    assert (await _chat(client))["status"] == 429
    assert (await _chat(client, stream=True))["status"] == 429

    async with factory() as s:
        row = await s.get(ApiKey, key_id)
        row.budget_limit_cents = -5
        await s.commit()

    assert (await _chat(client))["status"] == 429

    async with factory() as s:
        row = await s.get(ApiKey, key_id)
        row.budget_limit_cents = None
        await s.commit()

    assert (await _chat(client))["status"] == 200


async def test_unmeasured_charge_covers_every_ending():
    """Unit matrix for `_unmeasured_charge`: every ending has a defined charge.

    - Client disconnect with nothing delivered: the prompt went upstream, so
      the prompt estimate is charged.
    - Upstream fault with nothing delivered: zero.
    - Fault after a delivery: the delivery price, same as a clean completion.
    """
    from app.routes.chat import (
        _STREAM_CLIENT_DISCONNECT,
        _STREAM_COMPLETED,
        _STREAM_UPSTREAM_ERROR,
        _unmeasured_charge,
    )

    charge, estimate = _unmeasured_charge(
        delivered=False, ending=_STREAM_CLIENT_DISCONNECT,
        prompt_chars=400, completion_chars=0,
        model_id="gpt-4o-mini", fallback_model="gpt-4o-mini",
    )
    assert charge > 0
    assert estimate == {"prompt_tokens": 100, "completion_tokens": 0}

    charge, estimate = _unmeasured_charge(
        delivered=False, ending=_STREAM_UPSTREAM_ERROR,
        prompt_chars=400, completion_chars=0,
        model_id="gpt-4o-mini", fallback_model="gpt-4o-mini",
    )
    assert (charge, estimate) == (0, None)

    faulted, _ = _unmeasured_charge(
        delivered=True, ending=_STREAM_UPSTREAM_ERROR,
        prompt_chars=400, completion_chars=40,
        model_id="gpt-4o-mini", fallback_model="gpt-4o-mini",
    )
    clean, _ = _unmeasured_charge(
        delivered=True, ending=_STREAM_COMPLETED,
        prompt_chars=400, completion_chars=40,
        model_id="gpt-4o-mini", fallback_model="gpt-4o-mini",
    )
    assert faulted == clean > 0
