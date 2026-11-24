"""Joining a team's gateway: check the URL and key before touching any agent."""

from __future__ import annotations

import httpx
import pytest

from packages.desktop import gateway as gw


@pytest.mark.parametrize(
    "url",
    [
        "https://ai-gw.example.com",
        "https://ai-gw.example.com/",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://10.1.2.3:8000",
        "http://192.168.1.20",
        "http://172.20.0.5:8000",
    ],
)
def test_accepts_https_or_private_http(url):
    assert gw.normalize_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url,why",
    [
        ("http://ai-gw.example.com", "https"),
        ("ftp://x", "https"),
        ("not a url", "https"),
        ("https://gw.example.com/v1", "without /v1"),
        ("https://user:pw@gw.example.com", "credentials"),
    ],
)
def test_rejects_unsafe_or_malformed_urls(url, why):
    with pytest.raises(gw.GatewayError) as e:
        gw.normalize_url(url)
    assert why in str(e.value)


def test_verify_sends_the_key_to_the_models_endpoint():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "auto"}]})

    gw.verify("https://gw.example.com", "sk-orca-team", transport=httpx.MockTransport(handler))
    assert str(seen[0].url) == "https://gw.example.com/v1/models"
    assert seen[0].headers["authorization"] == "Bearer sk-orca-team"


def test_verify_explains_a_rejected_key():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    with pytest.raises(gw.GatewayError) as e:
        gw.verify("https://gw.example.com", "sk-orca-bad", transport=httpx.MockTransport(handler))
    assert "key" in str(e.value).lower()


def test_verify_explains_an_unreachable_gateway():
    def handler(request):
        raise httpx.ConnectError("nope")

    with pytest.raises(gw.GatewayError) as e:
        gw.verify("https://gw.example.com", "sk-orca-x", transport=httpx.MockTransport(handler))
    assert "reach" in str(e.value).lower()


def test_verify_rejects_something_that_is_not_a_gateway():
    def handler(request):
        return httpx.Response(200, text="<html>hello</html>")

    with pytest.raises(gw.GatewayError):
        gw.verify("https://gw.example.com", "sk-orca-x", transport=httpx.MockTransport(handler))
