"""The reserve has to be an upper bound on what actually gets billed.

Come in under and the request walks past a cap the operator set in real
money, and by the time the real cost is logged the hold is already gone.
"""

import pytest

from app.routes.chat import (
    _estimate_reserve_microcents,
    _input_token_ceiling,
    _lookup_priced_model,
    _priced,
)
from app.schemas import ChatCompletionRequest

_VISION = [{"type": "image_url", "image_url": {"url": "https://x/y.jpg"}}]
_URL = "https://x/y.jpg"
_AUDIO = [{"type": "input_audio", "input_audio": {"data": "x" * 100, "format": "wav"}}]


def _reserve(content="hi", models=("gpt-4o-mini",), **kw) -> int:
    body = ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": content}], **kw
    )
    return _estimate_reserve_microcents(body, list(models))


def _ceiling(content="hi", **kw) -> int:
    body = ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": content}], **kw
    )
    return _input_token_ceiling(body)


def test_an_image_is_not_counted_as_its_own_url():
    """content is a list of parts once vision is involved.

    str() of that part is a fifteen character URL while the image itself
    bills around a thousand tokens, so counting characters reserved next
    to nothing against a real cost.
    """
    assert _reserve(content=_VISION, max_tokens=16) > 10 * _reserve(
        content=_URL, max_tokens=16
    )


def test_n_multiplies_the_output_side():
    """Each of the n completions is billed in full."""
    assert _reserve(n=4) > 3 * _reserve(n=1)


def test_a_cascade_reserves_the_dearest_candidate():
    """Auto-routing can land on a fallback, so price them all."""
    assert _reserve(models=("gpt-4o-mini", "gpt-4o")) == _reserve(models=("gpt-4o",))


def test_a_model_nobody_can_price_reserves_nothing():
    """Not the catalog, not litellm — and litellm is who reports the cost.

    If it has no price for the model it reports none, so there is no spend
    for the cap to be protecting against.
    """
    assert _reserve(models=("not-a-real-model",)) == 0


def test_a_model_the_catalog_dropped_still_reserves():
    """The catalog only keeps the providers i route to by name.

    litellm prices everything in its own cost table and bills from it, so
    a deployment pointed at a provider the catalog filtered out used to
    reserve nothing at all while the log recorded a real cost.
    """
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, _litellm_cost

    outside = [
        mid
        for mid, meta in _litellm_cost().items()
        if isinstance(meta, dict)
        and (meta.get("input_cost_per_token") or meta.get("output_cost_per_token"))
        and mid not in CATALOG_BY_ID
    ]
    if not outside:
        pytest.skip("this litellm build has no priced model outside the catalog")
    assert _reserve(models=(outside[0],)) > 0


def test_a_zero_priced_catalog_entry_is_not_treated_as_a_price():
    """Free tiers sit in the catalog at 0.0, which reserves nothing — but
    i have to read past them to litellm rather than stop at the first hit."""
    assert _priced("orcarouter/free") is None
    assert _lookup_priced_model("orcarouter/free") is not None


def test_an_unset_max_tokens_uses_the_models_own_ceiling():
    """gpt-4o answers with far more than the flat 8192 i used to assume."""
    ceiling = _priced("gpt-4o").max_output_tokens
    if not ceiling:
        pytest.skip("this litellm build publishes no output ceiling for gpt-4o")
    assert _reserve(models=("gpt-4o",), max_tokens=ceiling) == _reserve(models=("gpt-4o",))


def test_tools_are_billed_as_input():
    """A tool schema can dwarf the messages it sits next to."""
    tool = {"type": "function", "function": {"name": "search", "description": "x" * 4000}}
    assert _ceiling(tools=[tool]) > _ceiling() + 900


def test_tool_calls_in_the_transcript_are_billed_as_input():
    body = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": "x" * 4000},
                    }
                ],
            }
        ],
    )
    assert _input_token_ceiling(body) > 900


def test_non_ascii_text_is_not_counted_as_a_quarter_token():
    """//4 is the english average: chinese bills about one token a character."""
    assert _ceiling(content="啊" * 100) > 3 * _ceiling(content="a" * 100)


def test_audio_reserves_more_than_a_single_image():
    """Audio bills by duration, so a clip is dearer than one image."""
    assert _ceiling(content=_AUDIO) > _ceiling(content=_VISION)


def test_a_cache_write_is_reserved_at_the_dearest_input_rate():
    """Anthropic bills a cache write at 1.25x base input, a read at 0.1x."""
    price = _priced("gpt-4o-mini")
    body = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "a" * 40_000}],
        max_tokens=1,
    )
    flat = int(
        (
            _input_token_ceiling(body) * price.input_cost_per_token
            + price.output_cost_per_token
        )
        * 1_000_000
    )
    assert _estimate_reserve_microcents(body, ["gpt-4o-mini"]) > flat
