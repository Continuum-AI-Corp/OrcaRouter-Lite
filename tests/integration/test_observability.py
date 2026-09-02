"""Check i log unhandled errors instead of dropping them."""

from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from packages.db import session as session_mod


async def test_unhandled_exception_is_logged(lite_app):
    def _boom(request):
        raise RuntimeError("pg password hunter2")

    lite_app.add_route("/boom", _boom)

    with capture_logs() as cap:
        # starlette sends the 500 then re-raises, so i stop httpx from raising
        transport = ASGITransport(app=lite_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/boom")

    assert r.status_code == 500
    # the caller must not see my internals
    assert "hunter2" not in r.text

    logged = [e for e in cap if e["event"] == "unhandled_exception"]
    assert logged, f"nothing logged: {[e.get('event') for e in cap]}"
    assert logged[0]["method"] == "GET"
    assert logged[0]["path"] == "/boom"
    assert logged[0]["log_level"] == "error"


async def test_auth_db_failure_is_logged(lite_app, monkeypatch):
    def _broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(session_mod, "_session_factory", _broken)

    with capture_logs() as cap:
        async with AsyncClient(transport=ASGITransport(app=lite_app), base_url="http://t") as c:
            r = await c.get("/v1/models", headers={"Authorization": "Bearer sk-orca-x"})

    assert r.status_code == 503

    logged = [e for e in cap if e["event"] == "auth_middleware_db_failure"]
    assert logged, f"nothing logged: {[e.get('event') for e in cap]}"
    assert logged[0]["path"] == "/v1/models"
    assert logged[0]["log_level"] == "error"
