"""Upgrade-path coverage for ensure_budget_columns (packages/db/migrate.py).

create_all never alters existing tables, so an upgraded deployment starts from
a legacy schema: api_keys without spent_microcents and requests_log without the
spend index. These tests build that legacy state by creating the real schema,
seeding rows, then dropping exactly what the pre-budget release lacked — and
pin that the startup migration restores it: (a) the column seeded from
historical request-log spend, (b) the composite index, (c) idempotency across
repeated boots, (d) the ORM (and thus auth) working again.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db.engine import build_engine
from packages.db.migrate import ensure_budget_columns
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base
from packages.db.models.request_log import RequestLog


async def _legacy_deploy_engine(tmp_sqlite_url):
    """Engine over a DB shaped like the last released schema, with one
    budgeted key that already burned 2500 microcents of history."""
    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        row = ApiKey(
            workspace_id="w1", name="leaked-then-capped", key_hash="h",
            key_prefix="p", budget_limit_cents=100, spent_microcents=2500,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        s.add(RequestLog(
            workspace_id="w1", api_key_id=row.id,
            trace_id="t1", model_requested="gpt-4o-mini",
            model_resolved="gpt-4o-mini", provider="openai",
            routing_strategy="balanced", input_tokens=5, output_tokens=2,
            cost_microcents=2500, latency_ms=10, status_code=200,
        ))
        await s.commit()
    # Downgrade to the pre-budget schema: drop the column and the index that
    # only the new release's metadata declares.
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS ix_requests_log_api_key_spend"))
        await conn.execute(text("ALTER TABLE api_keys DROP COLUMN spent_microcents"))
    await engine.dispose()
    return build_engine(tmp_sqlite_url)


async def test_ensure_budget_columns_upgrades_legacy_schema(tmp_sqlite_url):
    engine = await _legacy_deploy_engine(tmp_sqlite_url)
    try:
        await ensure_budget_columns(engine)

        async with engine.connect() as conn:
            # Seeded from history: a key that already burned 2500 microcents
            # must not get a fresh full budget on upgrade.
            spent = await conn.scalar(
                text("SELECT spent_microcents FROM api_keys WHERE workspace_id = 'w1'")
            )
            assert spent == 2500

            idx_names = {
                i["name"]
                for i in await conn.run_sync(
                    lambda sync: sa_inspect(sync).get_indexes("requests_log")
                )
            }
            assert "ix_requests_log_api_key_spend" in idx_names

        # Idempotent across restarts: a second boot changes nothing.
        await ensure_budget_columns(engine)
        async with engine.connect() as conn:
            assert await conn.scalar(
                text("SELECT spent_microcents FROM api_keys WHERE workspace_id = 'w1'")
            ) == 2500
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
            row = (await s.execute(select(ApiKey))).scalar_one()
        assert row.spent_microcents == 2500
        assert row.budget_limit_cents == 100
    finally:
        await engine.dispose()
