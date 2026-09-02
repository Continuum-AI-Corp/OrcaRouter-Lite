"""A live stream has to keep its hold alive.

The TTL is what reaps holds for requests that died, but it can't tell a
dead request from a slow one: a stream's log row only lands when the
stream ends, so a stream still running past the TTL would drop out of the
cap sum while carrying on spending against it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.routes.chat import _BudgetHold
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext
from packages.db.models.base import Base
from packages.db.models.budget_hold import BudgetHold


def _kc() -> KeyContext:
    return KeyContext(
        key_id="key-1", workspace_id="default", name="k", budget_limit_cents=100
    )


def _body() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
    )


async def _factory(tmp_sqlite_url):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _live_holds(db) -> int:
    """What the cap gate would actually count — same filter it uses."""
    from app.routes.chat import _HOLD_TTL

    return (
        await db.execute(
            select(func.count())
            .select_from(BudgetHold)
            .where(BudgetHold.last_seen_at > datetime.now(timezone.utc) - _HOLD_TTL)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_a_beat_pulls_an_aged_hold_back_inside_the_ttl(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    engine, factory = await _factory(tmp_sqlite_url)

    async with factory() as db:
        hold = _BudgetHold(db)
        await hold.acquire(_kc(), _body(), ["gpt-4o-mini"])

        # as the gate sees it, this request died over 15 minutes ago
        await db.execute(
            update(BudgetHold).values(
                last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=16)
            )
        )
        await db.commit()
        assert await _live_holds(db) == 0

        await hold.heartbeat()
        assert await _live_holds(db) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_beats_are_spaced_out(tmp_sqlite_url, monkeypatch):
    """One write per stream per half-TTL, not one per chunk."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    engine, factory = await _factory(tmp_sqlite_url)

    async with factory() as db:
        hold = _BudgetHold(db)
        await hold.acquire(_kc(), _body(), ["gpt-4o-mini"])
        await hold.heartbeat()  # lands, and starts the interval

        await db.execute(
            update(BudgetHold).values(
                last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=16)
            )
        )
        await db.commit()

        for _ in range(5):
            await hold.heartbeat()  # all inside the interval: no writes
        assert await _live_holds(db) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_beating_a_hold_that_was_never_taken_is_a_no_op(tmp_sqlite_url, monkeypatch):
    """No cap on the key means no row, and no key with a cap is ever refused."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    engine, factory = await _factory(tmp_sqlite_url)

    async with factory() as db:
        await _BudgetHold(db).heartbeat()
        assert await _live_holds(db) == 0

    await engine.dispose()
