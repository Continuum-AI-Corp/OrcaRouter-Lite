"""Top-N model list fetcher for the dashboard's "Models you can't reach" tile.

Source URL is configurable via `orcarouter_models_url` (default
`https://www.orcarouter.ai/models`). Response is parsed defensively —
the URL may serve raw JSON, an OpenAI-format catalog, or a Next.js HTML
page with the data embedded in `__NEXT_DATA__`. Result is cached
in-process for an hour so the unreachable endpoint doesn't hit the
network on every dashboard render.

If the fetch fails (network, 4xx/5xx, parse error, empty result), the
fetcher returns a static curated list so the conversion tile keeps
rendering — orcarouter.ai going down must not break the Lite dashboard.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

# Static fallback used when the remote fetch fails or returns nothing
# parseable. Same flagship models we hardcoded before the dynamic fetch
# existed — kept as a curated default so the tile is never empty.
_STATIC_FALLBACK_IDS: tuple[str, ...] = (
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
    "claude-3-opus-latest",
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o1-mini",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "deepseek-chat",
)

_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
_FETCH_TIMEOUT_SECONDS = 5.0

# Marketing pages built with Next.js embed their server-rendered data
# in this script tag. Cheap to look for, expensive to miss.
_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
    re.DOTALL,
)

# Process-wide cache. Keyed by URL so swapping the setting at runtime
# (e.g. tests with monkeypatched config) doesn't return stale data from
# a different source. No lock: a duplicate fetch on a cold-start race
# is harmless (same idempotent GET, last write wins) and a module-level
# `asyncio.Lock()` is fragile across pytest-asyncio's function-scoped
# event loops.
_cache: dict[str, tuple[float, list[str]]] = {}


def _extract_ids(payload: Any) -> list[str]:
    """Pull a list of model IDs from common response shapes.

    Handles:
      - {"data":    [{"id": "..."}, ...]}    # OpenAI-compat catalog
      - {"models":  [{"id": "..."}, ...]}    # generic
      - {"results": [{"id": "..."}, ...]}    # generic
      - {"items":   [{"id": "..."}, ...]}    # generic
      - [{"id": "..."}, ...]                 # bare list of dicts
      - [{"name": "..."}, ...]               # alt key
      - [{"model_id": "..."}, ...]           # alt key
      - ["id-1", "id-2", ...]                # bare ID list
    """
    if isinstance(payload, dict):
        for key in ("data", "models", "results", "items"):
            if key in payload:
                return _extract_ids(payload[key])
        return []
    if isinstance(payload, list):
        out: list[str] = []
        for entry in payload:
            if isinstance(entry, str) and entry:
                out.append(entry)
            elif isinstance(entry, dict):
                for k in ("id", "model_id", "name", "model"):
                    v = entry.get(k)
                    if isinstance(v, str) and v:
                        out.append(v)
                        break
        return out
    return []


def _parse_response(content_type: str, text: str) -> list[str]:
    """Try JSON first; fall back to scraping `__NEXT_DATA__` from HTML."""
    text = (text or "").strip()
    if not text:
        return []

    # Direct JSON (regardless of declared content-type — some CDNs lie).
    try:
        return _extract_ids(json.loads(text))
    except Exception:
        pass

    # Embedded Next.js payload.
    m = _NEXT_DATA_RE.search(text)
    if m:
        try:
            payload = json.loads(m.group(1))
            # Walk the most likely paths first; if none yield IDs,
            # fall through to the generic walk over the whole tree.
            for path in (
                ("props", "pageProps", "models"),
                ("props", "pageProps", "data"),
                ("props", "pageProps"),
            ):
                cur: Any = payload
                ok = True
                for k in path:
                    if isinstance(cur, dict) and k in cur:
                        cur = cur[k]
                    else:
                        ok = False
                        break
                if ok:
                    ids = _extract_ids(cur)
                    if ids:
                        return ids
            return _extract_ids(payload)
        except Exception:
            pass

    return []


async def _fetch_remote(url: str, timeout: float = _FETCH_TIMEOUT_SECONDS) -> list[str]:
    """Single request. Tests monkeypatch this to avoid network.

    Follows redirects — `httpx.AsyncClient` defaults to
    `follow_redirects=False`, and `raise_for_status()` raises on 3xx, so
    a healthy source behind a canonical-host or trailing-slash redirect
    would silently flip the unreachable tile to the static fallback for
    a full TTL.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        return _parse_response(r.headers.get("Content-Type", ""), r.text)


async def get_promoted_model_ids(*, limit: int = 10, force_refresh: bool = False) -> list[str]:
    """Return up to `limit` model IDs to feature in the unreachable tile.

    Caches the remote fetch for `_CACHE_TTL_SECONDS`. On any failure or
    empty parse, returns the static fallback list.
    """
    from app.config import get_settings

    url = get_settings().orcarouter_models_url
    now = time.monotonic()

    if not force_refresh:
        cached = _cache.get(url)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1][:limit]

    try:
        ids = await _fetch_remote(url)
        if not ids:
            raise ValueError("empty model list from remote")
    except Exception:
        ids = list(_STATIC_FALLBACK_IDS)
    _cache[url] = (time.monotonic(), ids)
    return ids[:limit]


def reset_cache() -> None:
    """Test hook — wipe the in-process cache."""
    _cache.clear()
