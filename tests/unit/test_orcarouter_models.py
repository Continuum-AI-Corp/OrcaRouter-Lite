"""Unit tests for `app.orcarouter_models` — the top-N model list fetcher
that drives the dashboard's "Models you can't reach" tile.

The fetcher must:
  - Pull from a configurable URL (default `https://www.orcarouter.ai/models`)
  - Tolerate JSON, OpenAI-format, and Next.js __NEXT_DATA__ responses
  - Fall back to a static curated list when the remote call fails or
    returns nothing parseable, so the dashboard never breaks
  - Cache responses in-process for an hour (TTL) so the unreachable
    endpoint doesn't issue an HTTP request per dashboard render
"""

from __future__ import annotations

import json

import httpx
import pytest


@pytest.fixture(autouse=True)
def _reset_models_cache():
    from app import orcarouter_models
    orcarouter_models.reset_cache()
    yield
    orcarouter_models.reset_cache()


def test_extract_ids_from_openai_data_envelope():
    from app.orcarouter_models import _extract_ids
    payload = {"data": [{"id": "gpt-4o"}, {"id": "claude-3-5-sonnet-latest"}]}
    assert _extract_ids(payload) == ["gpt-4o", "claude-3-5-sonnet-latest"]


def test_extract_ids_from_models_envelope():
    from app.orcarouter_models import _extract_ids
    assert _extract_ids({"models": [{"id": "x"}, {"id": "y"}]}) == ["x", "y"]


def test_extract_ids_from_bare_list_with_mixed_shapes():
    from app.orcarouter_models import _extract_ids
    payload = [{"id": "a"}, "raw-string-id", {"name": "alt-key"}, {"model_id": "alt2"}]
    assert _extract_ids(payload) == ["a", "raw-string-id", "alt-key", "alt2"]


def test_extract_ids_returns_empty_for_unrecognized_shapes():
    from app.orcarouter_models import _extract_ids
    assert _extract_ids({"unrelated": "shape"}) == []
    assert _extract_ids(None) == []
    assert _extract_ids(42) == []


def test_parse_response_pure_json():
    from app.orcarouter_models import _parse_response
    text = '{"data": [{"id": "m-1"}, {"id": "m-2"}]}'
    assert _parse_response("application/json", text) == ["m-1", "m-2"]


def test_parse_response_next_data_html():
    """Most marketing pages built with Next.js embed their data in a
    `<script id="__NEXT_DATA__">` tag — extract from there if the
    response isn't pure JSON."""
    from app.orcarouter_models import _parse_response
    next_payload = {
        "props": {
            "pageProps": {
                "models": [{"id": "from-nextjs-1"}, {"id": "from-nextjs-2"}]
            }
        }
    }
    text = (
        '<html><body>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_payload)}</script>'
        '</body></html>'
    )
    assert _parse_response("text/html", text) == ["from-nextjs-1", "from-nextjs-2"]


def test_parse_response_returns_empty_for_garbage():
    from app.orcarouter_models import _parse_response
    assert _parse_response("text/html", "<html>no embedded data</html>") == []
    assert _parse_response("application/json", "not json at all") == []


async def test_get_promoted_model_ids_uses_remote_when_fetch_succeeds(monkeypatch):
    from app import orcarouter_models

    async def fake_fetch(url: str, timeout: float = 5.0) -> list[str]:
        return ["remote-1", "remote-2", "remote-3"]

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", fake_fetch)
    ids = await orcarouter_models.get_promoted_model_ids(limit=10)
    assert ids == ["remote-1", "remote-2", "remote-3"]


async def test_get_promoted_model_ids_falls_back_to_static_on_network_failure(monkeypatch):
    """If orcarouter.ai is down, the dashboard tile must still render —
    the fallback list is the conversion message users see."""
    from app import orcarouter_models

    async def boom(url: str, timeout: float = 5.0) -> list[str]:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", boom)
    ids = await orcarouter_models.get_promoted_model_ids(limit=10)
    assert ids == list(orcarouter_models._STATIC_FALLBACK_IDS)


async def test_get_promoted_model_ids_falls_back_to_static_on_empty_remote(monkeypatch):
    """A 200 with no parseable model IDs is treated like a failure —
    a blank tile is worse than the curated default."""
    from app import orcarouter_models

    async def empty(url: str, timeout: float = 5.0) -> list[str]:
        return []

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", empty)
    ids = await orcarouter_models.get_promoted_model_ids(limit=10)
    assert ids == list(orcarouter_models._STATIC_FALLBACK_IDS)


async def test_get_promoted_model_ids_caches_within_ttl(monkeypatch):
    """Cache means the per-render HTTP latency hits only on cold start —
    the dashboard polls /v1/analytics/unreachable on every Overview view."""
    from app import orcarouter_models

    calls: list[str] = []

    async def fetcher(url: str, timeout: float = 5.0) -> list[str]:
        calls.append(url)
        return ["a", "b"]

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", fetcher)

    a = await orcarouter_models.get_promoted_model_ids()
    b = await orcarouter_models.get_promoted_model_ids()
    assert a == b == ["a", "b"]
    assert len(calls) == 1, f"expected 1 fetch within TTL, got {len(calls)}"


async def test_get_promoted_model_ids_respects_limit(monkeypatch):
    from app import orcarouter_models

    async def fetcher(url: str, timeout: float = 5.0) -> list[str]:
        return [f"m-{i}" for i in range(50)]

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", fetcher)
    ids = await orcarouter_models.get_promoted_model_ids(limit=5)
    assert ids == ["m-0", "m-1", "m-2", "m-3", "m-4"]


async def test_get_promoted_model_ids_uses_configured_url(monkeypatch):
    """Operator can swap orcarouter.ai/models for a different mirror via
    settings without code changes."""
    monkeypatch.setenv("ORCAROUTER_MODELS_URL", "https://example.test/models")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from app import orcarouter_models

    seen: list[str] = []

    async def fetcher(url: str, timeout: float = 5.0) -> list[str]:
        seen.append(url)
        return ["x"]

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", fetcher)
    await orcarouter_models.get_promoted_model_ids()
    assert seen == ["https://example.test/models"]
