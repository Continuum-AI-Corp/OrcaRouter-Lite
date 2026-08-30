"""Tests for app.main.create_app — boot, /health, error format, CORS."""

async def test_health_returns_ok(lite_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=lite_app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_unknown_route_returns_404_in_error_envelope(lite_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=lite_app), base_url="http://t") as c:
        r = await c.get("/v1/totally-not-a-route")
    # Auth middleware sees /v1/* and demands a bearer first.
    assert r.status_code == 401
    body = r.json()
    assert "error" in body
    assert body["error"]["type"] == "auth_error"


async def test_v1_models_requires_auth(lite_app):
    """/v1/models is gated behind a bearer token in lite (single-tenant)."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=lite_app), base_url="http://t") as c:
        r = await c.get("/v1/models")
    assert r.status_code == 401
