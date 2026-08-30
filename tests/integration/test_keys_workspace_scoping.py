"""Regression tests for /v1/keys workspace scoping and restriction inheritance.

Covers two issues filed against the route set:

- IDOR: GET /v1/keys and DELETE /v1/keys/{id} ignored workspace_id, so any
  authenticated key could enumerate and revoke every key in the database.
- Privilege escalation: POST /v1/keys minted keys with model_allowlist=NULL
  and budget_limit_cents=NULL regardless of the caller's own restrictions,
  letting a deliberately-restricted key mint itself an unrestricted sibling.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app
from app.seed import seed_initial_state
from packages.auth.hashing import hash_api_key
from packages.db import session as session_mod
from packages.db.models.api_key import ApiKey
from packages.db.models.workspace import Workspace


def _mk_key(raw: str, workspace_id: str, name: str, **extra) -> ApiKey:
    return ApiKey(
        workspace_id=workspace_id,
        name=name,
        key_hash=hash_api_key(raw),
        key_prefix="sk-orca-...." + raw[-4:],
        **extra,
    )


@pytest.mark.asyncio
async def test_list_and_revoke_are_scoped_to_callers_workspace(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    async with factory() as s:
        seed = await seed_initial_state(s)
        # A second workspace holding one key of its own.
        s.add(Workspace(id="other-ws", name="Other", slug="other"))
        other_key = _mk_key("sk-orca-otherwskey0001", "other-ws", "other")
        s.add(other_key)
        await s.commit()
        other_key_id = other_key.id

    app = create_app()
    auth = {"Authorization": f"Bearer {seed.api_key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        # List: the other workspace's key must not appear.
        resp = await client.get("/v1/keys", headers=auth)
        assert resp.status_code == 200
        listed_ids = {k["id"] for k in resp.json()["keys"]}
        assert other_key_id not in listed_ids

        # Revoke: must 404 and leave the foreign key untouched.
        resp = await client.delete(f"/v1/keys/{other_key_id}", headers=auth)
        assert resp.status_code == 404

    async with factory() as s:
        row = (await s.execute(
            select(ApiKey).where(ApiKey.id == other_key_id)
        )).scalar_one()
        assert row.is_active, "foreign key was revoked across the workspace boundary"


@pytest.mark.asyncio
async def test_created_key_inherits_caller_restrictions(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    async with factory() as s:
        seed = await seed_initial_state(s)
        restricted = _mk_key(
            "sk-orca-restrictedparent1",
            "default",
            "restricted",
            model_allowlist=["gpt-4o-mini"],
            budget_limit_cents=100,
        )
        s.add(restricted)
        await s.commit()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/v1/keys",
            json={"name": "escape-hatch"},
            headers={"Authorization": "Bearer sk-orca-restrictedparent1"},
        )
        assert resp.status_code == 201
        child_id = resp.json()["id"]

    async with factory() as s:
        child = (await s.execute(
            select(ApiKey).where(ApiKey.id == child_id)
        )).scalar_one()
        # The child must be at least as restricted as the parent — a key
        # can never mint itself out of its own allowlist/budget.
        assert child.model_allowlist == ["gpt-4o-mini"]
        assert child.budget_limit_cents == 100

    # And the unrestricted seed key still works as before (NULL restrictions
    # propagate as NULL — operators minting admin keys keep that ability).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/v1/keys",
            json={"name": "normal-child"},
            headers={"Authorization": f"Bearer {seed.api_key}"},
        )
        assert resp.status_code == 201
        child_id = resp.json()["id"]
    async with factory() as s:
        child = (await s.execute(
            select(ApiKey).where(ApiKey.id == child_id)
        )).scalar_one()
        assert child.model_allowlist is None
        assert child.budget_limit_cents is None
