"""POST /v1/chat/completions — the proxy endpoint, slimmed for lite.

Supports both blocking and streaming. The streaming path returns an SSE
response in OpenAI's `text/event-stream` format with a terminal
`data: [DONE]` sentinel, exactly matching what the OpenAI SDK expects.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, Callable

import anyio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import prompt_cache, router_cache
from app.auto_routing import (
    _VERSION_SUFFIX_RE,
    canonical_model_base,
    choose_auto_model,
    required_capabilities,
)
from app.config import get_settings
from app.deps import get_db, get_key_context
from app.protocols.sse import AdapterError
from app.quality_scores import resolve_model_metrics
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext
from packages.db.models.request_log import RequestLog
from packages.litellm_adapter.catalog import CATALOG, CATALOG_BY_ID
from packages.litellm_adapter.types import UpstreamProviderError

logger = structlog.get_logger()
router = APIRouter(prefix="/v1", tags=["Chat Completions"])

# Relays the engine's translated error type (rate_limit_error,
# model_not_found, ...) on engine-raised HTTPExceptions so the
# native-protocol routes can re-render the failure in their own
# status/error taxonomy.
ERROR_TYPE_HEADER = "x-orca-error-type"

# Delays (seconds) between successive attempts to commit a streaming
# RequestLog row; attempts = len + 1. That row is the only record of a
# stream's tokens and cost, so a commit that fails outright is retried on
# a fresh session before the row is given up on — bounded, because the
# retries hold the (already [DONE]) stream open. Tests shrink this.
_LOG_COMMIT_BACKOFF_S: tuple[float, ...] = (0.1, 0.4)


def _chunk_to_dict(chunk) -> dict:
    """Normalize a litellm chunk (Pydantic model or dict) into a plain dict."""
    if isinstance(chunk, dict):
        return chunk
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump(exclude_none=True)
    return dict(chunk)


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
    meta = response.get("_orca_meta", {}) or {}
    usage = response.get("usage", {}) or {}
    resolved = actual_resolved or response.get("model") or requested_model
    input_t = usage.get("prompt_tokens", 0) or 0
    output_t = usage.get("completion_tokens", 0) or 0
    return RequestLog(
        workspace_id=str(kc.workspace_id),
        api_key_id=str(kc.key_id),
        trace_id=str(uuid.uuid4()),
        model_requested=requested_model,
        model_resolved=resolved,
        provider=meta.get("provider", "unknown"),
        routing_strategy=strategy,
        input_tokens=input_t,
        output_tokens=output_t,
        cost_microcents=_compute_cost_microcents(
            litellm_cost_usd=usage.get("cost_usd") or meta.get("cost_usd"),
            model_id=resolved,
            input_tokens=input_t,
            output_tokens=output_t,
            fallback_model=requested_model,
        ),
        latency_ms=meta.get("latency_ms", latency_ms),
        status_code=status_code,
        error_type=error_type,
        is_streaming=body.stream,
    )


def _compute_cost_microcents(
    *,
    litellm_cost_usd: float | None,
    model_id: str | None,
    input_tokens: int,
    output_tokens: int,
    fallback_model: str | None = None,
) -> int:
    """Cost in microcents (1 USD = 1,000,000).

    Two-tier strategy:

      Tier 1 — `litellm_cost_usd` from the response's _orca_meta. This is
      LiteLLM's own `_hidden_params.response_cost`, computed in the adapter
      at the moment LiteLLM Router knew which provider it actually called.
      Authoritative because it includes:
        - Anthropic prompt caching (cache_creation = 1.25x base,
          cache_read = 0.1x base)
        - OpenAI o1/o3 reasoning tokens (priced separately from output)
        - Audio input/output token pricing
        - Provider-specific aliasing — no name-matching guesswork needed
      We do NOT call `litellm.completion_cost(response)` here: that helper
      tries to re-derive the provider from the response dict and fails on
      Anthropic/Gemini bare names ("Provider NOT provided" or
      "model isn't mapped"), so reverse-lookup is unreliable.

      Tier 2 — `tokens × catalog price` fallback. Used when LiteLLM didn't
      attach a cost (cache hit served from our prompt cache, exception
      paths where `_orca_meta` is absent, custom upstreams). Walks four
      catalog id shapes: as-is, prefix-stripped, version-suffix-stripped,
      then the original requested model id.

    Returns 0 only when both tiers miss. Negative tokens / negative cost
    are clamped to 0 (defensive against malformed upstream usage data).
    """
    if input_tokens < 0 or output_tokens < 0:
        return 0

    # Tier 1: LiteLLM's authoritative number, plumbed through _orca_meta.
    if litellm_cost_usd is not None and litellm_cost_usd > 0:
        return max(0, int(litellm_cost_usd * 1_000_000))

    # Tier 2: catalog × tokens fallback.
    m = _lookup_priced_model(model_id) or _lookup_priced_model(fallback_model)
    if m is None:
        return 0
    cost_usd = (
        input_tokens * m.input_cost_per_token
        + output_tokens * m.output_cost_per_token
    )
    return max(0, int(cost_usd * 1_000_000))


def _lookup_priced_model(model_id: str | None):
    """Try four id-shape variants, return the first catalog hit or None.

    Order:
      1. as-is
      2. provider-prefix stripped ("openai/gpt-4o" -> "gpt-4o")
      3. version-suffix stripped (handles "claude-3-5-sonnet-20241022" ->
         "claude-3-5-sonnet" when the response was a dated alias and only
         the base form is in our catalog)
    """
    if not model_id:
        return None
    m = CATALOG_BY_ID.get(model_id)
    if m is not None:
        return m
    bare = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    if bare != model_id:
        m = CATALOG_BY_ID.get(bare)
        if m is not None:
            return m
    base = canonical_model_base(bare)
    if base != bare:
        return CATALOG_BY_ID.get(base)
    return None


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
):
    return await execute_chat(body, kc, db)


async def execute_chat(
    body: ChatCompletionRequest,
    kc: KeyContext,
    db: AsyncSession,
    *,
    log_status: Callable[[int, str | None], int] | None = None,
) -> JSONResponse | StreamingResponse:
    """Protocol-agnostic chat engine — the full pipeline behind
    POST /v1/chat/completions (allowlist → auto-resolution → prompt cache →
    LiteLLM Router → RequestLog writeback), reusable by native-protocol
    adapters (Anthropic /v1/messages, Gemini /v1beta) with a translated body.

    Returns OpenAI-wire-format results: JSONResponse for blocking requests,
    StreamingResponse emitting `data: {json}\\n\\n` frames with a terminal
    `data: [DONE]` for streaming. Raises HTTPException on pre-stream errors.

    `log_status(engine_status, error_type)` lets a native-protocol caller
    record in the RequestLog the status IT will deliver for an upstream
    failure (e.g. 404 for model_not_found where this engine says 422), on
    both the blocking and the streaming path, so the persisted outcome
    matches what went over the wire.
    """
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
                # Same operator-side, permanent condition the pinned-model
                # path reports as no_providers_configured. Without the
                # type the native surfaces would collapse this 422 to a
                # client-blaming 400 while the pinned path renders 403.
                headers={ERROR_TYPE_HEADER: "no_providers_configured"},
            )
        # `quality`, `balanced`, `fastest` all want AA-derived metrics.
        # `resolve_model_metrics` does the AA fetch + merges manual
        # overrides for the quality axis (TPS / TTFT have no override
        # concept) and is cached at the resolver layer for 60s, so the
        # default `balanced` strategy doesn't pay a DB hit per request.
        # Skipped for `cheapest` / None where the metrics aren't used.
        quality_scores: dict[str, float] | None = None
        tps_scores: dict[str, float] | None = None
        ttft_scores: dict[str, float] | None = None
        if strategy in ("quality", "balanced", "fastest"):
            metrics = await resolve_model_metrics(
                db=db, workspace_id=str(kc.workspace_id),
            )
            quality_scores = metrics.quality_scores
            tps_scores = metrics.tps_scores
            ttft_scores = metrics.ttft_scores

        # Pass the key's allowlist into the resolver so it filters BEFORE
        # the top-N truncation. Without this, an allowed model ranked at
        # position 6+ would be silently dropped by top_n=5 and the user
        # would see a false 403 even though they have a valid candidate.
        candidates, _scoring = choose_auto_model(
            needs=needs,
            deployable=deployable,
            candidates=CATALOG,
            strategy=strategy,
            preferred_models=preferred_models,
            allowlist=kc.model_allowlist,
            quality_scores=quality_scores,
            tps_scores=tps_scores,
            ttft_scores=ttft_scores,
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
                any_capable, _ = choose_auto_model(
                    needs=needs,
                    deployable=deployable,
                    candidates=CATALOG,
                    strategy=strategy,
                    preferred_models=preferred_models,
                    allowlist=None,
                    quality_scores=quality_scores,
                    tps_scores=tps_scores,
                    ttft_scores=ttft_scores,
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
                # Operator-side and permanent like its sibling above:
                # providers ARE configured, but none of their deployable
                # models has a capability the request needs (vision, tools,
                # json_mode). The type lets the native surfaces render it
                # as 403 permission_error / PERMISSION_DENIED — the same
                # class as no_providers_configured — instead of collapsing
                # the bare 422 to a client-blaming 400.
                headers={ERROR_TYPE_HEADER: "no_capable_provider"},
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
            max_tokens=completion_kwargs.get("max_tokens"),
            stop=completion_kwargs.get("stop"),
            tool_choice=completion_kwargs.get("tool_choice"),
            top_p=completion_kwargs.get("top_p"),
            n=completion_kwargs.get("n"),
            presence_penalty=completion_kwargs.get("presence_penalty"),
            frequency_penalty=completion_kwargs.get("frequency_penalty"),
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
        # Auto-inject `stream_options.include_usage=True` if the client
        # didn't set it. Without this, OpenAI/LiteLLM streaming responses
        # omit the `usage` field entirely — chunks have no token counts,
        # so our log row gets input=0, output=0 and the cost calculation
        # rounds to zero. Almost no client knows to opt-in to this flag,
        # which would silently zero out streaming spend in the dashboard.
        # Honor an explicit `include_usage=False` from the client if they
        # really want to disable it (e.g. wire-format compatibility tests).
        existing_so = completion_kwargs.get("stream_options") or {}
        if "include_usage" not in existing_so:
            completion_kwargs["stream_options"] = {**existing_so, "include_usage": True}

        async def _log_pre_stream_failure(status: int, err_type: str | None) -> None:
            """Persist a row for a stream that failed BEFORE its first chunk.

            The mid-stream path logs from `_finalize` and the blocking path
            from its `finally`, but this failure happens between them: the
            client is rendered a real 404/429/403/503 and nothing recorded
            it, so the same upstream failure was accounted for when
            stream=false and vanished when stream=true.
            """
            if log_status is not None and err_type is not None:
                status = log_status(status, err_type)
            log = await _build_log_row(
                body=body, kc=kc, response={},
                status_code=status, error_type=err_type,
                started_perf=started_perf,
                strategy=strategy,
                requested_model=requested_model,
                actual_resolved=resolved_model,
            )
            db.add(log)
            try:
                await db.commit()
            except Exception as commit_err:
                logger.warning("request_log_commit_failed", error=str(commit_err))

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
            await _log_pre_stream_failure(exc.http_status, exc.error_type)
            raise HTTPException(
                status_code=exc.http_status,
                detail=f"Upstream provider error: {exc}",
                # The generic HTTP status alone loses the translated type
                # (e.g. model_not_found is 422 here but 404 on the
                # Anthropic/Gemini surfaces).
                headers={ERROR_TYPE_HEADER: exc.error_type},
            ) from exc
        except Exception as exc:
            logger.warning("chat_completion_upstream_error", error=str(exc))
            await _log_pre_stream_failure(503, type(exc).__name__)
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
            log_written = False

            async def _finalize() -> None:
                """Write the request log row exactly once.

                Called from two places: the cancel branch (so the row lands
                even if the [DONE] yield fails against a disconnected
                client), and the `finally` block (the normal path). The
                `log_written` guard makes the second call a no-op when the
                cancel path already ran.
                """
                nonlocal log_written, agg_provider
                if log_written:
                    return
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
                synthetic = {
                    "model": agg_model or resolved_model,
                    "usage": agg_usage,
                    "_orca_meta": {"provider": agg_provider},
                }
                if agg_latency:
                    # Real LiteLLM chunks carry no _orca_meta, so this is
                    # normally absent — leaving the key out lets
                    # _build_log_row fall back to the measured wall-clock
                    # latency instead of persisting a constant 0.
                    synthetic["_orca_meta"]["latency_ms"] = agg_latency
                from sqlalchemy import select

                from packages.db import session as session_mod

                # The row's VALUES are computed exactly once — latency is
                # measured here, before any commit attempt, so retry
                # backoff never inflates it — and every attempt inserts a
                # fresh ORM object carrying the same id/trace_id. (Fresh,
                # because an object left over from a failed flush carries
                # session state that makes a second session treat it as
                # an UPDATE, not an INSERT.)
                # Same correction the blocking path applies: on a native
                # surface the delivered status differs from the engine's
                # generic one (the Gemini aggregate stream renders a real
                # 404/429/403 from the error chunk; the SSE surfaces report
                # the same class in their in-band error frame), so the row
                # must not say 503 for a response the client saw as 404.
                row_status = status_code
                if log_status is not None and error_type is not None:
                    row_status = log_status(status_code, error_type)
                template = await _build_log_row(
                    body=body, kc=kc, response=synthetic,
                    status_code=row_status, error_type=error_type,
                    started_perf=started_perf,
                    strategy=strategy,
                    requested_model=requested_model,
                    actual_resolved=agg_model,
                )
                row_values = {
                    c.key: getattr(template, c.key)
                    for c in RequestLog.__table__.columns
                    if getattr(template, c.key) is not None
                }
                row_values.setdefault("id", str(uuid.uuid4()))

                async def _already_persisted(s) -> bool:
                    return (await s.scalar(
                        select(RequestLog.id).where(RequestLog.trace_id == row_values["trace_id"])
                    )) is not None

                async def _commit_row(*, retry: bool) -> None:
                    """INSERT + COMMIT the row on a session of its own.

                    Only a failing `commit()` propagates; a failure while
                    closing the session AFTER the commit returned is
                    swallowed — the row is already in. A retry is
                    idempotent: it first looks the trace_id up, so a COMMIT
                    that landed but whose ack was lost on the wire
                    (PostgreSQL, connection dropped mid-ack) is not
                    inserted a second time — and the shared primary key
                    would reject a duplicate anyway.
                    """
                    log = RequestLog(**row_values)
                    if session_mod._session_factory is None:
                        # Test-only fallback (the app always installs a
                        # factory): the request-scoped session has to be
                        # rolled back before a retry can reuse it.
                        if retry and await _already_persisted(db):
                            return
                        db.add(log)
                        try:
                            await db.commit()
                        except Exception:
                            try:
                                await db.rollback()
                            except Exception:
                                pass
                            raise
                        return
                    s = session_mod._session_factory()
                    try:
                        if retry and await _already_persisted(s):
                            return
                        s.add(log)
                        await s.commit()
                    finally:
                        try:
                            await s.close()
                        except Exception as close_err:
                            logger.debug(
                                "request_log_session_close_failed", error=str(close_err),
                            )

                # At-most-once across the two call sites: mark BEFORE the
                # first attempt so the other _finalize never re-runs this
                # sequence. Retries live HERE, bounded by
                # _LOG_COMMIT_BACKOFF_S and only for a commit that failed
                # outright — this row is the only record of a stream's
                # tokens and cost, so a transient DB hiccup at request end
                # must not silently zero that spend. Durability against a
                # close/cancel landing mid-commit (e.g. a disconnect
                # delivered during the protocol adapters' post-[DONE]
                # drain) comes from running each attempt in its own task:
                # cancellation aimed at THIS task can't abort the INSERT.
                log_written = True
                attempts = len(_LOG_COMMIT_BACKOFF_S) + 1
                for attempt in range(1, attempts + 1):
                    commit_task = asyncio.ensure_future(_commit_row(retry=attempt > 1))
                    try:
                        await asyncio.shield(commit_task)
                        return
                    except Exception as commit_err:
                        if attempt < attempts:
                            logger.info(
                                "request_log_commit_retry",
                                error=str(commit_err), attempt=attempt,
                            )
                            try:
                                await asyncio.sleep(_LOG_COMMIT_BACKOFF_S[attempt - 1])
                            except BaseException:
                                # Cancelled during the backoff: nothing is
                                # in flight, the row is given up on — say
                                # so, then propagate like the arm below.
                                logger.warning(
                                    "request_log_commit_failed",
                                    error=str(commit_err), attempts=attempt,
                                )
                                raise
                            continue
                        logger.warning(
                            "request_log_commit_failed",
                            error=str(commit_err), attempts=attempt,
                        )
                    except BaseException:
                        # CancelledError aimed at us, not at the commit —
                        # wait the in-flight attempt out so a row about to
                        # land isn't dropped, then let the cancellation
                        # propagate (no further attempts: we are being torn
                        # down).
                        try:
                            await commit_task
                        except Exception as commit_err:
                            logger.warning(
                                "request_log_commit_failed",
                                error=str(commit_err), attempts=attempt,
                            )
                        except BaseException:
                            pass
                        raise

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
                yield "data: [DONE]\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                # Client closed the connection (Ctrl+C, tab closed, browser
                # navigated away, proxy timeout, ...). Two distinct signals
                # land here depending on which side noticed first:
                #   - CancelledError: asyncio task running the generator was
                #     cancelled (Starlette saw the disconnect first).
                #   - GeneratorExit: Starlette called aclose() on us during
                #     its own cleanup pass.
                # Either way the consumer is gone — no point yielding more
                # frames, and we MUST stop pulling chunks from upstream so
                # LiteLLM doesn't keep burning tokens on a response nobody
                # will read.
                error_type = "client_disconnect"
                # 499 Client Closed Request — nginx convention, widely
                # understood in analytics pipelines for "user bailed".
                status_code = 499
                logger.info(
                    "chat_completion_stream_client_disconnect",
                    served_model=agg_model,
                )
                # Cleanup MUST actually complete before we unwind, not just
                # be scheduled. `asyncio.shield()` here would NOT wait — the
                # outer await re-raises CancelledError immediately under
                # Starlette's anyio task group cancellation, leaving the
                # inner aclose/finalize racing FastAPI's request-scoped
                # session teardown.
                #
                # `anyio.CancelScope(shield=True)` is the right primitive:
                # awaits inside the shielded scope ignore outer cancellation
                # and run to completion. The scope exits normally and we
                # re-raise the original CancelledError below.
                aclose = getattr(stream_obj, "aclose", None)
                with anyio.CancelScope(shield=True):
                    if aclose is not None:
                        try:
                            await aclose()
                        except Exception:
                            pass
                    try:
                        await _finalize()
                    except Exception:
                        pass
                # Re-raise so asyncio/Starlette see proper cancel propagation.
                raise
            except AdapterError:
                # The protocol adapter downstream of us failed and threw
                # this in rather than closing us: our own fault, not the
                # caller's. Without this branch the close would be
                # indistinguishable from a disconnect and every adapter bug
                # would be filed as 499/client_disconnect.
                error_type = "adapter_error"
                status_code = 500
                logger.warning(
                    "chat_completion_stream_adapter_error", served_model=agg_model,
                )
                aclose = getattr(stream_obj, "aclose", None)
                with anyio.CancelScope(shield=True):
                    if aclose is not None:
                        try:
                            await aclose()
                        except Exception:
                            pass
                return
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
                # Not handling GeneratorExit here, so yielding the sentinel
                # is legal; clients reading until [DONE] still get it after
                # an upstream error.
                yield "data: [DONE]\n\n"
            finally:
                # Same shielding reason as the cancel branch: ensure the
                # log write actually completes before we unwind, even if
                # we're inside a cancelled scope. The cancel branch may
                # have already run _finalize and set log_written=True; the
                # `if log_written: return` guard inside makes this call a
                # cheap no-op in that case.
                with anyio.CancelScope(shield=True):
                    try:
                        await _finalize()
                    except Exception:
                        pass

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
            # See the streaming-path twin: lets the native routes map the
            # translated type to their surface's status/error taxonomy.
            headers={ERROR_TYPE_HEADER: exc.error_type},
        ) from exc
    except Exception as exc:
        status_code = 503
        error_type = type(exc).__name__
        logger.warning("chat_completion_upstream_error", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Upstream provider error: {exc}") from exc
    finally:
        if log_status is not None and error_type is not None:
            status_code = log_status(status_code, error_type)
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
