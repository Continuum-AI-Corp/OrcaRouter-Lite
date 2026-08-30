"""Check SQLite survives concurrent writes.

Stock SQLite turns two overlapping writes into "database is locked",
which hit us as 500/503. I now set WAL, synchronous=NORMAL and a 5s
busy timeout on every connection.
"""

import pytest
from sqlalchemy import select, text

from packages.db.engine import build_engine


@pytest.mark.asyncio
async def test_sqlite_engine_enables_wal_and_busy_timeout(tmp_sqlite_url):
    engine = build_engine(tmp_sqlite_url)
    try:
        async with engine.connect() as conn:
            journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
            busy_timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
            synchronous = (await conn.execute(text("PRAGMA synchronous"))).scalar()
        assert journal_mode.lower() == "wal"
        assert busy_timeout == 5000
        # 1 = NORMAL (0 = OFF, 2 = FULL).
        assert synchronous == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_writers_do_not_error(tmp_sqlite_url):
    """Two sessions committing at once must both succeed.

    This failed with "database is locked" before i set WAL and a busy
    timeout. Now the second writer waits for the first.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import get_engine
    from packages.db.models.base import Base
    from packages.db.models.workspace import Workspace

    engine = get_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _write(n: int) -> None:
        async with factory() as s:
            s.add(Workspace(id=f"ws-{n}", name=f"ws-{n}", slug=f"ws-{n}"))
            await s.commit()

    await asyncio.gather(_write(1), _write(2), _write(3), _write(4))

    async with factory() as s:
        rows = (await s.execute(select(Workspace))).scalars().all()
        assert {w.id for w in rows} == {"ws-1", "ws-2", "ws-3", "ws-4"}

    from packages.db.engine import dispose_engine

    await dispose_engine()
