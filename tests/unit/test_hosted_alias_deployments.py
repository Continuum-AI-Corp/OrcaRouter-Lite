"""Hosted wire-id aliases are ONE upstream under two names (PR #64 round 4).

`build_deployments` registers both the bare id ("free") and the wire id
("orcarouter/free") so either spelling routes. LiteLLM Router derives a
deployment id per entry, so without pinning it the two names carry
independent cooldown / allowed-fails state: a dead upstream gets probed
(and paid for) once per alias before each spelling cools down.
"""

from __future__ import annotations

import pytest

from packages.litellm_adapter.client import OrcaLiteLLMClient
from packages.litellm_adapter.hosted_catalog import HOSTED_MODEL_ALIASES
from packages.litellm_adapter.types import ProviderDeployment


def test_aliased_hosted_models_share_one_deployment_id(monkeypatch):
    from app import config as cfg
    from app import router_cache

    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-hosted")
    cfg.get_settings.cache_clear()
    try:
        deployments = router_cache.build_deployments(
            env_keys={}, db_keys=[], settings=cfg.get_settings(),
        )
    finally:
        cfg.get_settings.cache_clear()

    by_name = {d.model_name: d for d in deployments}
    assert HOSTED_MODEL_ALIASES, "expected at least one aliased hosted model"
    for wire_id in HOSTED_MODEL_ALIASES:
        bare_id = wire_id.split("/", 1)[1]
        assert wire_id in by_name and bare_id in by_name
        # same upstream → same pinned id → shared cooldown/health state
        assert by_name[wire_id].litellm_model == by_name[bare_id].litellm_model
        assert by_name[wire_id].deployment_id == by_name[bare_id].deployment_id
        assert by_name[wire_id].deployment_id


def test_pinned_deployment_id_reaches_the_litellm_router():
    """LiteLLM would otherwise hash a distinct id per entry — the two names
    must resolve to the same deployment id in the built Router."""
    pytest.importorskip("litellm")
    shared = "hosted::orcarouter/free"
    client = OrcaLiteLLMClient(
        [
            ProviderDeployment(
                model_name=name, litellm_model="orcarouter/free", api_key="k",
                api_base="http://localhost:1", provider="orcarouter",
                custom_llm_provider="openai", deployment_id=shared,
            )
            for name in ("free", "orcarouter/free")
        ],
        cooldown_time=0,
    )
    ids = {
        d["model_name"]: d["model_info"]["id"] for d in client._router.get_model_list()
    }
    assert ids == {"free": shared, "orcarouter/free": shared}


def test_unpinned_deployments_keep_litellms_own_ids():
    pytest.importorskip("litellm")
    client = OrcaLiteLLMClient(
        [ProviderDeployment(
            model_name="gpt-4o-mini", litellm_model="openai/gpt-4o-mini", api_key="k",
            provider="openai",
        )],
        cooldown_time=0,
    )
    entry = client._router.get_model_list()[0]
    assert entry["model_info"]["id"]  # generated, not ours
    assert not entry["model_info"]["id"].startswith("hosted::")
