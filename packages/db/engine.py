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

    This is a pool ``connect`` hook: ANY exception raised here fails every
    connection attempt and takes the process down. Degraded (previous journal
    mode) is strictly better than dead, so nothing in here may propagate.
    """
    sqlite3_conn = _unwrap_sqlite3(dbapi_connection)
    if sqlite3_conn is None:
        logger.warning("sqlite_pragmas_skipped", reason="could not unwrap sqlite3 connection")
        return
    cursor = None
    try:
        try:
            cursor = sqlite3_conn.cursor()
        except Exception as exc:  # noqa: BLE001 - hook must not propagate
            logger.warning(
                "sqlite_pragmas_not_applied",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return
        # WAL may fail two ways: returning the prior mode, or raising (e.g.
        # read-only files raise "attempt to write a readonly database").
        # Both are the same operational fact — degraded, not dead.
        try:
            mode = cursor.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
            if str(mode).lower() != "wal":
                logger.warning("sqlite_wal_not_applied", mode=mode)
        except Exception as exc:  # noqa: BLE001 - hook must not propagate
            logger.warning(
                "sqlite_wal_not_applied",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        try:
            # NORMAL is the WAL-recommended durability level: safe across app
            # crashes and avoids an fsync per WAL write (FULL would pay that cost).
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
            cursor.execute("PRAGMA synchronous=NORMAL;")
        except Exception as exc:  # noqa: BLE001 - hook must not propagate
            logger.warning(
                "sqlite_pragmas_not_applied",
                error=str(exc),
                error_type=type(exc).__name__,
            )
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


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

        # Fresh engine per call, so no dedup guard is needed (the previous
        # `event.contains` check was dead code — `engine.sync_engine` is a
        # new object each time).
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
