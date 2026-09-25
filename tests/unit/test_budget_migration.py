"""Upgrade-path coverage for ensure_budget_columns (packages/db/migrate.py).

create_all never alters existing tables, so an upgraded deployment starts from
a legacy schema: api_keys without spent_microcents and requests_log without the
spend index. These tests build that legacy state by creating the real schema,
seeding rows, then dropping exactly what the pre-budget release lacked — and
pin that the startup migration restores it: (a) each key's counter seeded from
its own request-log history, (b) the composite index, (c) idempotency across
repeated boots, (d) the ORM (and thus auth) working again, and (e) a seed that
survives the boot that was supposed to run it dying halfway.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db.engine import build_engine
from packages.db.migrate import ensure_budget_columns
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base
from packages.db.models.budget_park import BudgetPark
from packages.db.models.request_log import RequestLog


async def _legacy_deploy_engine(tmp_sqlite_url):
    """Engine over a DB shaped like the last released schema.

    Three keys, each with its own request history, so the seed's own predicates
    are the only thing that can make the numbers come out right: `w1` is capped
    and burned 2500 microcents, `w2` is capped and burned 700 (drop the
    `api_key_id` correlation and both read the table total), and `w3` is uncapped
    with 400 of history that must stay uncounted — nothing ever charges an
    uncapped key, so its counter means nothing until it gets a cap.
    """
    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        for ws, cents, burned in (("w1", 100, 2500), ("w2", 50, 700), ("w3", None, 400)):
            row = ApiKey(
                workspace_id=ws, name=f"{ws}-key", key_hash=f"h-{ws}",
                key_prefix=f"p-{ws}", budget_limit_cents=cents,
                spent_microcents=burned,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            s.add(RequestLog(
                workspace_id=ws, api_key_id=row.id,
                trace_id=f"t-{ws}", model_requested="gpt-4o-mini",
                model_resolved="gpt-4o-mini", provider="openai",
                routing_strategy="balanced", input_tokens=5, output_tokens=2,
                cost_microcents=burned, latency_ms=10, status_code=200,
            ))
            await s.commit()
    # Downgrade to the pre-budget schema: drop the column and the index that
    # only the new release's metadata declares.
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS ix_requests_log_api_key_spend"))
        await conn.execute(text("ALTER TABLE api_keys DROP COLUMN spent_microcents"))
    await engine.dispose()
    return build_engine(tmp_sqlite_url)


async def _spent(engine, workspace_id: str) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(
            text("SELECT spent_microcents FROM api_keys WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )


async def test_ensure_budget_columns_upgrades_legacy_schema(tmp_sqlite_url):
    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    try:
        await ensure_budget_columns(engine)

        # Seeded from each key's own history: a key that already burned 2500
        # microcents must not get a fresh full budget on upgrade, and the key
        # next to it must not be billed for its neighbour's traffic.
        assert await _spent(engine, "w1") == 2500
        assert await _spent(engine, "w2") == 700
        # The uncapped key is never charged, so restoring a total for it would
        # aggregate the one unbounded table to compute a number nothing reads.
        assert await _spent(engine, "w3") == 0

        async with engine.connect() as conn:
            idx_names = {
                i["name"]
                for i in await conn.run_sync(
                    lambda sync: sa_inspect(sync).get_indexes("requests_log")
                )
            }
            assert "ix_requests_log_api_key_spend" in idx_names

        # Idempotent across restarts: a second boot changes nothing.
        await ensure_budget_columns(engine)
        assert await _spent(engine, "w1") == 2500
        assert await _spent(engine, "w2") == 700
        assert await _spent(engine, "w3") == 0
    finally:
        await engine.dispose()


async def test_seed_repairs_a_boot_that_died_before_it(tmp_sqlite_url):
    """A half-applied upgrade reseeds, on the next boot, by itself.

    The column and the seed are two statements and one is not proof of the
    other: on SQLite the `ALTER` is durable the instant it executes while the
    seed is DML in the transaction a kill, a dropped connection, or the 5s
    `busy_timeout` this aggregate can hit rolls back. Gating the seed on the
    column's absence — which is what the first version did — makes that boot the
    only one that ever could have seeded, so every key that predates the release
    keeps a full fresh allowance forever, silently, with no repair path.
    """
    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    try:
        # The state that boot left behind: column present, every counter zero,
        # history intact.
        async with engine.begin() as conn:
            await conn.execute(
                text("ALTER TABLE api_keys ADD COLUMN spent_microcents BIGINT "
                     "NOT NULL DEFAULT 0")
            )
        assert await _spent(engine, "w1") == 0

        await ensure_budget_columns(engine)
        assert await _spent(engine, "w1") == 2500
        assert await _spent(engine, "w2") == 700
    finally:
        await engine.dispose()


async def test_orm_reads_work_after_upgrade(tmp_sqlite_url):
    # The original 503 failure mode: the ORM SELECTs every mapped column, so
    # without the migration every authenticated request broke on the upgraded
    # database. After ensure_budget_columns the ApiKey select must succeed.
    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    try:
        await ensure_budget_columns(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            row = (
                await s.execute(select(ApiKey).where(ApiKey.workspace_id == "w1"))
            ).scalar_one()
        assert row.spent_microcents == 2500
        assert row.budget_limit_cents == 100
    finally:
        await engine.dispose()


async def test_seed_runs_after_the_index_it_aggregates_through(tmp_sqlite_url):
    """The first post-upgrade boot must not full-scan requests_log per key.

    The seed is a correlated SUM over requests_log, and the only thing that
    makes it cheap is ix_requests_log_api_key_spend. Building that index after
    the seed means the boot that restores every pre-release counter — and every
    later boot that finds a half-applied upgrade to repair — does it with a full
    scan of the one table that grows without bound.

    The exact-list assertion also pins that the seed is emitted once per boot:
    it runs on every start now, so a second copy is a second aggregate over the
    same table for no reason.
    """
    from sqlalchemy import event

    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    order: list[str] = []
    try:
        def _record(conn, cursor, statement, parameters, context, executemany):
            if "ix_requests_log_api_key_spend" in statement:
                order.append("index")
            elif "UPDATE api_keys SET spent_microcents" in statement:
                order.append("seed")

        event.listen(engine.sync_engine, "before_cursor_execute", _record)
        try:
            await ensure_budget_columns(engine)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _record)

        assert order == ["index", "seed"]
    finally:
        await engine.dispose()


async def test_ensure_budget_columns_survives_a_racing_boot(tmp_sqlite_url, monkeypatch):
    """The loser of a concurrent-boot ALTER still boots, and still seeds.

    Every worker runs this at startup, and the first boot after an upgrade
    starts several of them at once against one database. Both inspect the
    schema before either alters it, so the loser's ALTER meets a column that
    appeared in between and the driver rejects it with "duplicate column
    name" — which used to escape into the lifespan and keep that worker down.
    """
    import packages.db.migrate as migrate

    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    try:
        # The other boot gets there first: the column is committed, so this
        # process's inspection is now stale relative to the schema.
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE api_keys ADD COLUMN spent_microcents BIGINT "
                    "NOT NULL DEFAULT 0"
                )
            )
        inspector = sa_inspect(engine.sync_engine)

        class _StaleSchema:
            def __init__(self, inner):
                self._inner = inner

            def get_columns(self, table_name):
                return [
                    c for c in self._inner.get_columns(table_name)
                    if c["name"] != "spent_microcents"
                ]

            def __getattr__(self, name):
                return getattr(self._inner, name)

        monkeypatch.setattr(migrate, "inspect", lambda _sync: _StaleSchema(inspector))
        await ensure_budget_columns(engine)

        async with engine.connect() as conn:
            # It went on to seed the column the winner added — before the fix
            # the boot died on the ALTER and never reached this.
            assert await conn.scalar(
                text("SELECT spent_microcents FROM api_keys WHERE workspace_id = 'w1'")
            ) == 2500
    finally:
        await engine.dispose()


async def test_ensure_budget_columns_creates_budget_parks_table(tmp_sqlite_url):
    """A deployment that predates durable recovery gets the park table.

    `create_all` covers fresh databases, but an upgraded SQLite volume keeps
    its old schema — without this step the first give-up would have nowhere
    durable to park, and the cap would silently reopen after every restart.
    """
    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS budget_parks"))
        await ensure_budget_columns(engine)

        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync: sa_inspect(sync).get_table_names()
            )
            assert "budget_parks" in tables

        # The table the migration created actually holds a parked obligation.
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            s.add(BudgetPark(trace_id="park-t1", api_key_id="k1", microcents=900))
            await s.commit()
        async with factory() as s:
            row = (
                await s.execute(
                    select(BudgetPark).where(BudgetPark.trace_id == "park-t1")
                )
            ).scalar_one()
            assert row.microcents == 900

        # Idempotent across restarts: a second boot changes nothing.
        await ensure_budget_columns(engine)
    finally:
        await engine.dispose()
