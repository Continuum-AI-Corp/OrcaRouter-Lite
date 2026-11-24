"""H0 at the ranking layer: OrcaRouter's free models are real, zero-priced
models auto may pick (unpriced litellm rows still may not), and in the
desktop app's "free" mode they rank first, with own-key models after them
as fallbacks. A paid hosted deployment is never built in that mode."""

from __future__ import annotations

from app.auto_routing import choose_auto_model
from packages.litellm_adapter.catalog import CATALOG, CatalogModel
from packages.litellm_adapter.hosted_catalog import FREE_HOSTED_MODELS

FREE = list(FREE_HOSTED_MODELS)


def test_the_free_models_are_the_four_zero_priced_hosted_ones():
    assert FREE == ["deepseek/deepseek-v4-pro-free", "deepseek/deepseek-v4-flash-free",
                    "qwen/qwen3.8-27b-free", "orcarouter/free"]


def test_auto_may_pick_free_models_but_not_unpriced_rows():
    unpriced = CatalogModel("mystery-model", "openai", "openai/", True, False, True, 0.0, 0.0)
    ids, _ = choose_auto_model(needs=set(), deployable={*FREE, "mystery-model"}, candidates=[*CATALOG, unpriced],
                               strategy="cheapest", allow_free_hosted=True)
    assert set(ids) == set(FREE)


def test_free_first_puts_free_models_before_own_keys_under_any_strategy():
    deployable = {*FREE, "gpt-4o-mini", "gpt-4.1"}
    for strategy in ("cheapest", "balanced", "quality", "fastest"):
        ids, scoring = choose_auto_model(
            needs=set(), deployable=deployable, candidates=CATALOG, strategy=strategy, free_first=True,
            quality_scores={"gpt-4o-mini": 40.0, "gpt-4.1": 50.0},
            tps_scores={"gpt-4o-mini": 90.0, "gpt-4.1": 80.0}, ttft_scores={"gpt-4o-mini": 0.4, "gpt-4.1": 0.5},
        )
        assert ids[:4] == FREE, strategy
        assert set(ids[4:]) <= {"gpt-4o-mini", "gpt-4.1"} and ids[4:], strategy
        assert set(scoring) == set(ids)


def test_without_free_first_free_models_compete_on_price():
    ids, _ = choose_auto_model(needs=set(), deployable={*FREE, "gpt-4o-mini"}, candidates=CATALOG,
                               strategy="cheapest", allow_free_hosted=True)
    assert set(ids[:4]) == set(FREE)  # $0 is the cheapest there is


def test_a_server_never_auto_picks_zero_priced_free_models():
    # Outside the desktop app the engine keeps its old rule: zero-priced
    # rows are never auto-picked, so a server's routing doesn't change.
    ids, _ = choose_auto_model(needs=set(), deployable={*FREE, "gpt-4o-mini"}, candidates=CATALOG,
                               strategy="cheapest")
    assert ids == ["gpt-4o-mini"]


def test_free_models_cannot_take_images():
    ids, _ = choose_auto_model(needs={"vision"}, deployable=set(FREE), candidates=CATALOG, strategy="cheapest",
                               free_first=True)
    assert ids == []


def test_a_prompt_beyond_a_models_context_rules_it_out():
    deployable = {*FREE, "gpt-4.1"}
    limits = {m: 100_000 for m in FREE}
    ids, _ = choose_auto_model(needs=set(), deployable=deployable, candidates=CATALOG, strategy="cheapest",
                               free_first=True, context_limits=limits, prompt_tokens=150_000)
    assert ids == ["gpt-4.1"]
    ids, _ = choose_auto_model(needs=set(), deployable=deployable, candidates=CATALOG, strategy="cheapest",
                               free_first=True, context_limits=limits, prompt_tokens=90_000)
    assert ids[0] == FREE[0]


def test_free_mode_builds_only_free_hosted_deployments(monkeypatch):
    from app.config import Settings
    from app.router_cache import build_deployments

    s = Settings(_env_file=None, orcarouter_api_key="sk-orca-x")
    free = build_deployments(env_keys={"openai": "sk-o"}, db_keys=[], settings=s, hosted_models="free")
    hosted_names = {d.model_name for d in free if d.provider == "orcarouter"}
    assert set(FREE) <= hosted_names
    assert not hosted_names - set(FREE) - {"deepseek-v4-pro-free", "deepseek-v4-flash-free", "qwen3.8-27b-free",
                                           "free"}
    assert any(d.provider == "openai" for d in free)  # own keys unaffected
    everything = build_deployments(env_keys={}, db_keys=[], settings=s, hosted_models="all")
    assert "claude-sonnet-4.6" in {d.model_name for d in everything}


def test_paid_orcarouter_models_come_after_every_own_key_model():
    # With paid models on, OrcaRouter is the backup: a cheap paid hosted
    # model mustn't jump ahead of the user's own keys.
    paid = {"kimi-k2.6", "glm-5"} & {m.id for m in CATALOG} or {"kimi-k2.6"}
    own = {"gpt-4o-mini", "gpt-4.1"}
    ids, _ = choose_auto_model(needs=set(), deployable={*FREE, *own, *paid}, candidates=CATALOG,
                               strategy="cheapest", free_first=True, hosted_last=paid)
    assert ids[:4] == FREE
    rest = ids[4:]
    assert set(rest[: len(own)]) == own
    assert set(rest[len(own):]) <= paid and rest[len(own):]


def test_one_paid_orcarouter_model_stays_in_reach_when_own_keys_fill_the_list():
    own = {"gpt-4o-mini", "gpt-4.1", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano", "o3-mini"} & {m.id for m in CATALOG}
    ids, _ = choose_auto_model(needs=set(), deployable={*own, "kimi-k2.6"}, candidates=CATALOG,
                               strategy="cheapest", hosted_last={"kimi-k2.6"})
    assert len(ids) == 5 and ids[-1] == "kimi-k2.6"
