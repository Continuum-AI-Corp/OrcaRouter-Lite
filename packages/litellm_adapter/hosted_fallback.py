"""Detect when hosted-as-upstream served a model a local BYOK key covers.

`build_deployments()` registers hosted entries alongside local ones under the
same `model_name`, so LiteLLM treats them as equal-priority peers. After a
local 429 cools the BYOK deployment, hosted wins and `x-orca-resolved-model`
looks unchanged. These helpers recover the actual source from LiteLLM's
per-call diagnostics so callers can surface `x-orca-fallback: true`.
"""

from __future__ import annotations

from packages.litellm_adapter.types import ProviderDeployment

HOSTED_PROVIDER = "orcarouter"
HOSTED_DEPLOYMENT_PREFIX = "hosted::"


def hidden_params_of(resp: object) -> dict:
    """LiteLLM stashes per-call diagnostics on `_hidden_params` (dict)."""
    hidden = getattr(resp, "_hidden_params", None)
    return hidden if isinstance(hidden, dict) else {}


def _norm_base(url: str | None) -> str:
    return (url or "").rstrip("/")


def _bare(name: str) -> str:
    return name.split("/", 1)[-1] if "/" in name else name


def _model_matches(deployment: ProviderDeployment, served_model: str | None) -> bool:
    if not served_model:
        return False
    if served_model in (deployment.model_name, deployment.litellm_model):
        return True
    bare = _bare(served_model)
    return bare == deployment.model_name or bare == _bare(deployment.litellm_model)


def match_served_deployment(
    deployments: list[ProviderDeployment],
    *,
    hidden: dict | None = None,
    served_model: str | None = None,
) -> ProviderDeployment | None:
    """Identify the deployment LiteLLM actually called.

    Preference order:
      1. pinned `model_info.id` (hosted entries use `hosted::{wire_id}`)
      2. `api_base` — hosted always sets one; local BYOK usually does not
      3. model-name match, but only when it is unambiguous (a shared
         model_name between local + hosted is the visibility bug)
    """
    hidden = hidden or {}
    model_id = hidden.get("model_id")
    if isinstance(model_id, str) and model_id:
        for deployment in deployments:
            if deployment.deployment_id == model_id:
                return deployment
        if model_id.startswith(HOSTED_DEPLOYMENT_PREFIX):
            hosted = [d for d in deployments if d.provider == HOSTED_PROVIDER]
            for deployment in hosted:
                if _model_matches(deployment, served_model):
                    return deployment
            return hosted[0] if len(hosted) == 1 else None

    api_base = hidden.get("api_base")
    if isinstance(api_base, str) and api_base:
        norm = _norm_base(api_base)
        at_base = [
            d for d in deployments
            if d.api_base and _norm_base(d.api_base) == norm
        ]
        if at_base:
            for deployment in at_base:
                if _model_matches(deployment, served_model):
                    return deployment
            providers = {d.provider for d in at_base}
            if len(providers) == 1:
                return at_base[0]

    if not served_model:
        return None
    name_hits = [d for d in deployments if _model_matches(d, served_model)]
    if not name_hits:
        return None
    if len({d.provider for d in name_hits}) == 1:
        return name_hits[0]
    return None


def hosted_bypass_of_local(
    deployments: list[ProviderDeployment],
    served: ProviderDeployment | None,
    *,
    requested_model: str | None = None,
) -> bool:
    """True when hosted served a model that also has a local BYOK deployment.

    Hosted-only coverage (no local key for that model) is the intended
    long-tail path, not a bypass — callers should not see the fallback
    header in that case.
    """
    if served is None or served.provider != HOSTED_PROVIDER:
        return False
    groups = {served.model_name, _bare(served.model_name), _bare(served.litellm_model)}
    if requested_model:
        groups.add(requested_model)
        groups.add(_bare(requested_model))
    return any(
        d.provider != HOSTED_PROVIDER and d.model_name in groups
        for d in deployments
    )


def resolve_provider_and_fallback(
    deployments: list[ProviderDeployment],
    *,
    hidden: dict | None = None,
    served_model: str | None = None,
    requested_model: str | None = None,
    litellm_provider: str | None = None,
) -> tuple[str, bool]:
    """Return `(provider, hosted_fallback)` for a completed call.

    Hosted traffic is attributed as `orcarouter` (not LiteLLM's
    `custom_llm_provider="openai"`) so analytics can tell BYOK from
    hosted billing.
    """
    served = match_served_deployment(
        deployments, hidden=hidden, served_model=served_model,
    )
    fallback = hosted_bypass_of_local(
        deployments, served, requested_model=requested_model,
    )
    if served is not None:
        return served.provider, fallback
    if litellm_provider:
        return litellm_provider, False
    if served_model:
        for deployment in deployments:
            if deployment.litellm_model == served_model or deployment.model_name == served_model:
                return deployment.provider, False
    return "unknown", False
