"""Unit tests for packages.auth.spend — atomic budget charge under a hard cap."""

import asyncio

import pytest

from packages.auth.spend import (
    MICROCENTS_PER_CENT,
    charge_budget,
    is_exhausted,
    pending_parked_spend,
    read_spent,
    record_unsettled_spend,
    settle_parked_spend,
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


def test_microcent_conversion_constant():
    assert MICROCENTS_PER_CENT == 10_000


@pytest.fixture
async def parked_env(tmp_sqlite_url):
    """Engine + global session factory, so the park ledger is durable here."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old, session_mod._session_factory = session_mod._session_factory, factory
    try:
        yield factory
    finally:
        session_mod._session_factory = old
        await engine.dispose()


async def _parked_key(factory, *, spent: int = 0):
    from packages.db.models.api_key import ApiKey

    async with factory() as s:
        k = ApiKey(
            workspace_id="default", name="p", key_hash="h-p", key_prefix="p-p",
        )
        s.add(k)
        await s.commit()
        await s.refresh(k)
        if spent:
            await charge_budget(s, k.id, 10_000_000, spent)
        return k.id


async def test_recorded_park_folds_exactly_once(parked_env):
    """A lost settlement is billed once, by the next pre-check — never twice."""
    from packages.auth import spend as spend_mod

    key_id = await _parked_key(parked_env, spent=4_000)
    cap = 10_000
    await record_unsettled_spend(trace_id="t-fold", api_key_id=key_id, microcents=3_000)
    assert await pending_parked_spend(key_id) == 3_000  # durable, not just memory

    spend_mod._unsettled.clear()  # the machine stopped and cold-started

    async with parked_env() as s:
        assert await is_exhausted(s, key_id, cap) is False  # 7_000 of 10_000
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 7_000
        assert await pending_parked_spend(key_id) == 0

    # A second pre-check must not move the same microcents a second time.
    async with parked_env() as s:
        assert await is_exhausted(s, key_id, cap) is False
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 7_000


async def test_duplicate_park_record_is_idempotent(parked_env):
    """Retrying a park write after an ack loss must not record it twice."""
    key_id = await _parked_key(parked_env)
    await record_unsettled_spend(trace_id="t-dup", api_key_id=key_id, microcents=900)
    # The ack never came back, so the caller retries the identical record.
    await record_unsettled_spend(trace_id="t-dup", api_key_id=key_id, microcents=900)
    assert await pending_parked_spend(key_id) == 900


async def test_park_beyond_the_remainder_bills_what_fits(parked_env):
    """An oversized park converges the counter on the cap instead of freezing.

    Moving the whole 2_000 row would push the counter past the cap, and leaving
    it parked whole would refuse the key at a lifetime spend below its limit on
    the strength of a row nothing ever shrinks. So the 1_000 the cap can absorb
    bills and the row keeps the rest: the over-claim stays visible and still
    blocks, and with a park outstanding the counter is now exactly on the cap.
    """
    key_id = await _parked_key(parked_env, spent=9_000)
    cap = 10_000
    await record_unsettled_spend(trace_id="t-big", api_key_id=key_id, microcents=2_000)

    async with parked_env() as s:
        assert await is_exhausted(s, key_id, cap) is True
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 10_000  # the cap, never past it
    assert await pending_parked_spend(key_id) == 1_000  # the debt stays visible

    # A second pre-check must not bill the microcents the first one moved, and
    # the remainder must not clear on its own.
    async with parked_env() as s:
        assert await is_exhausted(s, key_id, cap) is True
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 10_000
    assert await pending_parked_spend(key_id) == 1_000


async def test_parked_queue_drains_oldest_first_as_the_cap_opens(parked_env):
    """What the cap could not absorb waits, and folds the moment it can.

    The oversized head takes the whole allowance, so the younger park behind it
    waits — not lost, just queued. Raising the cap reopens room, and the fold
    keeps its promise that the counter reaches `min(cap, spent + debt)`.
    """
    key_id = await _parked_key(parked_env, spent=9_000)
    await record_unsettled_spend(trace_id="t-old", api_key_id=key_id, microcents=2_000)
    await record_unsettled_spend(trace_id="t-new", api_key_id=key_id, microcents=500)

    assert await settle_parked_spend(key_id, 10_000) == 1_000
    assert await settle_parked_spend(key_id, 10_000) == 0  # no room left
    assert await pending_parked_spend(key_id) == 1_500

    assert await settle_parked_spend(key_id, 11_000) == 1_000
    assert await pending_parked_spend(key_id) == 500
    assert await settle_parked_spend(key_id, 12_000) == 500
    assert await pending_parked_spend(key_id) == 0
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 11_500


async def test_concurrent_folds_bill_the_park_once(parked_env):
    """Two workers folding the same park move it exactly once."""
    key_id = await _parked_key(parked_env)
    await record_unsettled_spend(trace_id="t-race", api_key_id=key_id, microcents=3_000)

    moved = await asyncio.gather(
        settle_parked_spend(key_id, 10_000), settle_parked_spend(key_id, 10_000),
    )
    assert sorted(moved) == [0, 3_000]
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 3_000
    assert await pending_parked_spend(key_id) == 0


async def test_memory_fallback_refiles_once_the_database_recovers(parked_env):
    """An amount held in memory during an outage becomes exactly one park."""
    from packages.db import session as session_mod

    key_id = await _parked_key(parked_env)
    old = session_mod._session_factory
    session_mod._session_factory = None
    try:
        # No session factory: the database might as well be down.
        await record_unsettled_spend(trace_id="t-mem", api_key_id=key_id, microcents=700)
        assert await pending_parked_spend(key_id) == 700
    finally:
        session_mod._session_factory = old

    async with parked_env() as s:
        assert await is_exhausted(s, key_id, 10_000) is False
    assert await pending_parked_spend(key_id) == 0
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 700


async def test_cancelled_refile_keeps_the_memory_copy(parked_env, monkeypatch):
    """Cancelling a memory-to-database refile must not drop the obligation."""
    from packages.auth import spend as spend_mod

    key_id = await _parked_key(parked_env)
    spend_mod._unsettled[(key_id, "t-cancel")] = 500

    async def _cancelled(**kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(spend_mod, "_insert_park", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        await settle_parked_spend(key_id, 10_000)
    assert spend_mod._unsettled[(key_id, "t-cancel")] == 500

    monkeypatch.undo()
    assert await settle_parked_spend(key_id, 10_000) == 500
    async with parked_env() as s:
        assert await read_spent(s, key_id) == 500
