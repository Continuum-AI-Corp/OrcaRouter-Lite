"""Unit tests for packages.auth.spend — atomic budget charge under a hard cap."""

import asyncio

import pytest

from packages.auth import spend as spend_mod
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


async def test_concurrent_charges_never_exceed_cap(tmp_sqlite_url):
    """Two simultaneous charges that together would exceed the cap are bounded.

    A file-backed URL, because `:memory:` hands back a `StaticPool`: both
    sessions would then share one DBAPI connection, the statements would
    serialise inside it, and the atomic `UPDATE ... WHERE spent + actual <= cap`
    guard would never meet a concurrent writer. Over a file each session gets
    its own connection, and SQLite's single writer plus the pool's busy timeout
    still makes the outcome deterministic — one charge fits, the other's guard
    matches no row and its clamp fills the counter to exactly `cap`.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.api_key import ApiKey
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        k = ApiKey(workspace_id="default", name="race", key_hash="h-race", key_prefix="p-race")
        s.add(k)
        await s.commit()
        await s.refresh(k)

    cap = 10_000
    async with factory() as s1, factory() as s2:
        r1, r2 = await asyncio.gather(
            charge_budget(s1, k.id, cap, 6_000),
            charge_budget(s2, k.id, cap, 6_000),
        )
    # Read the winner's outcome from a session that took part in neither charge.
    async with factory() as reader:
        final = await read_spent(reader, k.id)
    await engine.dispose()

    assert (r1 is True) + (r2 is True) == 1
    assert final == cap


async def test_stale_identity_map_cannot_clobber_a_concurrent_charge(tmp_sqlite_url):
    """A session that loaded the key before a concurrent charge must not flush
    its stale value over the DB's atomic result.

    The request path runs charge_budget on the same session that auth already
    used to load the ApiKey. Without
    synchronize_session=False the ORM's 'auto' sync evaluates the SET in Python
    against that stale identity-map copy, marks it dirty, and the commit
    flushes it as a plain unguarded UPDATE — silently dropping the other
    session's committed charge.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.api_key import ApiKey
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        k = ApiKey(
            workspace_id="default", name="sync", key_hash="h-sync", key_prefix="p-sync"
        )
        s.add(k)
        await s.commit()
        kid = k.id

    cap = 10_000
    async with factory() as stale, factory() as winner:
        # `stale` mirrors the request session: the row is loaded at spent=0
        # before the other session's charge commits.
        loaded = (
            await stale.execute(select(ApiKey).where(ApiKey.id == kid))
        ).scalar_one()
        assert await charge_budget(winner, kid, cap, 6_000) is True
        assert await charge_budget(stale, kid, cap, 2_000) is True
        # The charge left the identity-map copy untouched: the DB row is the
        # only source of truth for the counter.
        assert loaded.spent_microcents == 0

    async with factory() as reader:
        final = await read_spent(reader, kid)
    await engine.dispose()
    assert final == 8_000


def test_microcent_conversion_constant():
    assert MICROCENTS_PER_CENT == 10_000


