"""Cross-provider prompt cache.

LiteLLM only does prompt caching for Anthropic. This module ships an
exact-match cache that works for any provider — same `(model, messages,
temperature, tools, response_format, seed)` → cached response, no upstream
call.

Two backends, picked at startup:
  - Redis (when REDIS_URL is set) — survives restarts, works across pods.
  - InMemoryCache LRU — single-pod default; no infra deps.

Cache hits are surfaced via the `x-orca-cache: HIT` response header AND
the `cached: true` field on the returned dict. Misses get
`x-orca-cache: MISS`.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Protocol

_DEFAULT_TTL_SECONDS = 3600  # 1 hour


def cache_key(
    *,
    model: str,
    messages: list[dict],
    temperature: float | None,
    tools: list[dict] | None,
    response_format: dict | None,
    seed: int | None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    stop=None,
    n: int | None = None,
    tool_choice=None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
) -> str:
    """Deterministic SHA-256 key over EVERY output-affecting input.

    v2: the original key covered only six fields, so e.g. a max_tokens=16
    request collided with an identical max_tokens=4000 request and served
    the truncated answer as a HIT. The version field keeps old entries
    from ever matching the new key space.
    """
    payload = {
        "v": 2,
        "model": model,
        "messages": messages,
        "temperature": temperature if temperature is not None else 0.0,
        "tools": tools or None,
        "response_format": response_format or None,
        "seed": seed,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "stop": stop,
        "n": n,
        "tool_choice": tool_choice,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def is_cacheable(body: dict) -> bool:
    """A request is cacheable iff its output is deterministic.

    - Streaming responses are skipped (caching SSE chunks correctly is more
      trouble than it's worth for v1).
    - With an explicit seed, any sampling params are fine — the seed pins
      the output.
    - Otherwise the temperature must be EXPLICITLY zero AND top_p must not
      narrow the distribution. An OMITTED temperature means the provider
      default (1.0 — maximally non-deterministic), never cacheable.
    """
    if body.get("stream"):
        return False
    seed = body.get("seed")
    if seed is not None:
        return True
    temperature = body.get("temperature")
    if temperature is None or float(temperature) != 0.0:
        return False
    top_p = body.get("top_p")
    if top_p is not None and float(top_p) != 1.0:
        return False
    return True


# ── Backends ──────────────────────────────────────────────────────────


class CacheBackend(Protocol):
    async def get(self, key: str) -> dict | None: ...
    async def set(self, key: str, value: dict, ttl: int) -> None: ...


class InMemoryCache:
    """Simple LRU with TTL — fine for single-pod docker-compose."""

    def __init__(self, max_size: int = 1000, _now=None):
        self._max = max_size
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        # Indirection so tests can advance time without sleeping.
        self._now = _now or time.time

    async def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._now() >= expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: dict, ttl: int) -> None:
        self._store[key] = (self._now() + ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)


class RedisCache:
    """Redis-backed cache; activated when REDIS_URL is set."""

    def __init__(self, url: str):
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> dict | None:
        raw = await self._client.get(f"orca:cache:{key}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set(self, key: str, value: dict, ttl: int) -> None:
        await self._client.set(
            f"orca:cache:{key}",
            json.dumps(value, separators=(",", ":")),
            ex=ttl,
        )


# ── Module singleton ──────────────────────────────────────────────────

_backend: CacheBackend | None = None


def get_backend() -> CacheBackend:
    """Resolve the cache backend lazily on first call."""
    global _backend
    if _backend is not None:
        return _backend

    from app.config import get_settings

    settings = get_settings()
    if settings.redis_url:
        try:
            _backend = RedisCache(settings.redis_url)
            return _backend
        except Exception:
            pass
    _backend = InMemoryCache(max_size=1000)
    return _backend


def reset_backend() -> None:
    """Force re-resolution on next get_backend() — for tests."""
    global _backend
    _backend = None
