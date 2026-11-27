"""Models running on this computer (P2 · D1): Ollama, LM Studio, llama.cpp.

The desktop engine probes each runtime's local API on its default port (or
where the runtime's usual environment variable points), with a one-second
timeout so a runtime that isn't running costs nothing. Results are cached
for 30 seconds; `discover(force=True)` re-probes (the app's refresh).

Each model found becomes a deployment with provider "local" and id
`<runtime>/<name>` (ollama/qwen3-coder:30b), costing nothing, and a catalog
entry carrying what the runtime reports it can do (tools, images, context
size), which decides the requests the "local_first" strategy sends it.

Nothing is sent anywhere but 127.0.0.1 (or the host the user's environment
names), and only in desktop mode (the router asks; servers never do).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from packages.litellm_adapter.catalog import CatalogModel
from packages.litellm_adapter.types import ProviderDeployment

PROVIDER = "local"
CACHE_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 1.0
# A local model that takes longer than this is treated as failed and the
# request moves on to the cloud; one that isn't listening fails at connect.
LOCAL_TIMEOUT_SECONDS = 60.0
LOCAL_CONNECT_TIMEOUT_SECONDS = 2.0
# The context the engine runs a local model with. Runtimes report the
# model's trained maximum (often 128K-256K), but serving that would take
# far more memory than a laptop has; Ollama is asked for this much instead.
MAX_LOCAL_CONTEXT = 32_768
# When a runtime doesn't say (LM Studio's OpenAI list, a bare llama.cpp).
DEFAULT_LOCAL_CONTEXT = 8_192
# A request goes to a local model only if its prompt fits in this share of
# the context, leaving room for the answer.
FIT_SHARE = 0.8


@dataclass(frozen=True)
class LocalModel:
    id: str            # "<runtime>/<name>", the model id requests and settings use
    runtime: str       # "ollama" | "lmstudio" | "llamacpp"
    name: str          # the runtime's own name for it
    api_base: str      # the runtime's base URL, without /v1
    context: int | None
    tools: bool
    vision: bool


@dataclass(frozen=True)
class Runtime:
    id: str
    name: str
    url: str           # host:port, for display
    running: bool
    models: tuple[LocalModel, ...] = ()


# id, display name, env var naming its address, default address
RUNTIMES: tuple[tuple[str, str, str, str], ...] = (
    ("ollama", "Ollama", "OLLAMA_HOST", "http://127.0.0.1:11434"),
    ("lmstudio", "LM Studio", "LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"),
    ("llamacpp", "llama.cpp", "LLAMACPP_BASE_URL", "http://127.0.0.1:8080"),
)

_cache: tuple[float, list[Runtime]] | None = None
_lock = asyncio.Lock()


def reset() -> None:
    global _cache, _refresh
    _cache = None
    _refresh = None


def remember(runtimes: list[Runtime]) -> None:
    """Record a discovery result (discover() does; tests may too)."""
    global _cache
    _cache = (time.monotonic() + CACHE_SECONDS, list(runtimes))


def expire() -> None:
    """Make the next lookup re-probe (a runtime just stopped answering), so
    the panel and the router see it as not running without waiting out the
    cache."""
    global _cache
    if _cache is not None:
        _cache = (0.0, _cache[1])


def last() -> list[Runtime]:
    """The most recent discovery result, without probing (empty before any)."""
    return list(_cache[1]) if _cache else []


def last_models() -> list[LocalModel]:
    return [m for r in last() for m in r.models]


def describe(model_id: str) -> LocalModel | None:
    return next((m for m in last_models() if m.id == model_id), None)


def disabled(env: Mapping[str, str] | None = None) -> bool:
    """ORCA_NO_LOCAL_MODELS=1 turns discovery off (tests; users who want it)."""
    return (env if env is not None else os.environ).get("ORCA_NO_LOCAL_MODELS", "") not in ("", "0")


async def discover(
    *,
    force: bool = False,
    client: httpx.AsyncClient | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Runtime]:
    """Every runtime, running or not, with the models it serves."""
    if not force and _cache and _cache[0] > time.monotonic():
        return list(_cache[1])
    async with _lock:
        if not force and _cache and _cache[0] > time.monotonic():
            return list(_cache[1])
        env = env if env is not None else os.environ
        own = client is None
        # Runtimes are on this computer: never through HTTP_PROXY.
        http = client or httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, trust_env=False)
        try:
            runtimes = await asyncio.gather(
                *(_probe(http, rid, name, _base_url(env.get(var), default)) for rid, name, var, default in RUNTIMES)
            )
        finally:
            if own:
                await http.aclose()
        remember(list(runtimes))
        return list(runtimes)


_refresh: asyncio.Task | None = None


async def current() -> list[Runtime]:
    """What the router routes to, without making a request wait on a probe.

    The first call discovers (once, at most a second per runtime). After that
    a stale result is returned at once and re-probed in the background, one
    refresh at a time, so a slow or hung runtime never delays a request.
    """
    global _refresh
    if _cache is None:
        return await discover()
    if _cache[0] <= time.monotonic() and (_refresh is None or _refresh.done()):
        _refresh = asyncio.get_running_loop().create_task(_background_discover())
    return list(_cache[1])


async def _background_discover() -> None:
    try:
        await discover()
    except Exception:  # a refresh must never surface as an unhandled task error
        pass


def _base_url(configured: str | None, default: str) -> str:
    """A runtime's address as its users write it: OLLAMA_HOST is often a bare
    host:port, and 0.0.0.0 (listen everywhere) is reached on 127.0.0.1;
    LM Studio's is often given with its /v1 suffix."""
    url = (configured or "").strip() or default
    if "://" not in url:
        url = f"http://{url}"
    url = url.rstrip("/").replace("://0.0.0.0", "://127.0.0.1")
    return url[: -len("/v1")] if url.endswith("/v1") else url


