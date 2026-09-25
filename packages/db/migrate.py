"""Idempotent startup schema migrations for columns added after the first release.

`Base.metadata.create_all` creates new tables but never alters existing ones, so a
deployment that already ran a release (a SQLite named volume, a fly.io/Postgres
volume) keeps an `api_keys` table without the `spent_microcents` column. After an
upgrade the ORM would then `SELECT` every mapped column and hit "no such column"
on every authenticated request — a 503 for the whole API.

`ensure_budget_columns` runs at boot, after `create_all`, on every start: it
inspects the live schema, only acts where the change is missing, tolerates
another process racing it to the same change, and re-attempts a repair that an
earlier boot applied only halfway.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, inspect, text
from sqlalchemy.exc import DBAPIError

from packages.db.models.budget_park import BudgetPark
from packages.db.units import MICROCENTS_PER_CENT


def _already_applied(err: DBAPIError) -> bool:
    """Whether a DDL failure means someone else applied the change first."""
    msg = str(err).lower()
    return (
        "already exists" in msg
        or "duplicate column" in msg
        # Concurrent CREATE INDEX on Postgres can lose the race at the catalog
        # insert rather than the IF NOT EXISTS probe, surfacing as a verror on
        # pg_class's unique index instead of the usual "already exists".
        or "pg_class_relname_nsp_index" in msg
    )


async def _apply_ddl(conn, statement: str) -> None:
    """Run one startup DDL statement, tolerating a boot that raced us to it.

    Every worker runs this in its lifespan, so the first boot after an upgrade
    has several processes inspecting a schema none of them has altered yet. Each
    then issues the same statement and all but one fail — "column ... already
    exists" on Postgres, "duplicate column name" on SQLite — which is success
    from here, not a reason to keep the worker from booting. The failure is
    caught inside a SAVEPOINT because on Postgres an error would otherwise abort
    the whole transaction and take the rest of the startup with it.
    """
    try:
        async with conn.begin_nested():
            await conn.execute(text(statement))
    except DBAPIError as err:
        if not _already_applied(err):
            raise


async def ensure_budget_columns(engine) -> None:
    """Make `api_keys.spent_microcents` correct, whatever schema it started from.

    Adds the column when an upgraded volume lacks it, and repairs lifetime spend
    against historical request logs on every boot so the `ALTER` is never mistaken
    for proof that the seed ran. Also widens `budget_limit_cents` to BIGINT on
    Postgres (the column is scaled into microcents for every comparison against
    spend, and an int4 ceiling is about 214,748 dollars of lifetime budget),
    creates the `ix_requests_log_api_key_spend` index that create_all only builds
    on fresh databases, and creates `budget_parks` for deployments that predate
    the durable-recovery release — a lost settlement needs somewhere every
    worker, and every reboot, can see it. Each step costs nothing on a database
    that needs none of it — there the repair is a single indexed UPDATE that
    matches no row.
    """
    async with engine.begin() as conn:
        tables = set(
            await conn.run_sync(lambda sync: inspect(sync).get_table_names())
        )
        cols = {
            c["name"]: c["type"]
            for c in await conn.run_sync(lambda sync: inspect(sync).get_columns("api_keys"))
        }
        is_postgres = engine.dialect.name == "postgresql"

        if BudgetPark.__tablename__ not in tables:
            # `create_all` covers fresh databases; this covers upgrades whose
            # schema predates the table. `checkfirst` keeps a racing boot from
            # failing when the winner creates it first.
            await conn.run_sync(BudgetPark.__table__.create, checkfirst=True)

        # The model declares ix_requests_log_api_key_spend (api_key_id,
        # is_deleted); create_all only builds it on fresh databases, so an
        # upgraded deployment would drift. Built before the seed below, which is
        # a correlated aggregate over requests_log and otherwise full-scans the
        # one table that grows without bound here — once per key, inside the
        # transaction that already holds the api_keys lock. is_deleted has
        # existed since the first release (SoftDeleteMixin), so the index is
        # always creatable.
        idx = {
            i["name"]
            for i in await conn.run_sync(
                lambda sync: inspect(sync).get_indexes("requests_log")
            )
        }
        if "ix_requests_log_api_key_spend" not in idx:
            await _apply_ddl(
                conn,
                "CREATE INDEX IF NOT EXISTS ix_requests_log_api_key_spend "
                "ON requests_log (api_key_id, is_deleted)",
            )

        if "spent_microcents" not in cols:
            await _apply_ddl(
                conn,
                "ALTER TABLE api_keys ADD COLUMN spent_microcents BIGINT "
                "NOT NULL DEFAULT 0",
            )

        # Seed lifetime spend from historical request logs so an existing key's
        # cap is not silently reset to zero (which would re-grant a leaked key
        # a full new budget). Deliberately unfiltered by is_deleted, unlike the
        # analytics reads over the same table: this restores an accrued total,
        # so counting a row a retention job has hidden can only ever make the
        # cap tighter, while honouring the filter would hand a capped key
        # back the spend it was capped for.
        #
        # Not a one-shot `= 0` backfill but a monotonic, cap-clamped repair run
        # every boot: the counter rises to max(current, log total) and is never
        # written past budget_limit_cents scaled to microcents or below its
        # current value. Until #161 wires the per-request charge, request logs
        # are the only recorded spend, so a counter seeded at an earlier boot
        # goes stale as traffic flows and only re-aggregating closes the gap.
        # Afterwards the clamp keeps this a no-op on correct state: a key whose
        # final charge was clamped deliberately under-reports its log total, and
        # raising it back to the SUM would undo the clamp (and overshoot the
        # cap). The strict inequality means a steady-state boot matches no row.
        #
        # It runs beside every ALTER, not only with the column's own, because
        # the ALTER is no record of the seed: on SQLite that DDL is durable the
        # instant it executes while this is DML in the transaction a kill — or
        # the `database is locked` this very aggregate provokes on an upgrade
        # that overlaps the old machine's writes — rolls back, and a gate keyed
        # on the column would then never retry. Capped keys only: an uncapped
        # key is never charged, so its counter stays at zero by design and
        # nothing reads it. The cap is scaled by MICROCENTS_PER_CENT, the same
        # constant the request-path charge uses. GREATEST/LEAST are Postgres;
        # SQLite's scalar MAX/MIN take the same arguments.
        greatest, least = ("GREATEST", "LEAST") if is_postgres else ("MAX", "MIN")
        repaired = (
            f"{least}({greatest}(spent_microcents, ("
            "SELECT CAST(COALESCE(SUM(cost_microcents), 0) AS BIGINT) FROM requests_log "
            "WHERE requests_log.api_key_id = api_keys.id"
            f")), CAST(budget_limit_cents AS BIGINT) * {MICROCENTS_PER_CENT})"
        )
        await conn.execute(
            text(
                f"UPDATE api_keys SET spent_microcents = {repaired} "
                f"WHERE budget_limit_cents IS NOT NULL AND spent_microcents < {repaired}"
            )
        )

        limit_type = cols.get("budget_limit_cents")
        if is_postgres and limit_type is not None and not isinstance(limit_type, BigInteger):
            await _apply_ddl(
                conn, "ALTER TABLE api_keys ALTER COLUMN budget_limit_cents TYPE BIGINT"
            )
