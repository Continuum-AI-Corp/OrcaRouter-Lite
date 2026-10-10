"""Unit tests for the budget park ledger in packages.auth.spend.

A settlement that gives up leaves a delivered cost parked against its key. These
tests pin the properties the cap depends on: a park is recorded once per
trace_id, a parked amount keeps counting against the cap, a fold bills the
oldest debt first and never double-bills, and a row already present in the
request log is cleared instead of billed twice.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.auth import spend
from packages.auth.spend import (
    budget_precheck,
    pending_parked_spend,
    read_spent,
    record_unsettled_spend,
    settle_parked_spend,
)
from packages.db import session as session_mod
from packages.db.models.api_key import ApiKey
from packages.db.models.budget_park import BudgetPark
from packages.db.models.request_log import RequestLog


@pytest.fixture
async def factory(tmp_sqlite_url):
    """Session factory on a fresh schema, installed as the app's global factory."""
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    previous = session_mod._session_factory
    session_mod._session_factory = maker
    spend._unsettled.clear()
    try:
        yield maker
    finally:
        session_mod._session_factory = previous
        spend._unsettled.clear()
        await engine.dispose()


async def _make_key(maker, *, key_id: str, spent: int = 0) -> str:
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


async def _spent(maker, key_id: str) -> int:
    async with maker() as s:
        return await read_spent(s, key_id)


async def _park_rows(maker, key_id: str) -> list[tuple[str, int]]:
    async with maker() as s:
        rows = (
            await s.execute(
                select(BudgetPark.trace_id, BudgetPark.microcents)
                .where(BudgetPark.api_key_id == key_id)
                .order_by(BudgetPark.trace_id)
            )
        ).all()
    return [(trace, int(micro)) for trace, micro in rows]


async def test_record_unsettled_spend_persists_one_row_per_trace(factory):
    await _make_key(factory, key_id="k1")
    await record_unsettled_spend(trace_id="t1", api_key_id="k1", microcents=500)
    # A retried write of the same settlement must not park it twice.
    await record_unsettled_spend(trace_id="t1", api_key_id="k1", microcents=500)
    assert await _park_rows(factory, "k1") == [("t1", 500)]


async def test_record_ignores_zero_and_missing_identifiers(factory):
    await _make_key(factory, key_id="k1")
    await record_unsettled_spend(trace_id="t0", api_key_id="k1", microcents=0)
    await record_unsettled_spend(trace_id="", api_key_id="k1", microcents=5)
    await record_unsettled_spend(trace_id="t2", api_key_id="", microcents=5)
    assert await _park_rows(factory, "k1") == []
    assert spend._unsettled == {}


async def test_pending_parked_spend_sums_durable_rows(factory):
    await _make_key(factory, key_id="k1")
    await record_unsettled_spend(trace_id="a", api_key_id="k1", microcents=300)
    await record_unsettled_spend(trace_id="b", api_key_id="k1", microcents=200)
    assert await pending_parked_spend("k1") == 500


async def test_memory_hold_counts_when_the_database_is_unavailable(monkeypatch):
    """With no session factory the only record is the memory hold; it must count."""
    previous = session_mod._session_factory
    session_mod._session_factory = None
    spend._unsettled.clear()
    try:
        await record_unsettled_spend(trace_id="m1", api_key_id="k9", microcents=400)
        assert await pending_parked_spend("k9") == 400
    finally:
        session_mod._session_factory = previous
        spend._unsettled.clear()


async def test_memory_hold_is_bounded_by_key_not_by_failed_settlements(monkeypatch):
    """One entry per key, however many settlements fail during an outage.

    Entries only leave the hold when a fold commits, and no fold can commit
    while the database is down, so a per-settlement entry would grow for as
    long as the outage lasted.
    """
    previous = session_mod._session_factory
    session_mod._session_factory = None
    spend._unsettled.clear()
    try:
        for i in range(1000):
            await record_unsettled_spend(
                trace_id=f"t{i}", api_key_id="k9", microcents=1
            )
        assert len(spend._unsettled) == 1
        # Bounded, but nothing is lost: the full amount still counts.
        assert await pending_parked_spend("k9") == 1000
        # And it stays attributable to one key.
        assert await pending_parked_spend("other-key") == 0
    finally:
        session_mod._session_factory = previous
        spend._unsettled.clear()


async def test_merging_into_a_hold_raises_a_colliding_park_row(factory):
    """A hold that merged more settlements must not lose the difference.

    The row for the hold's trace can already exist when the fold re-files it —
    the original write landed and its ack was lost. Re-filing then collides, and
    treating that collision as success would drop everything merged in since.
    """
    await _make_key(factory, key_id="k1", spent=0)
    async with factory() as s:
        s.add(BudgetPark(trace_id="t", api_key_id="k1", microcents=100))
        await s.commit()

    # The writer believed all three failed and merged them into one hold.
    spend._hold("k1", "t", 100)
    spend._hold("k1", "t2", 50)
    spend._hold("k1", "t3", 25)

    moved = await settle_parked_spend("k1", cap_microcents=10_000)

    assert moved == 175
    assert await _spent(factory, "k1") == 175
    assert await _park_rows(factory, "k1") == []
    assert spend._unsettled == {}


