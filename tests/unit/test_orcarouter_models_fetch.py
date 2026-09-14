"""Verify _fetch_remote sends a User-Agent header.

Many CDNs and WAFs (Cloudflare, AWS CloudFront default rules) block
requests without a User-Agent. The unreachable-models tile silently
degrades to the static fallback for a full TTL when the remote is
blocked, making it look like the remote is down when it is actually
rejecting our requests.

The conftest autouse fixture replaces ``orcarouter_models._fetch_remote``
with a network-isolated stub. We hold a direct reference to the real
function (imported before the fixture runs) so our httpx mock is
actually exercised.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.orcarouter_models import _fetch_remote as _real_fetch_remote


class _FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}
    text = json.dumps({"data": [{"id": "gpt-4o"}]})

    def raise_for_status(self):
        pass


def _make_fake_client(captured: dict):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            captured.update(headers or {})
            return _FakeResponse()

    return FakeClient


@pytest.mark.asyncio
async def test_fetch_remote_sends_user_agent(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(captured))

    ids = await _real_fetch_remote("https://example.com/models")

    assert "User-Agent" in captured
    assert captured["User-Agent"].startswith("orcarouter-lite/")
    assert ids == ["gpt-4o"]


@pytest.mark.asyncio
async def test_fetch_remote_accept_header_present(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(captured))

    await _real_fetch_remote("https://example.com/models")

    assert captured.get("Accept") == "application/json"
