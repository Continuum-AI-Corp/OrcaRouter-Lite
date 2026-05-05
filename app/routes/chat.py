"""POST /v1/chat/completions — the proxy endpoint, slimmed for lite.

Supports both blocking and streaming. The streaming path returns an SSE
response in OpenAI's `text/event-stream` format with a terminal
`data: [DONE]` sentinel, exactly matching what the OpenAI SDK expects.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterable

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import prompt_cache, router_cache
from app.auto_routing import choose_auto_model, required_capabilities
from app.config import get_settings
from app.deps import get_db, get_key_context
from app.quality_scores import resolve_quality_scores
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext
from packages.db.models.request_log import RequestLog
from packages.litellm_adapter.catalog import CATALOG
from packages.litellm_adapter.types import UpstreamProviderError

logger = structlog.get_logger()
router = APIRouter(prefix="/v1", tags=["Chat Completions"])


def _chunk_to_dict(chunk) -> dict:
    """Normalize a litellm chunk (Pydantic model or dict) into a plain dict."""
    if isinstance(chunk, dict):
        return chunk
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump(exclude_none=True)
    return dict(chunk)


# Suffix shapes that mark a response model as a more-specific *version* of the
# requested model rather than a different one. Matched against the substring
# AFTER `requested_group + "-"` in the served name.
#   "2024-08-06"   — OpenAI dated version
#   "20241022"     — Anthropic dated version (compact form)
#   "001" / "002"  — Google Vertex / Gemini revision suffix
#   "v1.5"         — explicit semver-like version
#
# Deliberately excluded:
#   "preview"      — too ambiguous. "gpt-4-turbo-preview" is a distinct
#                    catalog model from "gpt-4-turbo", not a version variant.
#   "latest"       — providers don't return "-latest" in response.model;
#                    it's only a request-side alias.
#   "mini" / etc.  — branding suffixes, not versions.
_VERSION_SUFFIX_RE = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}"     # YYYY-MM-DD
    r"|\d{6,}"                # YYYYMMDD or compact dates / build numbers
    r"|\d{1,4}"               # 001, 002, 1, 12, ...
    r"|v\d[\d.]*"             # v1, v1.5, v2.0.1
    r")$"
)


def _served_same_group_as_requested(
    *, requested_group: str, served_model: str | None, client
) -> bool:
    """Return True iff the response's served model is in the same model_group
    (model_name in our deployment taxonomy) as the requested primary.

    LiteLLM frequently rewrites or expands model names in the response:
      - prefixed form: requested "gpt-4o-mini", response.model = "openai/gpt-4o-mini"
      - dated alias:   requested "gpt-4o", response.model = "gpt-4o-2024-08-06"
      - bare provider model: requested "claude-3-5-sonnet-latest",
                             response.model = "claude-3-5-sonnet-20241022"

    Strict string equality would treat these as different models and disable
    the prompt cache for almost all real traffic. Canonicalize via four
    progressively-stricter passes:

    1. Exact / prefix-stripped equality — handles "openai/gpt-4o-mini" vs "gpt-4o-mini".
    2. Version-suffix variant — served = requested + "-" + (date | build | vN).
       Catches OpenAI's "gpt-4o-2024-08-06" for "gpt-4o" without falsely
       matching "gpt-4o-mini" for "gpt-4o" (mini is not a date pattern).
    3. Deployment lookup — authoritative for the configured Router. If the
       served name maps to a different deployment's model_name, real cascade.
    4. Catalog lookup — if the bare name is a known distinct catalog entry,
       treat as cascade. Otherwise (unknown rendering), permit caching.
    """
    if not served_model:
        return True
    if served_model == requested_group:
        return True
    bare = served_model.split("/", 1)[-1] if "/" in served_model else served_model
    if bare == requested_group:
        return True

    # Pass 2: version-suffix variant (must run BEFORE deployment/catalog
    # lookups, because dated variants like "gpt-4o-2024-08-06" are also
    # in CATALOG_BY_ID as their own entries — those passes would falsely
    # flag them as a different group).
    if bare.startswith(requested_group + "-"):
        suffix = bare[len(requested_group) + 1:]
        if _VERSION_SUFFIX_RE.match(suffix):
            return True

    # Pass 3: deployment lookup. Authoritative — these are the model_groups
    # we actually configured for this Router.
    deployments = getattr(client, "_deployments", []) or []
    for d in deployments:
        if served_model in (d.litellm_model, d.model_name) or bare == d.model_name:
            return d.model_name == requested_group

    # Pass 4: catalog lookup. If the bare name is itself a recognized
    # catalog model distinct from the requested group, treat as cascade.
    # Imported lazily so the catalog isn't a hard dependency for this fn.
    from packages.litellm_adapter.catalog import CATALOG_BY_ID
    if bare in CATALOG_BY_ID and bare != requested_group:
        return False

    # Bare name doesn't resemble any known model — likely a provider-side
    # normalization we don't recognize. Permit caching to avoid disabling
    # the cache wholesale for unfamiliar response shapes.
    return True


async def _build_log_row(
    *,
    body: ChatCompletionRequest,
    kc: KeyContext,
    response: dict,
    status_code: int,
    error_type: str | None,
    started_perf: float,
    strategy: str,
    requested_model: str,
    actual_resolved: str | None = None,
) -> RequestLog:
    """Persist what the client asked for vs. what actually served the request.

    `requested_model` is the value the client sent (e.g. "auto" or a pinned
    model name) — captured before any auto-resolution so the log preserves
    user intent. `actual_resolved` is the model that ultimately served the
    response, which may differ from the auto-resolved primary if LiteLLM
    Router cascaded to a fallback after a 404 / cooldown.
    """
    latency_ms = int((time.perf_counter() - started_perf) * 1000)
    meta = response.get("_orca_meta", {})
    usage = response.get("usage", {}) or {}
    resolved = actual_resolved or response.get("model") or requested_model
    return RequestLog(
        workspace_id=str(kc.workspace_id),
        api_key_id=str(kc.key_id),
        trace_id=str(uuid.uuid4()),
        model_requested=requested_model,
        model_resolved=resolved,
        provider=meta.get("provider", "unknown"),
        routing_strategy=strategy,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        cost_microcents=0,
        latency_ms=meta.get("latency_ms", latency_ms),
        status_code=status_code,
        error_type=error_type,
        is_streaming=body.stream,
    )


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
):
    # Capture client intent before any mutation so the request log and the
    # `x-orca-requested-model` header always reflect what the user asked for,
    # not the post-resolution primary.
    requested_model = body.model
    was_auto = body.model == "auto"

    # Allowlist enforcement is split: pinned requests check up front, auto
    # requests defer to after resolution (since "auto" itself is never in
    # an allowlist literal). Without this exemption, every key with an
    # allowlist would be locked out of `model="auto"`.
    #
    # `is not None` (not truthiness): an explicit empty list means "deny
    # everything" — the operator's intent is to lock the key down. Falsy
    # check would let an empty allowlist mean "no restriction", which
    # silently inverts the operator's security posture.
    if not was_auto and kc.model_allowlist is not None and body.model not in kc.model_allowlist:
        raise HTTPException(
            status_code=403,
            detail=f"Model '{body.model}' is not allowed for this API key",
        )

    client = await router_cache.get_router(db)
    raw_strategy = getattr(client, "strategy", None)
    strategy = raw_strategy if isinstance(raw_strategy, str) and raw_strategy else "balanced"
    raw_preferred = getattr(client, "preferred_models", None)
    preferred_models = raw_preferred if isinstance(raw_preferred, list) else []

    # Resolve `model="auto"` BEFORE building the request kwargs so the router
    # sees a real model. `candidates` is the top-N list from auto-routing;
    # candidates[0] becomes the primary and candidates[1:] are passed to
    # LiteLLM Router as fallbacks for automatic cascade on 404 / cooldown.
    resolved_model = body.model
    candidates: list[str] = []
    if was_auto:
        body_dict = body.model_dump(exclude_none=True)
        needs = required_capabilities(body_dict)
        deployable = {
            d.model_name for d in getattr(client, "_deployments", []) or []
        }
        if not deployable:
            raise HTTPException(
                status_code=422,
                detail=(
                    "model='auto' requires at least one provider with a "
                    "configured key. No deployable provider found."
                ),
            )
        # When strategy is "quality", merge AA's Intelligence Index with
        # any manual operator overrides from the dashboard. Manual >  AA >
        # nothing. Empty dict (no AA key + no overrides) → resolver falls
        # back to the legacy cost-based proxy. Skipped for non-quality
        # strategies so we don't pay the cost on cheapest/balanced/fastest
        # calls that don't use the scores.
        quality_scores: dict[str, float] | None = None
        if strategy == "quality":
            quality_scores = await resolve_quality_scores(
                db=db, workspace_id=str(kc.workspace_id),
            )

        # Pass the key's allowlist into the resolver so it filters BEFORE
        # the top-N truncation. Without this, an allowed model ranked at
        # position 6+ would be silently dropped by top_n=5 and the user
        # would see a false 403 even though they have a valid candidate.
        candidates = choose_auto_model(
            needs=needs,
            deployable=deployable,
            candidates=CATALOG,
            strategy=strategy,
            preferred_models=preferred_models,
            allowlist=kc.model_allowlist,
            quality_scores=quality_scores,
        )
        if not candidates:
            # Empty result has two distinct causes — distinguish them so the
            # operator can debug the right thing:
            #   - 422: no model in the catalog can satisfy the request at all
            #          (capability mismatch or no provider key configured)
            #   - 403: capable models exist but none are in this key's allowlist
            # Re-run the resolver without the allowlist to tell which case
            # applies. Cheap (in-memory list comprehension, no DB / network).
            # Use `is not None` to honor explicit empty allowlist (deny-all).
            if kc.model_allowlist is not None:
                any_capable = choose_auto_model(
                    needs=needs,
                    deployable=deployable,
                    candidates=CATALOG,
                    strategy=strategy,
                    preferred_models=preferred_models,
                    allowlist=None,
                    quality_scores=quality_scores,
                    top_n=1,
                )
                if any_capable:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            f"No deployable model in this key's allowlist "
                            f"{kc.model_allowlist} satisfies the requested "
                            f"capabilities ({sorted(needs) or 'none'})."
                        ),
                    )
            raise HTTPException(
                status_code=422,
                detail=(
                    "No deployable model satisfies the requested capabilities "
                    f"({sorted(needs) or 'none'}). Configure a provider that "
                    "supports them or pin a specific model."
                ),
            )

        resolved_model = candidates[0]
        body.model = candidates[0]  # mutate for downstream completion call

    started_perf = time.perf_counter()
    completion_kwargs = body.model_dump(exclude_none=True)

    # Build the LiteLLM fallbacks argument from the auto candidate list.
    # Format: [{primary_model_name: [fallback_1, fallback_2, ...]}]
    # LiteLLM's async_function_with_fallbacks reads this from kwargs and
    # cascades automatically when the primary deployment fails or is in
    # cooldown — no explicit retry loop needed in this handler.
    fallbacks_arg: list | None = None
    if was_auto and len(candidates) > 1:
        fallbacks_arg = [{candidates[0]: candidates[1:]}]

    # On the auto path, set num_retries=0 so a dead primary cascades to the
    # next fallback immediately. Default num_retries (configured on Router)
    # would retry the primary 2x before cascading, adding 30-90s of latency
    # before the user sees a working response.
    settings = get_settings()
    per_call_kwargs: dict = {}
    if was_auto:
        per_call_kwargs["num_retries"] = settings.router_num_retries_auto

    # ── Prompt cache (blocking deterministic requests only) ────────────
    cache_status = "BYPASS"
    cache_hit_response: dict | None = None
    cache_lookup_key: str | None = None
    if not body.stream and prompt_cache.is_cacheable(completion_kwargs):
        cache_lookup_key = prompt_cache.cache_key(
            model=body.model,
            messages=completion_kwargs["messages"],
            temperature=completion_kwargs.get("temperature"),
            tools=completion_kwargs.get("tools"),
            response_format=completion_kwargs.get("response_format"),
            seed=completion_kwargs.get("seed"),
        )
        cached = await prompt_cache.get_backend().get(cache_lookup_key)
        if cached is not None:
            cache_status = "HIT"
            cache_hit_response = cached
        else:
            cache_status = "MISS"

    if cache_hit_response is not None:
        # Cache hit: served by us, no upstream call. Provider tagged "cache",
        # cost is zero so the savings dashboard stays accurate. We use the
        # resolved primary as the served model — cache lookup is keyed on
        # the same model so there's no cascade ambiguity here.
        cached_model = cache_hit_response.get("model", resolved_model)
        log = await _build_log_row(
            body=body, kc=kc,
            response={
                "model": cached_model,
                "usage": cache_hit_response.get("usage", {}),
                "_orca_meta": {"provider": "cache", "latency_ms": 0},
            },
            status_code=200, error_type=None, started_perf=started_perf,
            strategy=strategy,
            requested_model=requested_model,
            actual_resolved=cached_model,
        )
        log.cost_microcents = 0
        db.add(log)
        try:
            await db.commit()
        except Exception as commit_err:
            logger.warning("request_log_commit_failed", error=str(commit_err))
        return JSONResponse(
            content=cache_hit_response,
            headers={
                "x-orca-cache": "HIT",
                "x-orca-resolved-model": cached_model,
                "x-orca-requested-model": requested_model,
                "x-orca-routing-strategy": strategy,
            },
        )

    # ── Streaming path ─────────────────────────────────────────────────
    # NOTE: LiteLLM Router can fall back to a different model only BEFORE the
    # first chunk is emitted (or via MidStreamFallbackError, which only some
    # providers raise). Once any byte of the SSE stream is sent to the client,
    # mid-flight cascade is impossible — we have to surface the error and let
    # the client decide what to do.
    if body.stream:
        try:
            stream_obj = await client.acompletion(
                **completion_kwargs,
                fallbacks=fallbacks_arg,
                **per_call_kwargs,
            )
        except HTTPException:
            raise
        except UpstreamProviderError as exc:
            logger.warning("chat_completion_upstream_error", error=str(exc))
            raise HTTPException(
                status_code=exc.http_status,
                detail=f"Upstream provider error: {exc}",
            ) from exc
        except Exception as exc:
            logger.warning("chat_completion_upstream_error", error=str(exc))
            raise HTTPException(status_code=503, detail=f"Upstream provider error: {exc}") from exc

        async def sse() -> AsyncGenerator[str, None]:
            """Drain the chunk stream → emit SSE → write RequestLog when done."""
            agg_usage: dict = {}
            agg_provider = "unknown"
            agg_latency = 0
            # The first chunk's `model` field tells us what LiteLLM actually
            # served (could be a cascaded fallback, not the resolved primary).
            agg_model: str | None = None
            status_code = 200
            error_type: str | None = None
            try:
                async for chunk in _aiter(stream_obj):
                    d = _chunk_to_dict(chunk)
                    # Hoist orca-internal metadata onto the request log without
                    # leaking it into the SSE stream.
                    if "_orca_meta" in d:
                        meta = d.pop("_orca_meta") or {}
                        agg_provider = meta.get("provider", agg_provider)
                        agg_latency = meta.get("latency_ms", agg_latency)
                    if "usage" in d and d["usage"]:
                        agg_usage = d["usage"]
                    if d.get("model"):
                        agg_model = d["model"]
                    yield f"data: {json.dumps(d, separators=(',', ':'))}\n\n"
            except Exception as exc:
                # Translate the underlying LiteLLM exception so the request
                # log records the meaningful error_type (rate_limit_error,
                # model_not_found, ...) instead of just the raw class name.
                # The HTTP status is already 200 because headers were sent
                # before the first chunk; the SSE error frame carries the
                # type string for clients that parse it.
                from packages.litellm_adapter.client import _translate_error
                try:
                    translated = _translate_error(exc)
                except Exception:
                    translated = None
                if isinstance(translated, UpstreamProviderError):
                    error_type = translated.error_type
                    sse_error_type = translated.error_type
                else:
                    error_type = type(exc).__name__
                    sse_error_type = "upstream_error"
                # Mid-stream the response status is locked to 200 (headers
                # already flushed). Record 503 in the log to flag the
                # underlying upstream failure for analytics.
                status_code = 503
                logger.warning(
                    "chat_completion_stream_error",
                    error=str(exc), error_type=error_type,
                )
                err_body = {
                    "error": {
                        "message": f"Upstream provider error: {exc}",
                        "type": sse_error_type,
                    }
                }
                yield f"data: {json.dumps(err_body)}\n\n"
            finally:
                yield "data: [DONE]\n\n"
                # Real LiteLLM stream chunks don't carry _orca_meta (the
                # adapter only injects it on non-stream responses, since
                # wrapping every chunk would be wasteful). Look up provider
                # attribution from the served model name against the active
                # deployments — same lookup the non-stream adapter does.
                if agg_provider == "unknown" and agg_model:
                    deployments = getattr(client, "_deployments", []) or []
                    bare_served = (
                        agg_model.split("/", 1)[-1] if "/" in agg_model else agg_model
                    )
                    for d in deployments:
                        if agg_model in (d.litellm_model, d.model_name) or bare_served == d.model_name:
                            agg_provider = d.provider
                            break
                # Synthesize a response-shaped dict for the log helper.
                synthetic = {
                    "model": agg_model or resolved_model,
                    "usage": agg_usage,
                    "_orca_meta": {"provider": agg_provider, "latency_ms": agg_latency},
                }
                log = await _build_log_row(
                    body=body, kc=kc, response=synthetic,
                    status_code=status_code, error_type=error_type,
                    started_perf=started_perf,
                    strategy=strategy,
                    requested_model=requested_model,
                    actual_resolved=agg_model,
                )
                db.add(log)
                try:
                    await db.commit()
                except Exception as commit_err:
                    logger.warning("request_log_commit_failed", error=str(commit_err))

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                # Headers are sent before the first chunk, so we can only
                # promise the resolved primary here. The actual served model
                # ends up in each chunk's `model` field — clients reading the
                # stream get authoritative info from there.
                "x-orca-resolved-model": resolved_model,
                "x-orca-requested-model": requested_model,
                "x-orca-routing-strategy": strategy,
            },
        )

    # ── Blocking path ──────────────────────────────────────────────────
    status_code = 200
    error_type: str | None = None
    response: dict = {}
    actual_resolved: str | None = None
    try:
        response = await client.acompletion(
            **completion_kwargs,
            fallbacks=fallbacks_arg,
            **per_call_kwargs,
        )
        # The response.model field is what LiteLLM ultimately served — could
        # be the resolved primary, or a cascaded fallback if the primary 404'd.
        if isinstance(response, dict):
            actual_resolved = response.get("model") or resolved_model
    except HTTPException:
        raise
    except UpstreamProviderError as exc:
        status_code = exc.http_status
        error_type = exc.error_type
        logger.warning("chat_completion_upstream_error", error=str(exc), error_type=exc.error_type)
        raise HTTPException(
            status_code=exc.http_status,
            detail=f"Upstream provider error: {exc}",
        ) from exc
    except Exception as exc:
        status_code = 503
        error_type = type(exc).__name__
        logger.warning("chat_completion_upstream_error", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Upstream provider error: {exc}") from exc
    finally:
        log = await _build_log_row(
            body=body, kc=kc, response=response if isinstance(response, dict) else {},
            status_code=status_code, error_type=error_type,
            started_perf=started_perf,
            strategy=strategy,
            requested_model=requested_model,
            # On failure actual_resolved is None — fall back to the resolved
            # primary so the log row records what we tried, not "auto" (which
            # _build_log_row would otherwise default to via requested_model).
            actual_resolved=actual_resolved or resolved_model,
        )
        db.add(log)
        try:
            await db.commit()
        except Exception as commit_err:
            logger.warning("request_log_commit_failed", error=str(commit_err))

    if isinstance(response, dict) and "_orca_meta" in response:
        response = {k: v for k, v in response.items() if k != "_orca_meta"}

    # Write to cache on MISS only when the served model is in the same
    # model_group as the resolved primary. If LiteLLM Router cascaded to a
    # different group (fallback), the response is from a DIFFERENT model
    # than the cache key implies, and caching it would poison future
    # requests for the primary. Equivalent names within the same group
    # (prefix, dated alias) ARE safe to cache — see the helper for details.
    cache_safe_to_write = (
        cache_status == "MISS"
        and cache_lookup_key is not None
        and isinstance(response, dict)
        and _served_same_group_as_requested(
            requested_group=resolved_model,
            served_model=actual_resolved,
            client=client,
        )
    )
    if cache_safe_to_write:
        try:
            await prompt_cache.get_backend().set(cache_lookup_key, response, ttl=3600)
        except Exception as exc:
            logger.warning("prompt_cache_set_failed", error=str(exc))

    return JSONResponse(
        content=response,
        headers={
            "x-orca-cache": cache_status,
            # actual_resolved reflects post-cascade truth (might differ from
            # the primary if Router fell back). Falls back to resolved_model
            # if the response shape is unexpected.
            "x-orca-resolved-model": actual_resolved or resolved_model,
            "x-orca-requested-model": requested_model,
            "x-orca-routing-strategy": strategy,
        },
    )


def _aiter(obj):
    """Coerce a thing into an async iterator.

    LiteLLM's `acompletion(stream=True)` returns a `CustomStreamWrapper`
    that's already async-iterable. Test mocks may return a plain async
    generator. Accept both.
    """
    if hasattr(obj, "__aiter__"):
        return obj.__aiter__()
    if isinstance(obj, AsyncIterable):
        return obj.__aiter__()
    raise TypeError(f"Streaming router returned non-iterable: {type(obj).__name__}")
