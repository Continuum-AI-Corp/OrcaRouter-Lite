"""Auth middleware integration tests.

We mount the middleware on a tiny FastAPI app and exercise it end-to-end via
the TestClient. This catches scope/state plumbing bugs that pure-unit tests
of `validate_api_key` would miss.
"""

import pytest


@pytest.fixture
async def app_with_auth(db_session, monkeypatch):
    """A FastAPI app with the lite auth middleware and one /v1/protected route."""
    monkeypatch.setenv("DATABASE_URL", str(db_session.bind.url))
    from fastapi import FastAPI, Request

    # Middleware now opens its own session via `session_mod._session_factory()`
    # instead of consuming a `get_session()` async generator (the previous
    # `async for s in get_session(): break` pattern was timing-fragile in
    # error paths). Substitute a factory that hands back the test's
    # already-open `db_session` and is a no-op on close — the fixture
    # owns the session lifecycle.
    from app.middleware.auth import AuthMiddleware
    from packages.db import session as session_mod

    class _PassthroughFactory:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False  # propagate any exception, don't close

    monkeypatch.setattr(session_mod, "_session_factory", lambda: _PassthroughFactory())

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/v1/protected")
    async def protected(request: Request):
        # The middleware writes to scope["state"] as a dict; FastAPI's
        # Request.state may be a Starlette State, so read from scope directly.
        state = request.scope.get("state") or {}
        kc = state.get("key_context") if isinstance(state, dict) else getattr(state, "key_context", None)
        return {"workspace_id": kc.workspace_id if kc else None}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


async def test_health_skips_auth(app_with_auth):
    """/health is on the public allowlist."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200


async def test_protected_without_bearer_returns_401(app_with_auth):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/v1/protected")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["type"] == "auth_error"


async def test_protected_with_invalid_key_returns_401(app_with_auth):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/v1/protected", headers={"Authorization": "Bearer sk-orca-bogus"})
    assert r.status_code == 401


async def test_protected_with_valid_key_returns_200(app_with_auth, db_session):
    """A seeded key authenticates and KeyContext is attached to scope.state."""
    from httpx import ASGITransport, AsyncClient

    from app.seed import seed_initial_state

    seed = await seed_initial_state(db_session)
    assert seed.api_key is not None

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/v1/protected", headers={"Authorization": f"Bearer {seed.api_key}"})
    assert r.status_code == 200
    assert r.json() == {"workspace_id": "default"}


# ── native-protocol credential locations + /v1beta guard (slice S1) ──


async def test_v1beta_is_guarded_not_waved_through_as_static(app_with_auth):
    """Regression: `_is_static` used to match only the "/v1/" prefix, so
    "/v1beta/..." bypassed auth entirely. It must 401 (in the Google
    envelope), not fall through to the app unauthenticated."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/v1beta/models")
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == 401
    assert err["status"] == "UNAUTHENTICATED"


async def test_x_api_key_header_authenticates(app_with_auth, db_session):
    """Anthropic SDK / Claude Code style credential location."""
    from httpx import ASGITransport, AsyncClient

    from app.seed import seed_initial_state

    seed = await seed_initial_state(db_session)

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/v1/protected", headers={"x-api-key": seed.api_key})
    assert r.status_code == 200


async def test_x_goog_api_key_header_authenticates(app_with_auth, db_session):
    """google-genai SDK style credential location."""
    from httpx import ASGITransport, AsyncClient

    from app.seed import seed_initial_state

    seed = await seed_initial_state(db_session)

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get("/v1/protected", headers={"x-goog-api-key": seed.api_key})
    assert r.status_code == 200


