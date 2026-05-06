"""LiteLLM Router wrapper — the only module that imports litellm.

Lite edition: a thin wrapper. The full SaaS adapter handles streaming,
generation IDs, retry-cost accumulation, and structured error translation.
Lite covers the happy path and basic error mapping; that's enough for a
solo dev to ship a working router.
"""

from __future__ import annotations

import time

import structlog

from packages.litellm_adapter.types import ProviderDeployment, UpstreamProviderError

logger = structlog.get_logger(__name__)


def _build_allowed_fails_policy():
    """Construct an AllowedFailsPolicy that fails fast on hard errors and is
    lenient on transient ones. Returns None if litellm doesn't expose the type
    (older versions), in which case the caller's `allowed_fails` int applies
    uniformly.

    LiteLLM cooldown semantics (1.83.x): a deployment is cooled down when
    its failure count *exceeds* the resolved allowed-fails value, where
    `resolved = policy_value or router.allowed_fails`. Because `0` is
    falsy in that `or`, a policy value of 0 alone has NO effect — it
    silently inherits the router default. We rely on the caller setting
    `router_allowed_fails=0` (see app/config.py) so 0-valued policy entries
    here actually take effect: cool down on the very first failure for
    hard errors, give transient errors more headroom via non-zero values.
    """
    try:
        from litellm.types.router import AllowedFailsPolicy
    except Exception:
        return None
    return AllowedFailsPolicy(
        # 4xx is a mixed bucket — LiteLLM lumps these together with no way
        # to split them in AllowedFailsPolicy:
        #   - genuine deployment death:   model 404 / deprecated
        #   - client-side request error:  prompt too long, JSON malformed,
        #                                 unsupported parameter, model typo
        # The previous "0 = cool down on first failure" punished a single
        # client typo with a process-wide deployment freeze — actively
        # hostile during dev. 10 means a user can typo / oversize-prompt
        # their way through plenty of mistakes; if the deployment is
        # actually dead, the 11th failure still cools it within seconds.
        BadRequestErrorAllowedFails=10,
        # 401: API key is genuinely wrong / expired. No client-side
        # confusion possible — really cool down immediately.
        AuthenticationErrorAllowedFails=0,
        # 429: transient rate limit. Tolerate up to 3 in-window before cooling.
        RateLimitErrorAllowedFails=3,
        # 5xx: provider-side transient. Two strikes.
        InternalServerErrorAllowedFails=2,
        # Network timeouts: transient. Two strikes.
        TimeoutErrorAllowedFails=2,
    )


def _translate_error(exc: Exception) -> UpstreamProviderError:
    import litellm

    msg = str(exc)
    if isinstance(exc, litellm.ContextWindowExceededError):
        return UpstreamProviderError(msg, http_status=422, error_type="context_length_exceeded")
    if isinstance(exc, litellm.NotFoundError):
        return UpstreamProviderError(msg, http_status=422, error_type="model_not_found")
    if isinstance(exc, litellm.RateLimitError):
        return UpstreamProviderError(msg, http_status=429, error_type="rate_limit_error")
    if isinstance(exc, litellm.AuthenticationError):
        return UpstreamProviderError(msg, http_status=503, error_type="upstream_auth_error")
    if isinstance(exc, litellm.Timeout):
        return UpstreamProviderError(msg, http_status=503, error_type="upstream_timeout")
    return UpstreamProviderError(msg, http_status=503, error_type="upstream_error")


