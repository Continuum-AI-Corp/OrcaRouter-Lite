"""Keep coding agents working when they ask for a model the user can't reach.

Claude Code asks for claude-* models, Gemini CLI for gemini-* and Codex can
be switched to named models. In the desktop app the user may have added a
key for a different vendor (or a newer dated name may not be in the catalog
yet). For an agent's own key that must not mean a failed request: the engine
routes it like `model="auto"`, preferring the same vendor's models when one
of them can be served. The response's `x-orca-requested-model` and
`x-orca-resolved-model` headers say what was asked for and what answered.

Keys outside the desktop app's agents (the dashboard, server API keys) keep
strict pinned-model behaviour: asking for a model means that model.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

AGENT_KEY_PREFIX = "agent:"

# Name prefixes that identify a vendor when the exact id isn't in the catalog.
_VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "anthropic"),
    ("gemini", "google"),
    ("gemma", "google"),
    ("gpt", "openai"),
    ("chatgpt", "openai"),
    ("codex", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("grok", "xai"),
    ("deepseek", "deepseek"),
    ("kimi", "moonshot"),
    ("moonshot", "moonshot"),
    ("glm", "zai"),
    ("chatglm", "zai"),
    ("qwen", "qwen"),
    ("mistral", "mistral"),
    ("codestral", "mistral"),
    ("devstral", "mistral"),
    ("command", "cohere"),
    ("minimax", "minimax"),
)


# Catalog providers that are one vendor for this purpose: the hosted catalog
# lists Kimi models as "kimi", a Moonshot key deploys them as "moonshot".
_FAMILY: dict[str, str] = {"kimi": "moonshot"}


def is_agent_key(key_name: str | None) -> bool:
    return bool(key_name) and key_name.startswith(AGENT_KEY_PREFIX)


def _vendor(model: str, by_id: dict[str, str]) -> str | None:
    if model in by_id:
        return by_id[model]
    bare = model.rsplit("/", 1)[-1].lower()
    for prefix, vendor in _VENDOR_PREFIXES:
        if bare.startswith(prefix):
            return vendor
    return None


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.replace(".", "-"), b.replace(".", "-"), strict=False):
        if x != y:
            break
        n += 1
    return n


# A release-date suffix (gpt-4.1-nano-2025-04-14, claude-haiku-4-5-20251001,
# qwen3.8-max-0902): the same model as the undated name.
_DATE_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|20\d{6}|\d{4})$")


def backup_models(
    model: str,
    deployable: Iterable[str],
    *,
    catalog: Iterable,
    limit: int = 3,
    background: Callable[[str], bool] | None = None,
) -> list[str]:
    """Backups for an agent's pinned model that is deployed but may fail
    upstream (no capacity, 503): the same vendor's other deployable models,
    closest name first (claude-sonnet-4.6 before claude-haiku-4.5 for
    claude-sonnet-4-5), newest first among equals. `background` tells a
    small background-tier model (mini, nano, haiku): those come after the
    full-size ones unless the agent asked for one. A dated release is left
    out when its undated name is a candidate too. Empty when the vendor is
    unknown or nothing else of it is deployable."""
    by_id = {m.id: _FAMILY.get(m.provider, m.provider) for m in catalog}
    vendor = _vendor(model, by_id)
    if vendor is None:
        return []
    same = {d for d in deployable if d != model and _vendor(d, by_id) == vendor}
    same = {d for d in same if not (_DATE_SUFFIX.search(d) and _DATE_SUFFIX.sub("", d) in same)}
    is_bg = background or (lambda _m: False)
    wants_bg = is_bg(model)
    ranked = sorted(same, key=lambda d: (is_bg(d) != wants_bg, -_common_prefix(model, d), [-ord(ch) for ch in d]))
    return ranked[:limit]


def fallback_preferences(
    model: str,
    deployable: set[str],
    *,
    catalog: Iterable,
    is_agent_key: bool,
    desktop_mode: bool,
) -> list[str] | None:
    """How to serve `model` for this caller.

    None: serve the request as asked (it's servable, it's `auto`, the caller
    isn't a desktop agent, or nothing at all is deployable so the normal
    "no provider" error applies). A list: route it as `auto`, preferring
    these deployable models (the same vendor's); empty means any model.
    """
    if not (desktop_mode and is_agent_key) or model == "auto" or model in deployable or not deployable:
        return None
    by_id = {m.id: _FAMILY.get(m.provider, m.provider) for m in catalog}
    vendor = _vendor(model, by_id)
    if vendor is None:
        return []
    return sorted(d for d in deployable if by_id.get(d) == vendor)
