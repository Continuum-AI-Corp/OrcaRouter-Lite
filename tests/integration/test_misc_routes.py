"""Tests for /v1/models, /v1/keys (rotate / allowlist), /v1/routing (strategy)."""

from __future__ import annotations

import pytest


@pytest.fixture
async def lite_client(tmp_sqlite_url, monkeypatch):
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

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c, seed.api_key

    await engine.dispose()
    session_mod._session_factory = None


# ── /v1/models ────────────────────────────────────────────────────────

async def test_models_returns_openai_format_listing(lite_client):
    client, _ = lite_client
    r = await client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0
    sample = body["data"][0]
    assert sample["object"] == "model"
    assert "id" in sample
    assert "owned_by" in sample


async def test_models_returns_anthropic_format_for_anthropic_clients(lite_client):
    """The native /v1/messages surface lives on the same base URL, so
    `client.models.list()` from the Anthropic SDK hits this path too. It
    always sends `anthropic-version` (no OpenAI client does), which is
    what selects the Anthropic envelope."""
    client, _ = lite_client
    r = await client.get("/v1/models", headers={"anthropic-version": "2023-06-01"})
    assert r.status_code == 200
    body = r.json()
    assert "object" not in body  # not the OpenAI envelope
    assert body["has_more"] is False
    assert body["first_id"] == body["data"][0]["id"]
    assert body["last_id"] == body["data"][-1]["id"]
    sample = body["data"][0]
    assert sample["type"] == "model"
    assert sample["id"] and sample["display_name"]
    # RFC 3339, per ModelInfo.created_at
    assert sample["created_at"].endswith("Z")


async def test_models_without_anthropic_header_stays_openai_shaped(lite_client):
    """Regression guard: adding the Anthropic envelope must not change the
    default shape every OpenAI client depends on."""
    client, _ = lite_client
    r = await client.get("/v1/models", headers={"user-agent": "openai-python/1.0"})
    assert r.json()["object"] == "list"


# ── /v1/keys ──────────────────────────────────────────────────────────

async def test_list_keys_shows_seeded_key(lite_client):
    client, _ = lite_client
    r = await client.get("/v1/keys")
    assert r.status_code == 200
    body = r.json()
    assert len(body["keys"]) == 1
    assert body["keys"][0]["name"] == "default"
    assert "key_hash" not in body["keys"][0]
    # Seeded key is unrestricted — null, not [].
    assert body["keys"][0]["model_allowlist"] is None


