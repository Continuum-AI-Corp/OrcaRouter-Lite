"""The "local_first" strategy at the ranking layer (P2 · D1, H6).

A request that fits a local model (no images unless it has vision, tools
only if it supports them, a prompt within 80% of its context) goes to it
first, and the rest of the ranking (free hosted models first, then the
cheapest cloud models) follows as fallbacks. Other strategies never pick a
local model unless the user named it in preferred models.
"""

from __future__ import annotations

from app.auto_routing import choose_auto_model
from packages.litellm_adapter.catalog import CATALOG, CatalogModel

CODER = CatalogModel("ollama/qwen3-coder:30b", "local", "", True, False, True, 0.0, 0.0)
LLAVA = CatalogModel("ollama/llava:7b", "local", "", False, True, True, 0.0, 0.0)
LOCAL = [CODER, LLAVA]
CLOUD = {"gpt-4o-mini", "gpt-4.1", "gpt-4o"}
FREE = {"z-ai/glm-5.3-flash-free", "orcarouter/free"}
DEPLOYABLE = {*CLOUD, *FREE, CODER.id, LLAVA.id}
LIMITS = {CODER.id: 26_214, LLAVA.id: 3_276}


def _rank(strategy, needs=(), prompt_tokens=100, preferred=None):
    ids, _ = choose_auto_model(needs=set(needs), deployable=DEPLOYABLE, candidates=[*LOCAL, *CATALOG],
                               strategy=strategy, preferred_models=preferred, context_limits=LIMITS,
                               prompt_tokens=prompt_tokens, allow_free_hosted=True)
    return ids


def test_a_short_plain_request_goes_local_first_then_free_then_cheapest_cloud():
    ids = _rank("local_first")
    assert ids[:2] == [LLAVA.id, CODER.id]
    assert set(ids[2:4]) == FREE
    assert ids[4] == "gpt-4o-mini"


def test_tools_go_to_a_local_model_that_supports_them():
    assert _rank("local_first", needs={"tools"})[0] == CODER.id
    assert LLAVA.id not in _rank("local_first", needs={"tools"})


def test_images_go_to_a_local_model_with_vision_or_the_cloud():
    ids = _rank("local_first", needs={"vision"})
    assert ids[0] == LLAVA.id and CODER.id not in ids
    ids = _rank("local_first", needs={"vision"}, prompt_tokens=10_000)  # too long for llava's context
    assert ids[0] in CLOUD


def test_a_long_prompt_goes_to_the_cloud():
    ids = _rank("local_first", prompt_tokens=30_000)
    assert not {CODER.id, LLAVA.id} & set(ids)


def test_other_strategies_never_pick_local_models():
    for strategy in ("cheapest", "balanced", "fastest", "quality", None):
        assert not {CODER.id, LLAVA.id} & set(_rank(strategy)), strategy


def test_unless_the_user_prefers_one():
    assert _rank("cheapest", preferred=[CODER.id]) == [CODER.id]
