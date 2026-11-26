"""The Test button and local-model discovery talk to this computer only:
they must never go through HTTP_PROXY (the Test request carries the agent's
Orca key in a header, and a corporate proxy would see it in the clear)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from packages.desktop import agent_test
from packages.desktop import local_models as lm


class _Handler(BaseHTTPRequestHandler):
    def _send(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._send({"models": []})

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send({"model": "gpt-4o-mini", "choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def dead_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)


async def test_the_agent_test_request_never_uses_the_proxy(local_server, dead_proxy):
    ep = agent_test.Endpoint(protocol="chat", base_url=f"{local_server}/v1", key="sk-orca-secret-0123456789",
                             model="auto", config_path=Path("/tmp/x"))
    result = await agent_test.send(ep, timeout=5)
    assert result.ok, result


async def test_local_discovery_never_uses_the_proxy(local_server, dead_proxy):
    lm.reset()
    runtimes = await lm.discover(force=True, env={"OLLAMA_HOST": local_server})
    assert next(r for r in runtimes if r.id == "ollama").running
    lm.reset()


def test_the_desktop_engine_keeps_loopback_requests_off_the_proxy(monkeypatch):
    # LiteLLM's own calls to Ollama / LM Studio read HTTP_PROXY too; the
    # desktop engine adds this computer's addresses to NO_PROXY.
    from app import config
    from app.main import create_app

    monkeypatch.setenv("ORCA_DESKTOP_MODE", "1")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "corp.example")
    monkeypatch.delenv("no_proxy", raising=False)
    config.get_settings.cache_clear()
    try:
        create_app()
        import os

        for var in ("NO_PROXY", "no_proxy"):
            hosts = os.environ[var].split(",")
            assert {"127.0.0.1", "localhost", "::1", "corp.example"} <= set(hosts)
    finally:
        config.get_settings.cache_clear()
