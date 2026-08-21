"""Key-management authorization tests.

A restricted key (model_allowlist or budget_limit_cents set) must never be
able to mint, list, or revoke API keys — otherwise it could mint an
unrestricted sibling and bypass its own restrictions entirely.
See issue: restricted-key privilege escalation via POST /v1/keys.
"""

import pytest


@pytest.fixture
async def seeded_keys(db_session):
    """Seed the workspace root key plus one restricted and one budgeted key.

    Returns (root_full_key, restricted_full_key, budgeted_full_key).
    """
    from app.seed import seed_initial_state
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    seed = await seed_initial_state(db_session)
    assert seed.api_key is not None

    def _make(**kwargs) -> str:
        full_key, key_hash, key_prefix = generate_api_key()
        row = ApiKey(
            workspace_id="default",
            name=kwargs.pop("name", "test"),
            key_hash=key_hash,
            key_prefix=key_prefix,
            **kwargs,
        )
        db_session.add(row)
        return full_key

    # flush once so all rows land before any request reads them
    restricted = _make(name="restricted", model_allowlist=["gpt-4o-mini"])
    budgeted = _make(name="budgeted", budget_limit_cents=500)
    await db_session.commit()
    return seed.api_key, restricted, budgeted


@pytest.fixture
async def keys_app(db_session, monkeypatch):
    """FastAPI app with auth middleware and only the /v1/keys routes mounted."""
    monkeypatch.setenv("DATABASE_URL", str(db_session.bind.url))
    from fastapi import FastAPI

    from app.middleware.auth import AuthMiddleware
    from packages.db import session as session_mod

    class _PassthroughFactory:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False  # propagate, don't close — fixture owns the session

    monkeypatch.setattr(session_mod, "_session_factory", lambda: _PassthroughFactory())

    from app.routes.keys import router as keys_router

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(keys_router)
    return app


async def _client(app):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.parametrize("which", [1, 2], ids=["allowlist-restricted", "budget-restricted"])
async def test_restricted_key_cannot_create_keys(keys_app, seeded_keys, db_session, which):
    keys, restricted, budgeted = seeded_keys
    caller = (restricted, budgeted)[which - 1]
    async with await _client(keys_app) as c:
        r = await c.post(
            "/v1/keys",
            json={"name": "escalated"},
            headers={"Authorization": f"Bearer {caller}"},
        )
    assert r.status_code == 403
    # The escalation must not have persisted anything.
    from sqlalchemy import func, select

    from packages.db.models.api_key import ApiKey

    count = (
        await db_session.execute(select(func.count()).select_from(ApiKey))
    ).scalar_one()
    assert count == 3  # root + restricted + budgeted, nothing new


@pytest.mark.parametrize("which", [1, 2], ids=["allowlist-restricted", "budget-restricted"])
async def test_restricted_key_cannot_list_keys(keys_app, seeded_keys, which):
    keys, restricted, budgeted = seeded_keys
    caller = (restricted, budgeted)[which - 1]
    async with await _client(keys_app) as c:
        r = await c.get("/v1/keys", headers={"Authorization": f"Bearer {caller}"})
    assert r.status_code == 403


async def test_restricted_key_cannot_revoke_keys(keys_app, seeded_keys, db_session):
    _, restricted, _budgeted = seeded_keys
    from sqlalchemy import select

    from packages.db.models.api_key import ApiKey

    rows = (await db_session.execute(select(ApiKey))).scalars().all()
    target_id = next(r.id for r in rows if r.name == "default")
    async with await _client(keys_app) as c:
        r = await c.delete(
            f"/v1/keys/{target_id}",
            headers={"Authorization": f"Bearer {restricted}"},
        )
    assert r.status_code == 403
    target = next(r for r in rows if r.name == "default")
    assert target.is_active  # untouched


async def test_unrestricted_key_retains_full_management(keys_app, seeded_keys):
    root, _restricted, _budgeted = seeded_keys
    h = {"Authorization": f"Bearer {root}"}
    async with await _client(keys_app) as c:
        listed = await c.get("/v1/keys", headers=h)
        assert listed.status_code == 200

        created = await c.post("/v1/keys", json={"name": "child"}, headers=h)
        assert created.status_code == 201
        child_id = created.json()["id"]

        revoked = await c.delete(f"/v1/keys/{child_id}", headers=h)
        assert revoked.status_code == 204
