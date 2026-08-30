"""Async SQLAlchemy engine factory.

SQLite is the default, Postgres opt-in via DATABASE_URL=postgresql+asyncpg://...
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def redacted_url(database_url: str) -> str:
    """URL safe for logging: password replaced, garbage input never echoed.

    Uses SQLAlchemy's own renderer so every driver scheme is handled the
    same way (`postgresql+asyncpg://user:***@host/db`). Unparseable input
    degrades to a fixed placeholder instead of being reflected back into
    logs.
    """
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable-database-url>"


def _register_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Concurrent-write readiness for the default SQLite backend.

    Stock SQLite runs DELETE-journal with a zero busy timeout: two
    overlapping write transactions — AuthMiddleware's `last_used_at`
    commit racing a RequestLog insert — collide instantly with
    "database is locked" and surface as 500/503s under concurrent
    traffic. WAL lets readers proceed during a write and busy_timeout
    makes writers queue for the lock instead of erroring;
    synchronous=NORMAL keeps WAL's fsync cost sane (the durability
    tradeoff only risks the last transactions on an OS crash, never
    database corruption).

    journal_mode=WAL is idempotent and persisted in the database file, so
    it also upgrades pre-existing deployments on first connect. On
    in-memory databases it is a harmless no-op.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def build_engine(database_url: str) -> AsyncEngine:
    """Build an async engine for the given URL.

    SQLite gets `check_same_thread=False` for the async adapter, a 30s
    busy timeout and WAL (see `_register_sqlite_pragmas`); Postgres uses
    defaults with pool pre-ping.
    """
    if database_url.startswith("sqlite"):
        engine = create_async_engine(
            database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )
        _register_sqlite_pragmas(engine)
        return engine
    return create_async_engine(database_url, future=True, pool_pre_ping=True)


_engine: AsyncEngine | None = None


def get_engine(database_url: str) -> AsyncEngine:
    """Process-wide singleton."""
    global _engine
    if _engine is None:
        _engine = build_engine(database_url)
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