def _display(url: str) -> str:
    return url.split("://", 1)[-1]


async def _probe(http: httpx.AsyncClient, rid: str, name: str, base: str) -> Runtime:
    try:
        models = await _PROBES[rid](http, base)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return Runtime(rid, name, _display(base), running=False)
    return Runtime(rid, name, _display(base), running=True, models=tuple(models))


async def _get_json(http: httpx.AsyncClient, url: str, **kw) -> dict:
    method = "POST" if "json" in kw else "GET"
    r = await http.request(method, url, timeout=PROBE_TIMEOUT_SECONDS, **kw)
    r.raise_for_status()
    return r.json()


async def _ollama(http: httpx.AsyncClient, base: str) -> list[LocalModel]:
    tags = await _get_json(http, f"{base}/api/tags")
    names = [m["name"] for m in tags.get("models") or [] if isinstance(m, dict) and m.get("name")]
    shows = await asyncio.gather(*(_ollama_show(http, base, n) for n in names))
    out = []
    for n, shown in zip(names, shows, strict=True):
        known = describe(f"ollama/{n}")
        if shown is None and known is not None:
            # Ollama busy with a prompt can miss the probe timeout; keep what
            # it said last time rather than drop the model's tools flag (which
            # would take it out of routing and rebuild the router twice).
            out.append(known)
            continue
        caps, ctx = shown or (set(), None)
        out.append(LocalModel(id=f"ollama/{n}", runtime="ollama", name=n, api_base=base,
                              context=ctx, tools="tools" in caps, vision="vision" in caps))
    return out


async def _ollama_show(http: httpx.AsyncClient, base: str, name: str) -> tuple[set[str], int | None] | None:
    """What a model can do and its context size; None if Ollama didn't say."""
    try:
        info = await _get_json(http, f"{base}/api/show", json={"model": name})
    except (httpx.HTTPError, ValueError):
        return None
    caps = {c for c in info.get("capabilities") or [] if isinstance(c, str)}
    ctx = next(
        (v for k, v in (info.get("model_info") or {}).items()
         if k.endswith(".context_length") and isinstance(v, int)),
        None,
    )
    return caps, ctx


