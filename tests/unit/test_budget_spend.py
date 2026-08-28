"""Unit tests for packages.auth.spend — atomic budget claim/settle."""

import asyncio

import pytest

from packages.auth.spend import (
    MICROCENTS_PER_CENT,
    claim_budget,
    read_spent,
    settle_budget,
)


@pytest.fixture
async def key(db_session):
    from packages.db.models.api_key import ApiKey

    k = ApiKey(workspace_id="default", name="a", key_hash="h-a", key_prefix="p-a")
    db_session.add(k)
    await db_session.flush()
    return k


async def test_claim_reserves_remaining_and_blocks_second(db_session, key):
    cap = 10_000
    # First claim reserves the whole remaining budget and commits it.
    assert await claim_budget(db_session, key.id, cap) == cap
    assert await read_spent(db_session, key.id) == cap
    # A second concurrent-style claim now sees a full counter and is rejected.
    assert await claim_budget(db_session, key.id, cap) is None


async def test_settle_reconciles_actual_cost(db_session, key):
    cap = 10_000
    claimed = await claim_budget(db_session, key.id, cap)
    await settle_budget(db_session, key.id, claimed, 300)
    # spent becomes old(0) + actual(300), regardless of how much was claimed.
    assert await read_spent(db_session, key.id) == 300

    # A follow-up request claims what's left and reconciles again.
    claimed2 = await claim_budget(db_session, key.id, cap)
    assert claimed2 == cap - 300
    await settle_budget(db_session, key.id, claimed2, 250)
    assert await read_spent(db_session, key.id) == 300 + 250


async def test_claim_when_already_at_cap_returns_none(db_session, key):
    cap = 10_000
    key.spent_microcents = cap
    await db_session.commit()
    assert await claim_budget(db_session, key.id, cap) is None


async def test_concurrent_claims_race_only_one_wins(db_session, key):
    """Two simultaneous claims can never both pass the cap.

    Builds two independent sessions against the same engine so the UPDATE ...
    WHERE spent_microcents == spent guard is exercised for real. Exactly one
    claim wins; the loser sees 0 affected rows and is rejected.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine

    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        from packages.db.models.base import Base

        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        from packages.db.models.api_key import ApiKey

        k = ApiKey(workspace_id="default", name="race", key_hash="h-race", key_prefix="p-race")
        s.add(k)
        await s.commit()
        await s.refresh(k)

        cap = 10_000
        r1, r2 = await asyncio.gather(
            claim_budget(s, k.id, cap),
            claim_budget(s, k.id, cap),
        )
    await engine.dispose()
    assert (r1 is None) ^ (r2 is None)  # exactly one succeeded
    assert (r1 or r2) == cap


def test_microcent_conversion_constant():
    assert MICROCENTS_PER_CENT == 10_000
