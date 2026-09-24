"""Idempotent startup schema migrations for columns added after the first release.

`Base.metadata.create_all` creates new tables but never alters existing ones, so a
deployment that already ran a release (a SQLite named volume, a fly.io/Postgres
volume) keeps an `api_keys` table without the `spent_microcents` column. After an
upgrade the ORM would then `SELECT` every mapped column and hit "no such column"
on every authenticated request — a 503 for the whole API.

`ensure_budget_columns` is run once at boot, after `create_all`, and is safe to
call on every start: it inspects the live schema and only acts when the column is
missing.
"""

from __future__ import annotations

from sqlalchemy import inspect, text


async def ensure_budget_columns(engine) -> None:
    """Add `spent_microcents` to `api_keys` if absent, seeded from request history.

    Also widens `budget_limit_cents` to BIGINT on Postgres (the microcent scale
    can exceed int4) and creates the `ix_requests_log_api_key_spend` index that
    create_all only builds on fresh databases. All steps are no-ops on a fresh
    database.
    """
    async with engine.begin() as conn:
        cols = {
            c["name"]
            for c in await conn.run_sync(lambda sync: inspect(sync).get_columns("api_keys"))
        }
        is_postgres = engine.dialect.name == "postgresql"

        if "spent_microcents" not in cols:
            await conn.execute(
                text(
                    "ALTER TABLE api_keys ADD COLUMN spent_microcents BIGINT "
                    "NOT NULL DEFAULT 0"
                )
            )
            # Seed lifetime spend from historical request logs so an existing key's
            # cap is not silently reset to zero (which would re-grant a leaked key
            # a full new budget).
            await conn.execute(
                text(
                    "UPDATE api_keys SET spent_microcents = ("
                    "  SELECT COALESCE(SUM(cost_microcents), 0) FROM requests_log "
                    "  WHERE requests_log.api_key_id = api_keys.id"
                    ") WHERE spent_microcents = 0"
                )
            )

        if is_postgres and "budget_limit_cents" in cols:
            await conn.execute(
                text("ALTER TABLE api_keys ALTER COLUMN budget_limit_cents TYPE BIGINT")
            )

        # The model declares ix_requests_log_api_key_spend (api_key_id,
        # is_deleted); create_all only builds it on fresh databases, so an
        # upgraded deployment would drift. is_deleted has existed since the
        # first release (SoftDeleteMixin), so the index is always creatable.
        idx = {
            i["name"]
            for i in await conn.run_sync(
                lambda sync: inspect(sync).get_indexes("requests_log")
            )
        }
        if "ix_requests_log_api_key_spend" not in idx:
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_requests_log_api_key_spend "
                    "ON requests_log (api_key_id, is_deleted)"
                )
            )
