"""Async SQLAlchemy engine factory.

SQLite is the default, Postgres opt-in via DATABASE_URL=postgresql+asyncpg://...
"""

from __future__ import annotations

import structlog
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger(__name__)

# How long a writer waits (ms) for a contended lock before erroring. 5s is the
# standard recipe: enough to survive a burst of concurrent writes, short enough
# that a genuinely stuck lock can't hang a request path.
SQLITE_BUSY_TIMEOUT_MS = 5_000


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


def _unwrap_sqlite3(dbapi_connection):
    """Reach the real ``sqlite3.Connection`` behind aiosqlite + SQLAlchemy.

    aiosqlite's execute is async, so pragmas must run on the innermost sync
    sqlite3 handle. SQLAlchemy's ``AsyncAdaptedConnection`` wraps the aiosqlite
    ``Connection``, which wraps ``sqlite3.Connection``; unwrap defensively.
    """
    aio = getattr(dbapi_connection, "_connection", None)
    if aio is None:
        aio = getattr(dbapi_connection, "_dbapi_connection", None)
    if aio is None:
        return None
    return getattr(aio, "_conn", None)


def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    """Apply SQLite durability/locking pragmas on every new connection.

    Each pragma's *return value* is meaningful: SQLite reports a failed
    `journal_mode=WAL` by returning the prior mode ("delete") rather than
    raising, so a silent no-op here would leave us believing we have WAL when
    we do not. We log a warning instead of swallowing it.
    """
    sqlite3_conn = _unwrap_sqlite3(dbapi_connection)
    if sqlite3_conn is None:
        return
    cursor = sqlite3_conn.cursor()
    try:
        mode = cursor.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
        if mode.lower() != "wal":
            url = str(connection_record.engine.url)
            logger.warning("sqlite_wal_not_applied", url=redacted_url(url), mode=mode)
        # NORMAL is the WAL-recommended durability level: safe across app
        # crashes and avoids an fsync per WAL write (FULL would pay that cost).
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
        cursor.execute("PRAGMA synchronous=NORMAL;")
    finally:
        cursor.close()


def build_engine(database_url: str) -> AsyncEngine:
    """Build an async engine for the given URL.

    SQLite gets WAL mode plus a bounded ``busy_timeout`` so concurrent writers
    (the chat path finalizes ``RequestLog`` rows while other requests read)
    stop raising ``database is locked``. Postgres uses defaults.
    """
    if database_url.startswith("sqlite"):
        engine = create_async_engine(
            database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )

        # `build_engine` can be called more than once per process (notably in
        # tests); avoid stacking duplicate connect listeners on the same engine.
        if not event.contains(engine.sync_engine, "connect", _configure_sqlite_connection):
            event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

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
