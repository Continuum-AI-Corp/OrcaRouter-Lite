"""Check the index the budget sum needs reaches an upgraded database.

`create_all` skips tables that already exist, so on a deployment that
upgrades, adding `index=True` to a column does nothing — the index is
never created and the per-key sum stays a full scan. I create it by
hand on boot instead.
"""

import pytest
from sqlalchemy import text

from packages.db.engine import build_engine
from packages.db.models.base import Base
from packages.db.schema import ensure_runtime_indexes

_INDEX = "ix_requests_log_api_key_id"


def _indexes(sync_conn) -> set[str]:
    return {r[0] for r in sync_conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}


@pytest.mark.asyncio
async def test_missing_index_is_created_on_an_existing_database(tmp_sqlite_url):
    engine = build_engine(tmp_sqlite_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # what an upgrade looks like: the table is already there
            await conn.execute(text(f"DROP INDEX {_INDEX}"))
            await ensure_runtime_indexes(conn)

        async with engine.connect() as conn:
            names = await conn.run_sync(_indexes)
        assert _INDEX in names
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_running_twice_is_harmless(tmp_sqlite_url):
    engine = build_engine(tmp_sqlite_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await ensure_runtime_indexes(conn)
            await ensure_runtime_indexes(conn)

        async with engine.connect() as conn:
            names = await conn.run_sync(_indexes)
        assert _INDEX in names
    finally:
        await engine.dispose()