async def test_fold_bills_the_oldest_park_first_and_trims_the_partial(factory):
    await _make_key(factory, key_id="k1", spent=0)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with factory() as s:
        s.add_all(
            [
                BudgetPark(trace_id="new", api_key_id="k1", microcents=600,
                           created_at=base + timedelta(seconds=2)),
                BudgetPark(trace_id="old", api_key_id="k1", microcents=500,
                           created_at=base),
            ]
        )
        await s.commit()

    # Cap of 800: "old" (500) fits whole, "new" (600) only has 300 of room.
    moved = await settle_parked_spend("k1", cap_microcents=800)

    assert moved == 800
    assert await _spent(factory, "k1") == 800
    # "old" is fully billed and gone; "new" is trimmed to its 300 remainder.
    assert await _park_rows(factory, "k1") == [("new", 300)]


async def test_fold_clears_a_park_whose_charge_is_already_logged(factory):
    """A park whose request-log row landed was already billed; folding it again doubles the charge."""
    await _make_key(factory, key_id="k1", spent=100)
    async with factory() as s:
        s.add(BudgetPark(trace_id="done", api_key_id="k1", microcents=250))
        s.add(
            RequestLog(
                workspace_id="default",
                api_key_id="k1",
                trace_id="done",
                cost_microcents=250,
                model_requested="m",
                model_resolved="m",
                provider="openai",
                routing_strategy="passthrough",
                input_tokens=10,
                output_tokens=20,
                latency_ms=5,
                status_code=200,
            )
        )
        await s.commit()

    moved = await settle_parked_spend("k1", cap_microcents=10_000)

    assert moved == 0
    assert await _spent(factory, "k1") == 100
    assert await _park_rows(factory, "k1") == []


async def test_fold_does_nothing_when_the_cap_has_no_room(factory):
    await _make_key(factory, key_id="k1", spent=1_000)
    await record_unsettled_spend(trace_id="t", api_key_id="k1", microcents=50)
    assert await settle_parked_spend("k1", cap_microcents=1_000) == 0
    assert await _spent(factory, "k1") == 1_000
    assert await _park_rows(factory, "k1") == [("t", 50)]


async def test_precheck_counts_pending_park_against_the_cap(factory):
    """A parked obligation blocks dispatch even when the fold cannot commit."""
    await _make_key(factory, key_id="k1", spent=900)
    await record_unsettled_spend(trace_id="t", api_key_id="k1", microcents=200)
    async with factory() as s:
        assert await budget_precheck(s, "k1", cap_microcents=1_000) >= 1_000


async def test_precheck_folds_pending_park_into_the_counter(factory):
    await _make_key(factory, key_id="k1", spent=0)
    await record_unsettled_spend(trace_id="t", api_key_id="k1", microcents=300)
    async with factory() as s:
        total = await budget_precheck(s, "k1", cap_microcents=10_000)
    assert total == 300
    assert await _spent(factory, "k1") == 300
    assert await _park_rows(factory, "k1") == []


async def test_precheck_treats_an_unreadable_ledger_as_full_debt(factory, monkeypatch):
    await _make_key(factory, key_id="k1")

    async def _unreadable(_key):
        return None

    monkeypatch.setattr(spend, "pending_parked_spend", _unreadable)
    async with factory() as s:
        assert await budget_precheck(s, "k1", cap_microcents=777) == 777


async def test_cancel_after_a_landed_park_commit_leaves_no_hold(factory, monkeypatch):
    """A commit that landed before the cancellation is durable: no memory hold.

    A hold alongside the durable row lets another worker fold the row and this
    worker re-file the same obligation later, billing it twice.
    """
    await _make_key(factory, key_id="k", spent=0)
    real_insert = spend._insert_park

    async def insert_then_cancel(**kw):
        assert await real_insert(**kw)
        raise asyncio.CancelledError()

    monkeypatch.setattr(spend, "_insert_park", insert_then_cancel)
    with pytest.raises(asyncio.CancelledError):
        await record_unsettled_spend(trace_id="t", api_key_id="k", microcents=600)
    monkeypatch.setattr(spend, "_insert_park", real_insert)

    assert spend._unsettled.get("k") in (None, {})
    await settle_parked_spend("k", cap_microcents=10_000)
    await settle_parked_spend("k", cap_microcents=10_000)
    assert await _spent(factory, "k") == 600


async def test_cancel_before_any_commit_still_holds_the_amount(factory, monkeypatch):
    """If the park never landed, a cancellation must still hold the obligation."""
    await _make_key(factory, key_id="k", spent=0)

    async def insert_cancelled(**kw):
        raise asyncio.CancelledError()

    monkeypatch.setattr(spend, "_insert_park", insert_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await record_unsettled_spend(trace_id="t", api_key_id="k", microcents=600)
    assert spend._unsettled.get("k") == {"t": 600}
