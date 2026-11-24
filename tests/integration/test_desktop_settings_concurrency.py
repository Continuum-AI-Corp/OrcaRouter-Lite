"""Two settings saves in flight at once both land.

The panel and the setup window can each save settings while the other's
request is still running, each with its own database session. Each sends
only the fields it changed, so neither may overwrite the other's field with
the stale value it read.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.routes import desktop
from packages.auth.types import KeyContext
from packages.db.models.workspace import Workspace


async def test_concurrent_partial_saves_keep_both_fields(db_session, monkeypatch):
    from app.seed import seed_initial_state

    await seed_initial_state(db_session)
    ws_id = (await db_session.execute(select(Workspace.id))).scalars().first()
    kc = KeyContext(key_id="k", workspace_id=ws_id, name="desktop-app")
    Session = async_sessionmaker(db_session.bind, expire_on_commit=False)

    real = desktop._workspace
    both_read = asyncio.Barrier(2)

    async def slow_read(db, workspace_id):
        ws = await real(db, workspace_id)
        try:
            # Hold each request after its read until the other has read too.
            await asyncio.wait_for(both_read.wait(), timeout=0.5)
        except TimeoutError:
            pass  # serialized: the other request is waiting for us
        return ws

    monkeypatch.setattr(desktop, "_workspace", slow_read)

    async def save(**fields):
        async with Session() as db:
            body = desktop.DesktopSettings.model_validate(fields)
            return await desktop.put_settings_route(body, kc=kc, db=db)

    await asyncio.gather(save(daily_budget_cents=2_000), save(budget_mode="stop"))

    async with Session() as db:
        ws = (await db.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
        assert ws.settings_json["desktop"] == {"daily_budget_cents": 2_000, "budget_mode": "stop"}