async def test_create_new_key_returns_plaintext_once(lite_client):
    client, _ = lite_client
    r = await client.post("/v1/keys", json={"name": "ci-runner"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key"].startswith("sk-orca-")
    assert body["name"] == "ci-runner"
    assert body["model_allowlist"] is None

    listing = await client.get("/v1/keys")
    names = {k["name"] for k in listing.json()["keys"]}
    assert names == {"default", "ci-runner"}


async def test_create_key_with_allowlist(lite_client):
    client, _ = lite_client
    r = await client.post(
        "/v1/keys",
        json={"name": "scoped", "model_allowlist": ["gpt-4o-mini"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["model_allowlist"] == ["gpt-4o-mini"]

    listing = await client.get("/v1/keys")
    scoped = next(k for k in listing.json()["keys"] if k["name"] == "scoped")
    assert scoped["model_allowlist"] == ["gpt-4o-mini"]


async def test_create_key_empty_allowlist_is_deny_all(lite_client):
    """[] is stored as [] (deny everything), not coerced to null."""
    client, _ = lite_client
    r = await client.post("/v1/keys", json={"name": "locked", "model_allowlist": []})
    assert r.status_code == 201, r.text
    assert r.json()["model_allowlist"] == []

    listing = await client.get("/v1/keys")
    locked = next(k for k in listing.json()["keys"] if k["name"] == "locked")
    assert locked["model_allowlist"] == []


async def test_create_key_rejects_unknown_model_ids(lite_client):
    client, _ = lite_client
    r = await client.post(
        "/v1/keys",
        json={
            "name": "typo",
            "model_allowlist": ["gpt-4o-mni", "also-fake", "gpt-4o-mini"],
        },
    )
    assert r.status_code == 422, r.text
    assert "gpt-4o-mni" in r.text
    assert "also-fake" in r.text
    listing = await client.get("/v1/keys")
    names = {k["name"] for k in listing.json()["keys"]}
    assert "typo" not in names


async def test_put_key_updates_allowlist(lite_client):
    client, _ = lite_client
    created = (await client.post("/v1/keys", json={"name": "mutable"})).json()
    r = await client.put(
        f"/v1/keys/{created['id']}",
        json={"model_allowlist": ["gpt-4o-mini"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["model_allowlist"] == ["gpt-4o-mini"]

    listing = await client.get("/v1/keys")
    row = next(k for k in listing.json()["keys"] if k["id"] == created["id"])
    assert row["model_allowlist"] == ["gpt-4o-mini"]


async def test_put_key_empty_allowlist_is_deny_all(lite_client):
    client, _ = lite_client
    created = (
        await client.post(
            "/v1/keys",
            json={"name": "lockable", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()
    r = await client.put(f"/v1/keys/{created['id']}", json={"model_allowlist": []})
    assert r.status_code == 200, r.text
    assert r.json()["model_allowlist"] == []


async def test_put_key_null_allowlist_clears_restriction(lite_client):
    client, _ = lite_client
    created = (
        await client.post(
            "/v1/keys",
            json={"name": "clearable", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()
    r = await client.put(
        f"/v1/keys/{created['id']}",
        json={"model_allowlist": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["model_allowlist"] is None


async def test_restricted_key_can_update_own_allowlist(lite_client):
    """A restricted key may PUT /v1/keys/{own_id} with a non-null list,
    including [] (deny-everything). Existing schema: [] is not coerced
    to null."""
    from httpx import AsyncClient

    client, _ = lite_client
    created = (
        await client.post(
            "/v1/keys",
            json={"name": "self-update", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()
    restricted_id = created["id"]
    headers = {"Authorization": f"Bearer {created['api_key']}"}

    async with AsyncClient(
        transport=client._transport, base_url="http://t", headers=headers
    ) as restricted:
        narrowed = await restricted.put(
            f"/v1/keys/{restricted_id}",
            json={"model_allowlist": ["gpt-4o"]},
        )
        assert narrowed.status_code == 200, narrowed.text
        assert narrowed.json()["model_allowlist"] == ["gpt-4o"]

        empty = await restricted.put(
            f"/v1/keys/{restricted_id}",
            json={"model_allowlist": []},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["model_allowlist"] == []

    listing = await client.get("/v1/keys")
    row = next(k for k in listing.json()["keys"] if k["id"] == restricted_id)
    assert row["model_allowlist"] == []


async def test_restricted_key_cannot_clear_own_allowlist_to_unrestricted(lite_client):
    """JSON null stores None = unrestricted. A restricted key must not
    lift the operator-imposed allowlist on itself."""
    from httpx import AsyncClient

    client, _ = lite_client
    created = (
        await client.post(
            "/v1/keys",
            json={"name": "self-clear", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()
    restricted_id = created["id"]

    async with AsyncClient(
        transport=client._transport,
        base_url="http://t",
        headers={"Authorization": f"Bearer {created['api_key']}"},
    ) as restricted:
        cleared = await restricted.put(
            f"/v1/keys/{restricted_id}",
            json={"model_allowlist": None},
        )
    assert cleared.status_code == 403, cleared.text

    listing = await client.get("/v1/keys")
    row = next(k for k in listing.json()["keys"] if k["id"] == restricted_id)
    assert row["model_allowlist"] == ["gpt-4o-mini"]


async def test_restricted_key_cannot_update_other_key_allowlist(lite_client):
    """A restricted key may not rewrite a sibling key's allowlist."""
    from httpx import AsyncClient

    client, _ = lite_client
    restricted = (
        await client.post(
            "/v1/keys",
            json={"name": "scoped-caller", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()
    other = (
        await client.post(
            "/v1/keys",
            json={"name": "sibling", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()

    async with AsyncClient(
        transport=client._transport,
        base_url="http://t",
        headers={"Authorization": f"Bearer {restricted['api_key']}"},
    ) as caller:
        r = await caller.put(
            f"/v1/keys/{other['id']}",
            json={"model_allowlist": None},
        )
    assert r.status_code == 403, r.text

    listing = await client.get("/v1/keys")
    row = next(k for k in listing.json()["keys"] if k["id"] == other["id"])
    assert row["model_allowlist"] == ["gpt-4o-mini"]


async def test_put_key_rejects_unknown_model_ids(lite_client):
    client, _ = lite_client
    created = (
        await client.post(
            "/v1/keys",
            json={"name": "stable", "model_allowlist": ["gpt-4o-mini"]},
        )
    ).json()
    r = await client.put(
        f"/v1/keys/{created['id']}",
        json={"model_allowlist": ["not-a-real-model"]},
    )
    assert r.status_code == 422, r.text
    assert "not-a-real-model" in r.text
    listing = await client.get("/v1/keys")
    row = next(k for k in listing.json()["keys"] if k["id"] == created["id"])
    assert row["model_allowlist"] == ["gpt-4o-mini"]


async def test_put_key_missing_returns_404(lite_client):
    client, _ = lite_client
    r = await client.put(
        "/v1/keys/does-not-exist",
        json={"model_allowlist": ["gpt-4o-mini"]},
    )
    assert r.status_code == 404


async def test_revoke_key_blocks_reauth(lite_client):
    client, _ = lite_client
    created = (await client.post("/v1/keys", json={"name": "to-revoke"})).json()
    new_key = created["api_key"]
    new_id = created["id"]

    r = await client.delete(f"/v1/keys/{new_id}")
    assert r.status_code == 204

    from httpx import AsyncClient
    transport = client._transport
    async with AsyncClient(transport=transport, base_url="http://t",
                           headers={"Authorization": f"Bearer {new_key}"}) as fresh:
        r2 = await fresh.get("/v1/keys")
    assert r2.status_code == 401


# ── /v1/routing ───────────────────────────────────────────────────────

async def test_get_routing_returns_default_strategy(lite_client):
    client, _ = lite_client
    r = await client.get("/v1/routing")
    assert r.status_code == 200
    body = r.json()
    assert body["strategy"] == "balanced"


async def test_put_routing_updates_strategy(lite_client):
    client, _ = lite_client
    r = await client.put("/v1/routing", json={"strategy": "cheapest"})
    assert r.status_code == 200
    assert r.json()["strategy"] == "cheapest"

    fetched = await client.get("/v1/routing")
    assert fetched.json()["strategy"] == "cheapest"


async def test_put_routing_rejects_unknown_strategy(lite_client):
    client, _ = lite_client
    r = await client.put("/v1/routing", json={"strategy": "magic-sauce"})
    assert r.status_code == 422


async def test_put_routing_invalidates_cached_router(lite_client, monkeypatch):
    """Changing the strategy must drop the cached client so the next request
    rebuilds it with the new `routing_strategy`."""
    client, _ = lite_client
    from app import router_cache

    sentinel = object()
    router_cache._cached_client = sentinel
    assert router_cache._cached_client is sentinel

    r = await client.put("/v1/routing", json={"strategy": "cheapest"})
    assert r.status_code == 200
    assert router_cache._cached_client is None
