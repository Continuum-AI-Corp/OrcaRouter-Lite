"""Cross-provider prompt cache.

LiteLLM only does prompt caching for Anthropic. Lite ships an exact-match
cache that works for any provider — same (model, messages, temperature,
tools, response_format, seed) → cached response, no upstream call.

Backed by Redis when REDIS_URL is set, falls back to an in-process LRU
otherwise so it works in single-pod docker-compose / on a laptop.
"""

from __future__ import annotations

import pytest


def test_cache_key_is_deterministic_across_runs():
    from app.prompt_cache import cache_key

    a = cache_key(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        tools=None,
        response_format=None,
        seed=None,
    )
    b = cache_key(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        tools=None,
        response_format=None,
        seed=None,
    )
    assert a == b
    assert isinstance(a, str)
    assert len(a) >= 32  # sha256 hex


def test_cache_key_differs_on_message_content():
    from app.prompt_cache import cache_key

    a = cache_key(model="m", messages=[{"role": "user", "content": "hi"}],
                  temperature=0.0, tools=None, response_format=None, seed=None)
    b = cache_key(model="m", messages=[{"role": "user", "content": "bye"}],
                  temperature=0.0, tools=None, response_format=None, seed=None)
    assert a != b


def test_cache_key_differs_on_temperature():
    from app.prompt_cache import cache_key

    msgs = [{"role": "user", "content": "hi"}]
    a = cache_key(model="m", messages=msgs, temperature=0.0,
                  tools=None, response_format=None, seed=None)
    b = cache_key(model="m", messages=msgs, temperature=0.7,
                  tools=None, response_format=None, seed=None)
    assert a != b


def test_cache_key_differs_on_model():
    from app.prompt_cache import cache_key

    msgs = [{"role": "user", "content": "hi"}]
    a = cache_key(model="gpt-4o", messages=msgs, temperature=0.0,
                  tools=None, response_format=None, seed=None)
    b = cache_key(model="claude-3-5-sonnet-latest", messages=msgs,
                  temperature=0.0, tools=None, response_format=None, seed=None)
    assert a != b


def test_should_cache_skips_streaming_and_high_temperature():
    """We only cache deterministic, non-streaming requests."""
    from app.prompt_cache import is_cacheable

    base = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}

    # Cacheable: explicitly-zero temperature and not streaming
    assert is_cacheable({**base, "temperature": 0.0, "stream": False}) is True

    # Not cacheable — an OMITTED temperature means the provider default
    # (1.0), i.e. maximally non-deterministic. Never cache that.
    assert is_cacheable({**base, "stream": False}) is False

    assert is_cacheable({**base, "stream": True}) is False
    assert is_cacheable({**base, "temperature": 0.7}) is False
    assert is_cacheable({**base, "temperature": 0.1}) is False


def test_should_cache_blocks_narrowed_top_p_without_seed():
    """top_p < 1 samples from a truncated distribution even at temperature 0."""
    from app.prompt_cache import is_cacheable

    base = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
    assert is_cacheable({**base, "temperature": 0.0, "top_p": 0.5}) is False
    assert is_cacheable({**base, "temperature": 0.0, "top_p": 1.0}) is True
    # A seed overrides any sampling param.
    assert is_cacheable({**base, "temperature": 0.7, "top_p": 0.3, "seed": 7}) is True


# ── v2 key-space: every output-affecting parameter must change the key ──

_MSGS = [{"role": "user", "content": "hi"}]


def _key(**overrides):
    from app.prompt_cache import cache_key

    kwargs = dict(model="m", messages=_MSGS, temperature=0.0, tools=None,
                  response_format=None, seed=None)
    kwargs.update(overrides)
    return cache_key(**kwargs)


@pytest.mark.parametrize("field,value", [
    ("max_tokens", 16),
    ("max_tokens", 4000),
    ("top_p", 0.9),
    ("stop", ["\n"]),
    ("n", 2),
    ("tool_choice", "none"),
    ("presence_penalty", 1.0),
    ("frequency_penalty", -0.5),
])
def test_cache_key_differs_on_every_output_affecting_param(field, value):
    base = _key()
    assert _key(**{field: value}) != base


def test_cache_key_version_bump_invalidates_v1_entries():
    """A v1-era entry (no 'v' field) can never collide with the v2 space."""
    k = _key(max_tokens=100)
    # Recompute what the old implementation would have produced for the
    # same six fields and confirm it differs from the new key.
    import hashlib
    import json

    legacy_payload = {
        "model": "m",
        "messages": _MSGS,
        "temperature": 0.0,
        "tools": None,
        "response_format": None,
        "seed": None,
    }
    legacy = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert k != legacy


def test_should_cache_skips_when_seed_unspecified_with_high_temp():
    """A seed pins determinism; without it, anything > 0 is non-deterministic."""
    from app.prompt_cache import is_cacheable

    base = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
    # With explicit seed AND any temp → still cacheable (seed pins output)
    assert is_cacheable({**base, "temperature": 0.7, "seed": 42}) is True


@pytest.mark.asyncio
async def test_inmem_cache_round_trip():
    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=10)
    await c.set("key1", {"hello": "world"}, ttl=60)
    got = await c.get("key1")
    assert got == {"hello": "world"}


@pytest.mark.asyncio
async def test_inmem_cache_miss_returns_none():
    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=10)
    assert await c.get("never-set") is None


@pytest.mark.asyncio
async def test_inmem_cache_evicts_when_full():
    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=2)
    await c.set("a", {"v": 1}, ttl=60)
    await c.set("b", {"v": 2}, ttl=60)
    await c.set("c", {"v": 3}, ttl=60)  # evicts oldest "a"
    assert await c.get("a") is None
    assert await c.get("b") is not None
    assert await c.get("c") is not None


@pytest.mark.asyncio
async def test_inmem_cache_respects_ttl():
    import time

    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=10, _now=lambda: time.time())
    await c.set("k", {"v": 1}, ttl=0)  # immediate expiry
    # Fast-forward by mocking _now
    c._now = lambda: time.time() + 1
    assert await c.get("k") is None
