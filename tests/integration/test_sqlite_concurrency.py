"""Regression tests: SQLite WAL/busy_timeout and degraded-path handling.

With WAL journal mode and a bounded busy_timeout (set in `build_engine`),
concurrent writers/reader+writer must not raise ``sqlite3.OperationalError:
database is locked``. The original 50-writer fast workload was not
discriminating — it passed even without pragmas — so these tests use
real contention (BEGIN + sleep + barrier) and a negative control.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.auth.hashing import hash_api_key
from packages.db import engine as engine_module
from packages.db.engine import SQLITE_BUSY_TIMEOUT_MS, build_engine
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base


@pytest.mark.asyncio
async def test_sqlite_lock_contention_under_concurrent_writes():
    """Concurrent writes with overlapping transactions must not raise lock errors.

    Each writer does BEGIN + SELECT + sleep(0.02) + COMMIT, overlapping via a
    barrier, so the RESERVED lock is actually contended. With busy_timeout=0
    this would raise ``database is locked``; with the pragmas (WAL + 5000ms)
    writers serialize and all succeed. The explicit PRAGMA assertions below
    remain the primary config check — the workload proves the pragmas are
    load-bearing, not just set.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite+aiosqlite:///{db_path}"

    try:
        engine = build_engine(db_url)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)

        raw_key = "sk-orca-test123456789012345678901234"
        key_hash = hash_api_key(raw_key)

        async with factory() as s:
            s.add(
                ApiKey(
                    id="key_concurrency_test",
                    workspace_id="default",
                    name="test-key",
                    key_hash=key_hash,
                    key_prefix="sk-orca-....1234",
                    is_active=True,
                )
            )
            await s.commit()

        # The engine must have actually applied the durability pragmas.
        async with engine.connect() as conn:
            mode = (await conn.execute(text("PRAGMA journal_mode;"))).scalar()
            assert str(mode).lower() == "wal", f"Expected WAL journal mode, got {mode}"
            busy = (await conn.execute(text("PRAGMA busy_timeout;"))).scalar()
            assert int(busy) == SQLITE_BUSY_TIMEOUT_MS, f"Expected busy_timeout={SQLITE_BUSY_TIMEOUT_MS}, got {busy}"

        barrier = asyncio.Barrier(50)

        async def _concurrent_write(op_id: int) -> None:
            await barrier.wait()
            async with factory() as session:
                # Hold the RESERVED lock past the default 0ms timeout so
                # contention is real — without busy_timeout this fails.
                await session.execute(text("BEGIN IMMEDIATE"))
                row = (
                    await session.execute(select(ApiKey).where(ApiKey.id == "key_concurrency_test"))
                ).scalar_one_or_none()
                assert row is not None
                row.last_used_at = datetime.now(timezone.utc)
                await asyncio.sleep(0.02)
                await session.commit()

        results = await asyncio.gather(
            *[_concurrent_write(i) for i in range(50)],
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 0, (
            f"Expected 0 database lock errors under concurrent load, but encountered "
            f"{len(errors)} failures! First error: {errors[0] if errors else 'None'}"
        )

        await engine.dispose()
    finally:
        for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_sqlite_degraded_path_still_connects_in_memory():
    """Degraded path must not take the pool down.

    :memory: databases return ``memory`` for PRAGMA journal_mode=WAL instead
    of raising, and the previous code accessed ``connection_record.engine``
    (which does not exist) in that branch — failing every connection. This
    test closes the gap CI currently cannot see: it asserts the engine still
    connects and basic queries work even when WAL cannot be applied.
    """

    engine = build_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            # WAL cannot apply to :memory: — should degrade to 'memory', not crash.
            mode = (await conn.execute(text("PRAGMA journal_mode;"))).scalar()
            assert str(mode).lower() == "memory"
            # busy_timeout must still be applied even when WAL degrades.
            busy = (await conn.execute(text("PRAGMA busy_timeout;"))).scalar()
            assert int(busy) == SQLITE_BUSY_TIMEOUT_MS
            val = (await conn.execute(text("SELECT 1"))).scalar()
            assert int(val) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_degraded_path_on_pragma_raise_still_connects(monkeypatch):
    """Hook must survive pragma failures (e.g. read-only DB raises)."""

    class FakeCursor:
        def execute(self, *_a, **_kw):
            raise RuntimeError("injected pragma failure")  # noqa: TRY003

        def fetchone(self):  # pragma: no cover
            return ["wal"]

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(engine_module, "_unwrap_sqlite3", lambda _c: FakeConn())

    engine = build_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            val = (await conn.execute(text("SELECT 1"))).scalar()
            assert int(val) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_pragmas_skipped_when_unwrap_fails(monkeypatch):
    """If _unwrap_sqlite3 returns None, hook must warn and not crash."""

    monkeypatch.setattr(engine_module, "_unwrap_sqlite3", lambda _c: None)
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            val = (await conn.execute(text("SELECT 1"))).scalar()
            assert int(val) == 1
    finally:
        # restore for other tests (module-level mock cleared by monkeypatch)
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_cursor_allocation_failure_still_connects(monkeypatch):
    """Hook must survive sqlite3 cursor() allocation failure."""

    class FakeConn:
        def cursor(self):
            raise RuntimeError("injected cursor failure")  # noqa: TRY003

    monkeypatch.setattr(engine_module, "_unwrap_sqlite3", lambda _c: FakeConn())
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            val = (await conn.execute(text("SELECT 1"))).scalar()
            assert int(val) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_reader_writer_contention_is_load_bearing():
    """Negative control: reader+writer must fail with busy=0, succeed with WAL+busy."""

    async def _run_one(use_pragmas: bool) -> str:
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db_url = f"sqlite+aiosqlite:///{db_path}"
        if use_pragmas:
            eng = build_engine(db_url)
        else:

            def _set_raw_pragmas(dbapi_conn, _rec):
                aio = getattr(dbapi_conn, "_connection", None) or getattr(dbapi_conn, "_dbapi_connection", None)
                if aio is None:
                    return
                sconn = getattr(aio, "_conn", None)
                if sconn is None:
                    return
                cur = sconn.cursor()
                try:
                    try:
                        cur.execute("PRAGMA journal_mode=DELETE;")
                    except Exception:
                        pass
                    try:
                        cur.execute("PRAGMA busy_timeout=0;")
                    except Exception:
                        pass
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass

            eng = create_async_engine(
                db_url,
                connect_args={"check_same_thread": False},
                future=True,
            )
            event.listen(eng.sync_engine, "connect", _set_raw_pragmas)

        try:
            async with eng.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            fac = async_sessionmaker(eng, expire_on_commit=False)
            async with fac() as s:
                s.add(
                    ApiKey(
                        id="key_contention_test",
                        workspace_id="default",
                        name="test-key",
                        key_hash=hash_api_key("sk-orca-test123456789012345678901234"),
                        key_prefix="sk-orca-....1234",
                        is_active=True,
                    )
                )
                await s.commit()

            async def reader():
                async with fac() as sess:
                    await sess.execute(text("BEGIN"))
                    row = (await sess.execute(select(ApiKey).where(ApiKey.id == "key_contention_test"))).scalar_one()
                    assert row is not None
                    await asyncio.sleep(0.35)
                    await sess.commit()
                    return "reader done"

            async def writer():
                await asyncio.sleep(0.05)
                async with fac() as sess:
                    row = (await sess.execute(select(ApiKey).where(ApiKey.id == "key_contention_test"))).scalar_one()
                    row.name = "writer-update"
                    await sess.commit()
                    return "writer success"

            results = await asyncio.gather(reader(), writer(), return_exceptions=True)
            writer_res = results[1]
            if isinstance(writer_res, Exception):
                return f"failed:{type(writer_res).__name__}"
            return str(writer_res)
        finally:
            await eng.dispose()
            for p in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
                try:
                    if os.path.exists(p):
                        os.unlink(p)
                except OSError:
                    pass

    raw_result = await _run_one(use_pragmas=False)
    wal_result = await _run_one(use_pragmas=True)

    assert raw_result.startswith("failed:") and "OperationalError" in raw_result, (
        f"Expected raw DELETE/busy=0 to fail with OperationalError/database is locked, got {raw_result!r}"
    )
    assert wal_result == "writer success", f"Expected WAL/busy=5000 to succeed, got {wal_result!r}"
