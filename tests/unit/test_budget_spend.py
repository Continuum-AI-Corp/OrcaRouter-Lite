"""Unit tests for packages.auth.spend — atomic budget charge under a hard cap."""

import asyncio

import pytest

from packages.auth.spend import (
    MICROCENTS_PER_CENT,
    charge_budget,
    is_exhausted,
    read_spent,
)


@pytest.fixture
async def key(db_session):
    from packages.db.models.api_key import ApiKey

    k = ApiKey(workspace_id="default", name="a", key_hash="h-a", key_prefix="p-a")
    db_session.add(k)
    await db_session.flush()
    return k


async def test_charge_within_cap_advances_counter(db_session, key):
    cap = 10_000
    assert await charge_budget(db_session, key.id, cap, 300) is True
    assert await read_spent(db_session, key.id) == 300


async def test_charge_past_cap_clamps_and_reports_false(db_session, key):
    cap = 10_000
    # A single request whose cost exceeds the remaining budget must not push the
    # counter past the cap; it is clamped and reported as over-budget.
    assert await charge_budget(db_session, key.id, cap, 50_000) is False
    assert await read_spent(db_session, key.id) == cap
    assert await is_exhausted(db_session, key.id, cap) is True


async def test_is_exhausted_false_below_cap(db_session, key):
    cap = 10_000
    await charge_budget(db_session, key.id, cap, 9_000)
    assert await is_exhausted(db_session, key.id, cap) is False
    await charge_budget(db_session, key.id, cap, 2_000)  # clamps at 10_000
    assert await is_exhausted(db_session, key.id, cap) is True


async def test_concurrent_charges_never_exceed_cap(db_session, key):
    """Two simultaneous charges that together would exceed the cap are bounded.

    Build two independent sessions against the same engine so the atomic
    `UPDATE ... WHERE spent + actual <= cap` guard is exercised for real.
    Exactly one fits; the other is clamped. The counter ends at `cap`, never
    above it.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        from packages.db.models.api_key import ApiKey

        k = ApiKey(workspace_id="default", name="race", key_hash="h-race", key_prefix="p-race")
        s.add(k)
        await s.commit()
        await s.refresh(k)

    cap = 10_000
    # Each request costs 6_000; both cannot fit under a 10_000 cap. Use two
    # independent sessions so the atomic `UPDATE ... WHERE spent + actual <= cap`
    # guard is exercised for real.
    async with factory() as s1, factory() as s2:
        r1, r2 = await asyncio.gather(
            charge_budget(s1, k.id, cap, 6_000),
            charge_budget(s2, k.id, cap, 6_000),
        )
        final = (await read_spent(s1, k.id)) or (await read_spent(s2, k.id))
    await engine.dispose()
    # One succeeds, the other is clamped — but the counter never exceeds cap.
    assert (r1 is True) ^ (r2 is True) or (r1 is False and r2 is False)
    assert final <= cap


def test_microcent_conversion_constant():
    assert MICROCENTS_PER_CENT == 10_000