async def test_query_param_key_only_works_under_v1beta(app_with_auth, db_session):
    """?key= must NOT authenticate /v1/* paths (credential-in-URL is scoped
    to the Gemini surface); under /v1beta a valid ?key= passes the
    middleware (the test app then 404s — anything but 401 proves it)."""
    from httpx import ASGITransport, AsyncClient

    from app.seed import seed_initial_state

    seed = await seed_initial_state(db_session)

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        denied = await c.get(f"/v1/protected?key={seed.api_key}")
        allowed = await c.get(f"/v1beta/anything?key={seed.api_key}")
    assert denied.status_code == 401
    assert allowed.status_code == 404  # passed auth, no such route


async def test_foreign_bearer_token_falls_through_to_x_api_key(app_with_auth, db_session):
    """Regression: a reverse proxy / SSO gateway that injects its own
    non-empty Bearer token must not mask the caller's valid key in
    x-api-key — the rejected candidate falls through to the next one."""
    from httpx import ASGITransport, AsyncClient

    from app.seed import seed_initial_state

    seed = await seed_initial_state(db_session)

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get(
            "/v1/protected",
            headers={
                "Authorization": "Bearer gateway-injected-token",
                "x-api-key": seed.api_key,
            },
        )
    assert r.status_code == 200
    assert r.json() == {"workspace_id": "default"}


async def test_all_invalid_candidates_still_401(app_with_auth):
    """Falling through the chain must not become fail-open: when every
    candidate is rejected the request is still 401."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get(
            "/v1/protected",
            headers={
                "Authorization": "Bearer sk-orca-bogus-1",
                "x-api-key": "sk-orca-bogus-2",
                "x-goog-api-key": "sk-orca-bogus-3",
            },
        )
    assert r.status_code == 401


async def test_empty_bearer_falls_through_to_x_api_key(app_with_auth, db_session):
    """An empty `Authorization: Bearer ` (e.g. blanked by a proxy) must not
    short-circuit the documented fallback chain — a valid key in x-api-key
    still authenticates."""
    from httpx import ASGITransport, AsyncClient

    from app.seed import seed_initial_state

    seed = await seed_initial_state(db_session)

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.get(
            "/v1/protected",
            headers={"Authorization": "Bearer ", "x-api-key": seed.api_key},
        )
    assert r.status_code == 200


def test_extract_credentials_collects_every_location_in_order():
    """Scope-level check of the candidate chain (immune to any
    client/transport header normalization). Every location contributes a
    candidate — an empty or foreign Bearer must not hide the others — and
    duplicates collapse so the same key isn't validated twice."""
    from app.middleware.auth import _extract_credentials

    def scope(headers: dict[str, str], path="/v1/x", query=""):
        return {
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            "path": path,
            "query_string": query.encode(),
        }

    assert _extract_credentials(
        scope({"authorization": "Bearer ", "x-api-key": "sk-orca-a"})
    ) == ["sk-orca-a"]
    assert _extract_credentials(
        scope({"authorization": "Bearer ", "x-goog-api-key": "sk-orca-b"})
    ) == ["sk-orca-b"]
    assert _extract_credentials(
        scope({"authorization": "Bearer "}, path="/v1beta/models", query="key=sk-orca-c")
    ) == ["sk-orca-c"]
    assert _extract_credentials(scope({"authorization": "Bearer "})) == []

    # A proxy's own Bearer keeps precedence but no longer excludes the rest.
    assert _extract_credentials(
        scope({"authorization": "Bearer proxy-token", "x-api-key": "sk-orca-a"})
    ) == ["proxy-token", "sk-orca-a"]
    # Same key in two locations (Claude Code sends both) → one candidate.
    assert _extract_credentials(
        scope({"authorization": "Bearer sk-orca-a", "x-api-key": "sk-orca-a"})
    ) == ["sk-orca-a"]


async def test_v1_messages_401_uses_anthropic_envelope(app_with_auth):
    """Auth failures on the Anthropic surface render the Anthropic error
    envelope, not the OpenAI one."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_auth), base_url="http://t") as c:
        r = await c.post("/v1/messages", json={})
    assert r.status_code == 401
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "authentication_error"
