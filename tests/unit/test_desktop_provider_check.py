"""Setup checks a provider key with the provider before saving it.

A wrong key used to show up only as the first failed agent request. The
check asks the provider to list its models (no tokens are spent): 200 means
the key works, 401/403 means it doesn't. A network problem is reported but
doesn't block saving, so setup still works offline.
"""

from __future__ import annotations

import httpx
import pytest

from packages.desktop import provider_check as pc


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_working_key_is_valid():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        return httpx.Response(200, json={"data": []})

    async with _client(handler) as c:
        r = await pc.check_key("openai", "sk-good", client=c, env={})
    assert r == {"status": "valid", "detail": "OpenAI accepted the key."}
    assert seen == {"url": "https://api.openai.com/v1/models", "auth": "Bearer sk-good"}


@pytest.mark.parametrize("code", [401, 403])
async def test_a_rejected_key_is_invalid(code):
    async with _client(lambda req: httpx.Response(code, json={"error": "nope"})) as c:
        r = await pc.check_key("anthropic", "sk-ant-bad", client=c, env={})
    assert r["status"] == "invalid"
    assert "Anthropic" in r["detail"] and "sk-ant-bad" not in r["detail"]


async def test_a_network_problem_does_not_block_saving():
    def handler(req):
        raise httpx.ConnectError("offline", request=req)

    async with _client(handler) as c:
        r = await pc.check_key("openai", "sk-x", client=c, env={})
    assert r["status"] == "unreachable"


async def test_each_provider_is_asked_the_way_it_expects():
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers.get("x-api-key"), req.headers.get("x-goog-api-key"),
                     req.headers.get("authorization")))
        return httpx.Response(200, json={})

    async with _client(handler) as c:
        await pc.check_key("anthropic", "A", client=c, env={})
        await pc.check_key("google", "G", client=c, env={})
        await pc.check_key("deepseek", "D", client=c, env={})
    assert seen == [
        ("api.anthropic.com", "A", None, None),
        ("generativelanguage.googleapis.com", None, "G", None),
        ("api.deepseek.com", None, None, "Bearer D"),
    ]


async def test_the_openai_base_url_override_is_honoured():
    seen = []
    async with _client(lambda req: seen.append(str(req.url)) or httpx.Response(200, json={})) as c:
        await pc.check_key("openai", "k", client=c, env={"OPENAI_BASE_URL": "http://127.0.0.1:9/v1/"})
    assert seen == ["http://127.0.0.1:9/v1/models"]


async def test_providers_without_a_check_are_saved_unchecked():
    async with _client(lambda req: httpx.Response(500)) as c:
        r = await pc.check_key("perplexity", "k", client=c, env={})
    assert r["status"] == "unchecked"


def test_setup_offers_every_checked_provider():
    assert {"anthropic", "openai", "google", "deepseek", "xai", "mistral", "groq", "together", "fireworks"} <= set(pc.CHECKS)