@pytest.fixture
async def park_factory(tmp_sqlite_url):
    """Session factory on a fresh schema, installed as the app's global factory.

    The park regression tests below need the module-global session factory
    (the fold and the probes do not take a session), while the charge tests
    above use an explicit session. Installed and cleared like the fixture in
    test_budget_park.py.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    previous = session_mod._session_factory
    session_mod._session_factory = maker
    spend_mod._unsettled.clear()
    try:
        yield maker
    finally:
        session_mod._session_factory = previous
        spend_mod._unsettled.clear()
        await engine.dispose()


async def _make_park_key(maker, *, key_id: str, spent: int = 0) -> str:
    from packages.db.models.api_key import ApiKey

    async with maker() as s:
        s.add(
            ApiKey(
                id=key_id,
                workspace_id="default",
                name=key_id,
                key_hash=f"h-{key_id}",
                key_prefix=f"p-{key_id}",
                spent_microcents=spent,
            )
        )
        await s.commit()
    return key_id


async def test_durability_probe_compares_amounts_not_existence(park_factory):
    """A row holding less than the obligation is not durable for it.

    Regression for the P1 where `_park_is_durable` answered True on mere row
    existence: a 100-microcent row must not vouch for a 150-microcent hold.
    """
    from packages.db.models.budget_park import BudgetPark

    await _make_park_key(park_factory, key_id="k")
    async with park_factory() as s:
        s.add(BudgetPark(trace_id="t1", api_key_id="k", microcents=100))
        await s.commit()

    assert (
        await spend_mod._park_is_durable(
            trace_id="t1", api_key_id="k", expected_microcents=150
        )
        is False
    )
    assert (
        await spend_mod._park_is_durable(
            trace_id="t1", api_key_id="k", expected_microcents=100
        )
        is True
    )


async def test_pending_counts_hold_excess_over_durable_row(park_factory):
    """A 100-microcent row with a 150 hold still counts 150 toward the cap.

    Regression for the P1 where pending zeroed the whole hold when its trace
    had any row: the uncovered 50 must keep counting.
    """
    from packages.db.models.budget_park import BudgetPark

    await _make_park_key(park_factory, key_id="k")
    async with park_factory() as s:
        s.add(BudgetPark(trace_id="t1", api_key_id="k", microcents=100))
        await s.commit()
    spend_mod._hold("k", "t1", 150)

    assert await spend_mod.pending_parked_spend("k") == 150


async def test_fold_keeps_hold_excess_when_refile_cannot_land(park_factory, monkeypatch):
    """Row 100, hold 150, re-file fails: the fold bills 100 and keeps 50 held.

    Regression for the P1's concrete scenario (write outage: the row stays at
    100 while the hold is 150). The excess must survive under a fresh identity,
    never be dropped.
    """
    from packages.db.models.budget_park import BudgetPark

    await _make_park_key(park_factory, key_id="k", spent=0)
    async with park_factory() as s:
        s.add(BudgetPark(trace_id="t1", api_key_id="k", microcents=100))
        await s.commit()
    spend_mod._hold("k", "t1", 150)

    async def _failing_insert(**kw):
        return False

    monkeypatch.setattr(spend_mod, "_insert_park", _failing_insert)
    moved = await spend_mod.settle_parked_spend("k", cap_microcents=10_000)

    assert moved == 100
    async with park_factory() as s:
        assert await spend_mod.read_spent(s, "k") == 100
    assert sum(spend_mod._unsettled.get("k", {}).values()) == 50


async def test_full_bill_delete_is_amount_guarded(park_factory):
    """A delete naming a stale amount matches nothing; the raised row survives.

    Regression for the P1 where the full-bill DELETE matched by trace_id
    alone: a concurrent re-file raising the row 100 -> 175 must make the stale
    fold conflict instead of deleting 175 while billing 100.
    """
    from sqlalchemy import delete, select

    from packages.db.models.budget_park import BudgetPark

    await _make_park_key(park_factory, key_id="k", spent=0)
    async with park_factory() as s:
        s.add(BudgetPark(trace_id="t", api_key_id="k", microcents=100))
        await s.commit()

    # The concurrent re-file lands first and raises the row.
    async with park_factory() as s:
        from sqlalchemy import update

        await s.execute(
            update(BudgetPark)
            .where(BudgetPark.trace_id == "t", BudgetPark.api_key_id == "k")
            .values(microcents=175)
        )
        await s.commit()

    # The stale fold's guarded delete (amount 100) must match nothing.
    async with park_factory() as s:
        stale = await s.execute(
            delete(BudgetPark).where(
                BudgetPark.trace_id == "t",
                BudgetPark.api_key_id == "k",
                BudgetPark.microcents == 100,
            )
        )
        assert stale.rowcount == 0
        await s.rollback()

    # And a fresh fold bills the raised amount in full — nothing is lost.
    moved = await spend_mod.settle_parked_spend("k", cap_microcents=10_000)
    assert moved == 175
    async with park_factory() as s:
        assert await spend_mod.read_spent(s, "k") == 175
        remaining = (
            await s.execute(
                select(BudgetPark.trace_id).where(BudgetPark.api_key_id == "k")
            )
        ).all()
    assert remaining == []
