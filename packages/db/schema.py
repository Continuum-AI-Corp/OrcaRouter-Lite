"""Indexes that have to be created by hand on boot.

`create_all` builds tables that are missing, but leaves alone any table
that's already there — so an index I add to an existing table never
reaches a deployment that upgraded. There's no migration tool in here to
do it properly, so the ones the request path depends on get applied
here instead.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# IF NOT EXISTS, so on a fresh database where create_all already made them
# this is a no-op.
_RUNTIME_INDEXES = (
    # the per-key sum the budget cap does on every request
    "CREATE INDEX IF NOT EXISTS ix_requests_log_api_key_id "
    "ON requests_log (api_key_id)",
)


async def ensure_runtime_indexes(conn: AsyncConnection) -> None:
    """Run after create_all, while the tables are known to exist."""
    for ddl in _RUNTIME_INDEXES:
        await conn.execute(text(ddl))
