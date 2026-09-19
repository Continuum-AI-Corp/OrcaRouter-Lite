"""Hosted-bypass detection (issue #140).

When a local BYOK key 429s, LiteLLM cools that deployment and the hosted
peer of the same model_name wins. The model name is unchanged; these
helpers are what let the response header / RequestLog tell them apart.
"""

from __future__ import annotations

from packages.litellm_adapter.hosted_fallback import (
    hidden_params_of,
    hosted_bypass_of_local,
    match_served_deployment,
    resolve_provider_and_fallback,
)
from packages.litellm_adapter.types import ProviderDeployment


def _local(model: str = "gpt-4o-mini") -> ProviderDeployment:
    return ProviderDeployment(
        model_name=model,
        litellm_model=f"openai/{model}",
        api_key="sk-local",
        provider="openai",
    )


def _hosted(model: str = "gpt-4o-mini") -> ProviderDeployment:
    wire = f"openai/{model}"
    return ProviderDeployment(
        model_name=model,
        litellm_model=wire,
        api_key="sk-orca-hosted",
        api_base="https://api.orcarouter.ai/v1",
        provider="orcarouter",
        custom_llm_provider="openai",
        deployment_id=f"hosted::{wire}",
    )


def test_hidden_params_of_reads_dict_and_ignores_junk():
    class _Resp:
        _hidden_params = {"model_id": "hosted::openai/gpt-4o-mini"}

    assert hidden_params_of(_Resp())["model_id"].startswith("hosted::")
    assert hidden_params_of(object()) == {}
    assert hidden_params_of(type("X", (), {"_hidden_params": "nope"})()) == {}


def test_match_by_pinned_hosted_deployment_id():
    served = match_served_deployment(
        [_local(), _hosted()],
        hidden={"model_id": "hosted::openai/gpt-4o-mini"},
        served_model="gpt-4o-mini",
    )
    assert served is not None
    assert served.provider == "orcarouter"
    assert served.deployment_id == "hosted::openai/gpt-4o-mini"


def test_match_by_hosted_api_base_when_model_id_missing():
    served = match_served_deployment(
        [_local(), _hosted()],
        hidden={"api_base": "https://api.orcarouter.ai/v1/"},
        served_model="gpt-4o-mini",
    )
    assert served is not None
    assert served.provider == "orcarouter"


def test_match_refuses_to_guess_when_local_and_hosted_share_the_name():
    """This is the visibility bug: same model_name, no hidden signal.
    Guessing the first (local) hit would hide a hosted bypass."""
    assert match_served_deployment(
        [_local(), _hosted()],
        hidden={},
        served_model="gpt-4o-mini",
    ) is None


def test_match_by_name_when_only_local_exists():
    served = match_served_deployment(
        [_local()], hidden={}, served_model="gpt-4o-mini",
    )
    assert served is not None
    assert served.provider == "openai"


def test_hosted_bypass_true_only_when_local_peer_exists():
    hosted = _hosted()
    assert hosted_bypass_of_local([_local(), hosted], hosted, requested_model="gpt-4o-mini")
    assert not hosted_bypass_of_local([hosted], hosted, requested_model="gpt-4o-mini")
    assert not hosted_bypass_of_local([_local(), hosted], _local(), requested_model="gpt-4o-mini")
    assert not hosted_bypass_of_local([_local(), hosted], None, requested_model="gpt-4o-mini")


def test_hosted_bypass_false_for_model_with_no_local_key():
    """Hosted covering a model the operator has no BYOK key for is the
    intended long-tail path, not a silent absorb of a dead local key."""
    claude_hosted = _hosted("claude-3-5-sonnet-latest")
    claude_hosted.litellm_model = "anthropic/claude-3-5-sonnet-latest"
    claude_hosted.deployment_id = "hosted::anthropic/claude-3-5-sonnet-latest"
    assert not hosted_bypass_of_local(
        [_local("gpt-4o-mini"), claude_hosted],
        claude_hosted,
        requested_model="claude-3-5-sonnet-latest",
    )


def test_resolve_hosted_fallback_after_local_429():
    """The 429-cooldown case: LiteLLM reports openai (hosted's
    custom_llm_provider) plus the pinned hosted deployment id."""
    provider, fallback = resolve_provider_and_fallback(
        [_local(), _hosted()],
        hidden={
            "custom_llm_provider": "openai",
            "model_id": "hosted::openai/gpt-4o-mini",
            "api_base": "https://api.orcarouter.ai/v1",
        },
        served_model="gpt-4o-mini",
        requested_model="gpt-4o-mini",
        litellm_provider="openai",
    )
    assert provider == "orcarouter"
    assert fallback is True


def test_resolve_local_win_stays_openai():
    provider, fallback = resolve_provider_and_fallback(
        [_local(), _hosted()],
        hidden={"custom_llm_provider": "openai"},
        served_model="gpt-4o-mini",
        requested_model="gpt-4o-mini",
        litellm_provider="openai",
    )
    # No model_id / api_base → we cannot prove hosted, so keep LiteLLM's
    # provider and do not claim a fallback (false positive is worse).
    assert provider == "openai"
    assert fallback is False


def test_resolve_hosted_only_is_orcarouter_but_not_fallback():
    provider, fallback = resolve_provider_and_fallback(
        [_hosted()],
        hidden={"model_id": "hosted::openai/gpt-4o-mini"},
        served_model="gpt-4o-mini",
        requested_model="gpt-4o-mini",
        litellm_provider="openai",
    )
    assert provider == "orcarouter"
    assert fallback is False


def test_orca_response_headers_emit_fallback_only_when_set():
    from app.routes.chat import FALLBACK_HEADER, _orca_response_headers

    local = _orca_response_headers(
        resolved_model="gpt-4o-mini",
        requested_model="gpt-4o-mini",
        strategy="balanced",
        cache_status="MISS",
    )
    assert FALLBACK_HEADER not in local
    assert local["x-orca-cache"] == "MISS"
    assert local["x-orca-resolved-model"] == "gpt-4o-mini"

    bypassed = _orca_response_headers(
        resolved_model="gpt-4o-mini",
        requested_model="gpt-4o-mini",
        strategy="balanced",
        fallback=True,
    )
    assert bypassed[FALLBACK_HEADER] == "true"


def test_resolve_falls_back_to_litellm_provider_when_no_match():
    provider, fallback = resolve_provider_and_fallback(
        [_local("gpt-4o")],
        hidden={},
        served_model="some-unknown-alias",
        requested_model="some-unknown-alias",
        litellm_provider="anthropic",
    )
    assert provider == "anthropic"
    assert fallback is False
