"""`requests_log.route_note` — why a request was routed (or refused) the way
it was. Fresh databases get it from create_all; upgraded ones from the
startup migration, which must be idempotent like ensure_budget_columns."""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.db.engine import build_engine
from packages.db.migrate import ensure_route_note_column
from packages.db.models.base import Base
from packages.db.models.request_log import RequestLog


def _row(**kw) -> RequestLog:
    base = dict(
        workspace_id="default", api_key_id="k", trace_id="t", model_requested="auto",
        model_resolved="gpt-4o-mini", provider="openai", routing_strategy="balanced",
        input_tokens=1, output_tokens=1, latency_ms=1, status_code=200,
    )
    base.update(kw)
    return RequestLog(**base)


async def _columns(engine) -> set[str]:
    async with engine.connect() as conn:
        return {c["name"] for c in await conn.run_sync(lambda s: sa_inspect(s).get_columns("requests_log"))}


async def test_fresh_schema_has_route_note(tmp_sqlite_url):
    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    assert "route_note" in await _columns(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(_row(route_note="free"))
        s.add(_row(trace_id="t2"))
        await s.commit()
        notes = set((await s.execute(select(RequestLog.route_note))).scalars())
    assert notes == {"free", None}
    await engine.dispose()


async def test_migration_adds_route_note_to_an_upgraded_database(tmp_sqlite_url):
    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE requests_log DROP COLUMN route_note"))
    assert "route_note" not in await _columns(engine)

    await ensure_route_note_column(engine)
    await ensure_route_note_column(engine)  # idempotent on every boot

    assert "route_note" in await _columns(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(_row(route_note="no_fallback"))
        await s.commit()
        assert (await s.execute(select(RequestLog.route_note))).scalar_one() == "no_fallback"
    await engine.dispose()