async def _lmstudio(http: httpx.AsyncClient, base: str) -> list[LocalModel]:
    """LM Studio's own REST API says what each model can do; older versions
    only have the OpenAI-compatible list (assume tools, unknown context)."""
    try:
        data = (await _get_json(http, f"{base}/api/v0/models")).get("data") or []
    except httpx.HTTPStatusError:
        data = None
    if data is None:
        listed = (await _get_json(http, f"{base}/v1/models")).get("data") or []
        return [LocalModel(id=f"lmstudio/{m['id']}", runtime="lmstudio", name=m["id"], api_base=base,
                           context=None, tools=True, vision=False) for m in listed]
    out = []
    for m in data:
        if m.get("type") not in ("llm", "vlm"):
            continue
        caps = m.get("capabilities") or []
        out.append(LocalModel(
            id=f"lmstudio/{m['id']}", runtime="lmstudio", name=m["id"], api_base=base,
            context=m.get("max_context_length") if isinstance(m.get("max_context_length"), int) else None,
            tools="tool_use" in caps, vision=m.get("type") == "vlm",
        ))
    return out


async def _llamacpp(http: httpx.AsyncClient, base: str) -> list[LocalModel]:
    listed = (await _get_json(http, f"{base}/v1/models")).get("data") or []
    out = []
    for m in listed:
        ctx = (m.get("meta") or {}).get("n_ctx_train")
        out.append(LocalModel(id=f"llamacpp/{m['id']}", runtime="llamacpp", name=m["id"], api_base=base,
                              context=ctx if isinstance(ctx, int) else None, tools=True, vision=False))
    return out


_PROBES = {"ollama": _ollama, "lmstudio": _lmstudio, "llamacpp": _llamacpp}


def enabled(models: list[LocalModel], selection: list[str] | None) -> list[LocalModel]:
    """The local models auto may use: the user's choice, or by default every
    model that can call tools (coding agents need them)."""
    if selection is None:
        return [m for m in models if m.tools]
    chosen = set(selection)
    return [m for m in models if m.id in chosen]


def run_context(m: LocalModel) -> int:
    """The context the engine runs the model with."""
    return min(m.context or DEFAULT_LOCAL_CONTEXT, MAX_LOCAL_CONTEXT)


def usable_context(m: LocalModel) -> int:
    """The largest prompt (in tokens) sent to the model."""
    return int(FIT_SHARE * run_context(m))


def deployments(models: list[LocalModel]) -> list[ProviderDeployment]:
    out = []
    for m in models:
        if m.runtime == "ollama":
            out.append(ProviderDeployment(
                model_name=m.id, litellm_model=f"ollama_chat/{m.name}", api_key="ollama", api_base=m.api_base,
                provider=PROVIDER, deployment_id=f"local::{m.id}", timeout=LOCAL_TIMEOUT_SECONDS,
                connect_timeout=LOCAL_CONNECT_TIMEOUT_SECONDS,
                extra_params={"num_ctx": run_context(m)},
            ))
        else:
            # OpenAI-compatible servers; the key is a placeholder they ignore.
            out.append(ProviderDeployment(
                model_name=m.id, litellm_model=f"openai/{m.name}", api_key=m.runtime, api_base=f"{m.api_base}/v1",
                provider=PROVIDER, deployment_id=f"local::{m.id}", timeout=LOCAL_TIMEOUT_SECONDS,
                connect_timeout=LOCAL_CONNECT_TIMEOUT_SECONDS,
            ))
    return out


def catalog_entry(m: LocalModel) -> CatalogModel:
    return CatalogModel(
        id=m.id, provider=PROVIDER, litellm_prefix="",
        supports_tools=m.tools, supports_vision=m.vision, supports_json_mode=True,
        input_cost_per_token=0.0, output_cost_per_token=0.0,
    )
