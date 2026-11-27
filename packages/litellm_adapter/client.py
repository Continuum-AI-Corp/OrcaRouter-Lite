"""LiteLLM Router wrapper — the only module that imports litellm.

Lite edition: a thin wrapper. The full SaaS adapter handles streaming,
generation IDs, retry-cost accumulation, and structured error translation.
Lite covers the happy path and basic error mapping; that's enough for a
solo dev to ship a working router.
"""

from __future__ import annotations

import re
import time

import httpx
import structlog

from packages.litellm_adapter.hosted_catalog import is_free_hosted
from packages.litellm_adapter.hosted_fallback import (
    HOSTED_DEPLOYMENT_PREFIX,
    hidden_params_of,
    hosted_cost_usd,
    match_served_deployment,
    resolve_provider_and_fallback,
)
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


# OrcaRouter's words when it refuses its free models to a whole account.
_NOT_ELIGIBLE = "not available to this account"
_LITELLM_PREFIX = re.compile(r"^(?:litellm\.\w+: )?(?:\w+: )?(?:\w+Exception - )?")


def free_refusal(exc: Exception) -> str | None:
    """OrcaRouter's message when it refused a free model for the whole account
    (not eligible for free models yet, or the free allowance is used up);
    None for anything else, a passing free rate limit included."""
    failed = str(getattr(exc, "failed_deployment_id", "") or "")
    if not failed.startswith(HOSTED_DEPLOYMENT_PREFIX) or not is_free_hosted(failed[len(HOSTED_DEPLOYMENT_PREFIX):]):
        return None
    body = getattr(exc, "body", None)
    body = body if isinstance(body, dict) else {}
    # LiteLLM prefixes the upstream text with its own exception names.
    message = _LITELLM_PREFIX.sub("", str(body.get("message") or exc)).strip()
    status = getattr(exc, "status_code", None)
    if status == 402 or body.get("code") == "free_quota_exhausted":
        return message
    if status == 429 and _NOT_ELIGIBLE in message:
        return message
    return None


def free_refusal_watcher(on_refusal):
    """A LiteLLM callback calling `on_refusal(message)` whenever a free model
    is refused for the account, also mid-fallback when a later model answers
    (the final error alone would miss those)."""
    from litellm.integrations.custom_logger import CustomLogger

    class _Watcher(CustomLogger):
        async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
            exc = kwargs.get("exception")
            if exc is None:
                return
            if not getattr(exc, "failed_deployment_id", None):
                model_info = (kwargs.get("litellm_params") or {}).get("model_info") or {}
                try:
                    exc.failed_deployment_id = model_info.get("id")
                except AttributeError:
                    return
            message = free_refusal(exc)
            if message:
                on_refusal(message)

    return _Watcher()


# Deployment ids of the models on this computer (packages/desktop/local_models.py).
LOCAL_DEPLOYMENT_PREFIX = "local::"
LOCAL_RUNTIME_UNAVAILABLE = "local_runtime_unavailable"


def _connect_failure(exc: BaseException) -> bool:
    """The request never reached the server: nothing listened at the address
    (connection refused, which Windows reports as a connect timeout)."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, (httpx.ConnectError, httpx.ConnectTimeout)):
            return True
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return False


def _translate_error(exc: Exception) -> UpstreamProviderError:
    import litellm

    msg = str(exc)
    refused = free_refusal(exc)
    if refused:
        # Not a rate limit to retry nor an empty wallet: this account can't
        # use OrcaRouter's free models (the message says why and what to do).
        return UpstreamProviderError(refused, http_status=403, error_type="free_unavailable")
    failed = str(getattr(exc, "failed_deployment_id", "") or "")
    if failed.startswith(LOCAL_DEPLOYMENT_PREFIX) and _connect_failure(exc):
        # Ollama / LM Studio / llama.cpp isn't running: not a slow upstream
        # (LiteLLM calls it a timeout or a connection error depending on the
        # runtime and the platform), and nothing a retry fixes until it starts.
        return UpstreamProviderError(msg, http_status=503, error_type=LOCAL_RUNTIME_UNAVAILABLE, deployment_id=failed)
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
    if getattr(exc, "status_code", None) == 402:
        # Payment required. From OrcaRouter that means its credit ran out
        # (the desktop app says so and keeps to own keys for a while); from
        # an own key (DeepSeek's empty balance) it's that account's problem.
        # LiteLLM names the deployment that failed; hosted ids are pinned.
        failed = str(getattr(exc, "failed_deployment_id", "") or "")
        kind = "out_of_credit" if failed.startswith(HOSTED_DEPLOYMENT_PREFIX) else "payment_required"
        return UpstreamProviderError(msg, http_status=402, error_type=kind)
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
            if d.timeout:
                params["timeout"] = (
                    httpx.Timeout(d.timeout, connect=d.connect_timeout) if d.connect_timeout else d.timeout
                )
                params["stream_timeout"] = d.timeout
            if d.extra_params:
                params.update(d.extra_params)
            if d.rpm:
                params["rpm"] = d.rpm
            if d.tpm:
                params["tpm"] = d.tpm
            entry: dict = {"model_name": d.model_name, "litellm_params": params}
            model_info: dict = {}
            if d.deployment_id:
                # Pins the Router's deployment id so aliases of one upstream
                # share cooldown / allowed-fails state instead of each
                # spelling failing its own way into a cooldown.
                model_info["id"] = d.deployment_id
            # Without supports_response_schema, some LiteLLM versions
            # re-wrap or tool-translate LangChain's json_schema
            # response_format and OpenAI rejects it as
            # "Invalid schema for response_format".
            if d.provider == "openai" or d.custom_llm_provider == "openai":
                model_info["supports_response_schema"] = True
            if model_info:
                entry["model_info"] = model_info
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
        #   - model_id / api_base: which deployment won. Hosted pins
        #     model_info.id to `hosted::{wire_id}` and always sets api_base;
        #     without those, hosted traffic is attributed as "openai"
        #     (custom_llm_provider on the hosted entry) and a 429-cooled
        #     BYOK key is silently bypassed.
        hidden = hidden_params_of(resp)
        litellm_cost_usd = hidden.get("response_cost")
        litellm_provider = hidden.get("custom_llm_provider")

        # Convert litellm's ModelResponse to a plain dict + attach orca metadata.
        out = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)

        provider, hosted_fallback = resolve_provider_and_fallback(
            self._deployments,
            hidden=hidden,
            served_model=out.get("model"),
            requested_model=kwargs.get("model"),
            litellm_provider=litellm_provider,
        )

        # OrcaRouter reports each request's exact cost in a response header
        # (asked for with X-OrcaRouter-beta-usd); it beats LiteLLM's own
        # estimate, which doesn't know hosted prices.
        hosted_cost = hosted_cost_usd(hidden)
        out["_orca_meta"] = {
            "provider": provider,
            "latency_ms": latency_ms,
            "cost_usd": hosted_cost if hosted_cost is not None else litellm_cost_usd,
        }
        served = match_served_deployment(self._deployments, hidden=hidden, served_model=out.get("model"))
        if served is not None:
            # The deployment's own name (e.g. a free model's id), whatever
            # spelling the upstream put in the response.
            out["_orca_meta"]["model_group"] = served.model_name
        if hosted_fallback:
            out["_orca_meta"]["fallback"] = True
            logger.info(
                "hosted_fallback_used",
                model=out.get("model"),
                requested=kwargs.get("model"),
                provider=provider,
            )
        return out