class OrcaLiteLLMClient:
    """Wraps a litellm.Router, routes by `model` alias, returns a dict."""

    def __init__(
        self,
        deployments: list[ProviderDeployment],
        *,
        strategy: str | None = None,
        preferred_models: list[str] | None = None,
        litellm_routing_strategy: str | None = None,
        # Router behavior knobs. Defaults keep prior behavior when caller
        # doesn't inject — but app code (router_cache.py) injects from
        # Settings so the deployment respects user config.
        cooldown_time: float = 1.0,
        allowed_fails: int | None = None,
        enable_pre_call_checks: bool = False,
        num_retries: int = 2,
    ):
        # Stash routing config on the instance so chat.py can read it without
        # re-querying the DB on every request.
        self.strategy = strategy or "balanced"
        self.preferred_models = list(preferred_models or [])

        # litellm-suppress-debug
        import litellm
        from litellm import Router
        litellm.suppress_debug_info = True
        litellm.vertex_project = None
        litellm.vertex_location = None

        model_list = []
        for d in deployments:
            params: dict = {
                "model": d.litellm_model,
                "api_key": d.api_key,
            }
            if d.api_base:
                params["api_base"] = d.api_base
            if d.custom_llm_provider:
                params["custom_llm_provider"] = d.custom_llm_provider
            if d.extra_headers:
                params["extra_headers"] = d.extra_headers
            if d.rpm:
                params["rpm"] = d.rpm
            if d.tpm:
                params["tpm"] = d.tpm
            entry: dict = {"model_name": d.model_name, "litellm_params": params}
            model_list.append(entry)

        if not model_list:
            self._router = None
            self._deployments = []
            return

        router_kwargs: dict = {
            "model_list": model_list,
            "num_retries": num_retries,
            "timeout": 30.0,
            "enable_pre_call_checks": enable_pre_call_checks,
        }
        # cooldown_time=0 must translate to disable_cooldowns=True. Otherwise
        # LiteLLM treats 0 as falsy and silently substitutes its 1-second
        # default — the test/dev "no cooldown" mode wouldn't actually take
        # effect, and a single 4xx in CI would cool a deployment for 1s and
        # cross-contaminate the next test.
        if cooldown_time and cooldown_time > 0:
            router_kwargs["cooldown_time"] = cooldown_time
        else:
            router_kwargs["disable_cooldowns"] = True
        if allowed_fails is not None:
            router_kwargs["allowed_fails"] = allowed_fails
            # Per-error-type policy: 4xx (model_not_found, bad payload) means
            # the deployment is genuinely broken — fail fast. 429 / timeouts
            # are usually transient, so give them more chances before cooldown
            # to avoid taking a model offline because of one rate-limit spike.
            policy = _build_allowed_fails_policy()
            if policy is not None:
                router_kwargs["allowed_fails_policy"] = policy
        if litellm_routing_strategy:
            router_kwargs["routing_strategy"] = litellm_routing_strategy

        self._router = Router(**router_kwargs)
        self._deployments = deployments

    async def acompletion(self, *, fallbacks: list | None = None, **kwargs):
        """Dispatch a chat completion through the LiteLLM Router.

        Returns:
          - Streaming (`stream=True`): the LiteLLM stream wrapper, an async
            iterable of chunk objects. The caller (chat.py) is responsible for
            iterating and dict-converting each chunk. We do NOT coerce the
            wrapper to a dict here — that would consume the stream eagerly
            and produce garbage.
          - Non-streaming: a plain dict (the OpenAI ChatCompletion response)
            with an extra `_orca_meta` key carrying provider attribution and
            measured latency.

        The `fallbacks` kwarg is passed through to LiteLLM's internal
        `async_function_with_fallbacks` cascade engine in the format
        `[{primary_model: [fb1, fb2, ...]}]`.
        """
        if self._router is None:
            raise UpstreamProviderError(
                "No provider keys configured. Set OPENAI_API_KEY (or another) "
                "in your env, or add a key via PUT /v1/providers/{provider}.",
                http_status=503,
                error_type="no_providers_configured",
            )
        if fallbacks is not None:
            kwargs["fallbacks"] = fallbacks
        is_streaming = bool(kwargs.get("stream"))
        started = time.perf_counter()
        try:
            resp = await self._router.acompletion(**kwargs)
        except Exception as exc:
            raise _translate_error(exc) from exc

        if is_streaming:
            # Stream wrappers are async iterables, not dicts. Return the raw
            # wrapper so the caller can `async for` over chunks. We forfeit
            # the `_orca_meta` injection on streams (provider attribution and
            # latency for stream requests degrade to defaults in the request
            # log) — a documented tradeoff that keeps this adapter thin and
            # avoids wrapping LiteLLM's stream object.
            return resp

        latency_ms = int((time.perf_counter() - started) * 1000)
        # LiteLLM stashes per-call diagnostics on `_hidden_params` BEFORE we
        # serialize. Pull what we need out first, because `model_dump()` drops
        # private-prefixed attrs and we lose them otherwise.
        #   - response_cost: USD cost LiteLLM computed at the moment it knew
        #     the resolved provider, including cache_creation/cache_read
        #     multipliers and reasoning-token pricing. Authoritative.
        #   - custom_llm_provider: the provider LiteLLM actually routed to
        #     ("openai", "anthropic", "gemini", ...). Beats our own
        #     deployment-loop matching, which can mis-attribute when LiteLLM
        #     rewrites the model name to a dated alias mid-cascade.
        hidden = getattr(resp, "_hidden_params", {}) or {}
        litellm_cost_usd = hidden.get("response_cost")
        litellm_provider = hidden.get("custom_llm_provider")

        # Convert litellm's ModelResponse to a plain dict + attach orca metadata.
        out = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)

        # Provider attribution: LiteLLM's own field wins. Fall back to a
        # deployment-loop lookup only when LiteLLM didn't supply one (very
        # old LiteLLM versions; defensive).
        provider = litellm_provider or "unknown"
        if not litellm_provider:
            for d in self._deployments:
                if d.litellm_model == out.get("model") or d.model_name == out.get("model"):
                    provider = d.provider
                    break

        out["_orca_meta"] = {
            "provider": provider,
            "latency_ms": latency_ms,
            "cost_usd": litellm_cost_usd,
        }
        return out
