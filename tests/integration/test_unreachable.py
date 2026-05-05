"""Tests for GET /v1/analytics/unreachable — the "Models you can't reach" tile.

Drives the dashboard's conversion message: "look what you're missing without
hosted." When hosted is configured, the list must clear to zero (otherwise
the tile would lie about coverage).
"""

from __future__ import annotations

import pytest


async def _client(tmp_sqlite_url, monkeypatch, env_vars: dict | None = None):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    for k, v in (env_vars or {}).items():
        monkeypatch.setenv(k, v)
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient
    return engine, AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    )


@pytest.fixture
async def fresh_client(tmp_sqlite_url, monkeypatch):
    engine, client = await _client(tmp_sqlite_url, monkeypatch)
    async with client as c:
        yield c
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None


async def test_unreachable_backfills_from_static_when_remote_ids_unknown(tmp_sqlite_url, monkeypatch, isolated_env):
    """Codex P2: when orcarouter.ai promotes IDs that this Lite build's
    catalog doesn't know (newer model names, vendor-specific aliases),
    every entry would be filtered out in the catalog lookup loop and
    the conversion tile would regress to empty. After filtering, if
    we have fewer than `limit` entries, top up from the static
    fallback list — same flagships the previous hardcoded build always
    showed."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    # Remote returns IDs that DEFINITELY aren't in the litellm catalog —
    # simulating a Lite build behind on its catalog vs orcarouter.ai's
    # promoted top-N.
    from app import orcarouter_models
    orcarouter_models.reset_cache()

    async def fake_fetch(url: str, timeout: float = 5.0) -> list[str]:
        return [
            "totally-fake-future-model-2099",
            "another-unknown-id",
            "vendor-x/private-fine-tune",
        ]

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", fake_fetch)

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        r = await c.get("/v1/analytics/unreachable?limit=5")
        body = r.json()
        ids = [m["id"] for m in body["unreachable"]]
        # Tile must NOT be empty — backfill from static fallback should
        # populate it with curated flagships even when every remote ID
        # was unknown to the local catalog.
        assert len(ids) >= 3, (
            f"expected backfill from static fallback, got {len(ids)} entries: {ids}"
        )
        # The backfilled IDs must be flagship models from the static
        # curated list (not random catalog entries).
        assert "claude-3-5-sonnet-latest" in ids or "gpt-4o" in ids, (
            f"expected flagship IDs from static fallback, got {ids}"
        )

    await engine.dispose()
    session_mod._session_factory = None
    orcarouter_models.reset_cache()


async def test_unreachable_uses_remote_top_n_list(tmp_sqlite_url, monkeypatch, isolated_env):
    """The unreachable tile must reflect what orcarouter.ai actually
    promotes (top-N from /models), not a list compiled into the source.
    Stub the fetcher and verify the endpoint surfaces THOSE IDs."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    # Pretend orcarouter.ai/models returns these IDs as its top picks.
    # All three are flagship IDs hardcoded in catalog.py (or in litellm's
    # core catalog), so they're guaranteed-present regardless of litellm
    # version and the endpoint can resolve provider/price for each.
    promoted = [
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "gpt-4o-mini",
    ]
    from app import orcarouter_models
    orcarouter_models.reset_cache()

    async def fake_fetch(url: str, timeout: float = 5.0) -> list[str]:
        return promoted

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", fake_fetch)

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        r = await c.get("/v1/analytics/unreachable?limit=5")
        body = r.json()
        ids = [m["id"] for m in body["unreachable"]]
        # Remote-promoted IDs must appear at the front in order (it's a
        # "top picks" list). The remaining slots up to `limit` are
        # backfilled from the static curated list.
        assert ids[: len(promoted)] == promoted, (
            f"expected promoted top list at front, got {ids}"
        )

    await engine.dispose()
    session_mod._session_factory = None
    orcarouter_models.reset_cache()


async def test_unreachable_with_no_keys_lists_flagship_models(isolated_env, fresh_client):
    """A bare-bones Lite install with no provider keys can't reach any
    flagship model — the endpoint should return a non-empty list to power
    the conversion CTA."""
    r = await fresh_client.get("/v1/analytics/unreachable")
    assert r.status_code == 200
    body = r.json()
    assert body["hosted_configured"] is False
    assert body["configured_providers"] == []
    assert len(body["unreachable"]) >= 1
    # Each entry must carry the fields the SPA renders (provider, prices,
    # capability flags) — otherwise the tile breaks.
    sample = body["unreachable"][0]
    for field in (
        "id", "provider",
        "input_cost_per_token", "output_cost_per_token",
        "supports_tools", "supports_vision", "supports_json_mode",
    ):
        assert field in sample


async def test_unreachable_excludes_models_for_configured_providers(fresh_client):
    """Once anthropic key is set, no anthropic models appear in unreachable."""
    await fresh_client.put(
        "/v1/providers/anthropic",
        json={"api_key": "sk-ant-test"},
    )
    r = await fresh_client.get("/v1/analytics/unreachable")
    body = r.json()
    assert "anthropic" in body["configured_providers"]
    providers_in_list = {m["provider"] for m in body["unreachable"]}
    assert "anthropic" not in providers_in_list


async def test_unreachable_clears_when_hosted_enabled(fresh_client):
    """Hosted reaches every catalog model, so the unreachable list must be
    empty — otherwise the dashboard would falsely tell active hosted users
    they're missing models they actually have access to."""
    await fresh_client.put(
        "/v1/providers/orcarouter",
        json={"api_key": "sk-orca-test"},
    )
    r = await fresh_client.get("/v1/analytics/unreachable")
    body = r.json()
    assert body["hosted_configured"] is True
    assert body["unreachable"] == []


async def test_unreachable_clears_when_hosted_via_env(tmp_sqlite_url, monkeypatch):
    """Env-configured hosted should clear the list just like dashboard does."""
    engine, client = await _client(
        tmp_sqlite_url, monkeypatch,
        {"ORCAROUTER_API_KEY": "sk-orca-env"},
    )
    async with client as c:
        r = await c.get("/v1/analytics/unreachable")
        body = r.json()
        assert body["hosted_configured"] is True
        assert body["unreachable"] == []
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None


async def test_unreachable_respects_limit(fresh_client):
    r = await fresh_client.get("/v1/analytics/unreachable?limit=3")
    body = r.json()
    assert len(body["unreachable"]) <= 3


async def test_unreachable_excludes_undecryptable_provider_keys(tmp_sqlite_url, monkeypatch, isolated_env):
    """Codex P2: an enabled DB row with a corrupt encrypted_key isn't
    actually deployable (build_deployments drops it). The unreachable
    endpoint must not silently treat that provider as 'covered' — those
    models really are unreachable until the key is fixed."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    # Inject a corrupt anthropic row — would falsely suppress claude-* from
    # the unreachable list if the endpoint trusts is_enabled blindly.
    from packages.db.models.provider_key import ProviderKey
    async with factory() as s:
        s.add(ProviderKey(
            provider="anthropic",
            encrypted_key=b"corrupt-not-valid-aesgcm",
            key_prefix="sk-ant-...",
            label="default",
            is_enabled=True,
        ))
        await s.commit()

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        r = await c.get("/v1/analytics/unreachable")
        body = r.json()
        assert "anthropic" not in body["configured_providers"], (
            "An undecryptable DB row must not be reported as a configured "
            "provider — build_deployments can't deploy it"
        )
        providers_in_list = {m["provider"] for m in body["unreachable"]}
        assert "anthropic" in providers_in_list

    await engine.dispose()
    session_mod._session_factory = None


async def test_unreachable_counts_env_provider_keys(tmp_sqlite_url, monkeypatch):
    """Env-set OPENAI_API_KEY counts as 'configured' — a Docker user with
    only env vars shouldn't see openai models in the unreachable tile."""
    engine, client = await _client(
        tmp_sqlite_url, monkeypatch,
        {"OPENAI_API_KEY": "sk-test-env"},
    )
    async with client as c:
        r = await c.get("/v1/analytics/unreachable")
        body = r.json()
        assert "openai" in body["configured_providers"]
        providers_in_list = {m["provider"] for m in body["unreachable"]}
        assert "openai" not in providers_in_list
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None
