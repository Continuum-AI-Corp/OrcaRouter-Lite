"""`_settle_unmeasured_stream` only prices what nothing else measured."""

from __future__ import annotations

from types import SimpleNamespace

from app.routes.chat import _settle_unmeasured_stream


def _body(prompt: str):
    return SimpleNamespace(messages=[SimpleNamespace(content=prompt)])


def test_measured_usage_is_never_replaced_by_an_estimate():
    usage = {"prompt_tokens": 11, "completion_tokens": 22}
    got = _settle_unmeasured_stream(usage, 90_000, _body("x" * 400))
    assert got == usage


def test_nothing_delivered_stays_unbilled():
    # A failure before the first content chunk delivered no tokens; inventing a
    # prompt charge for it would repeat the over-charge this estimate replaces.
    assert _settle_unmeasured_stream({}, 0, _body("x" * 400)) == {}


def test_empty_client_bail_still_costs_the_prompt():
    # A disconnect is the caller's choice after the prompt went upstream, so an
    # empty delivery is priced from the prompt rather than settled at zero.
    assert _settle_unmeasured_stream({}, 0, _body("x" * 400), caller_bailed=True) == {
        "prompt_tokens": 100,
        "completion_tokens": 1,
    }


def test_estimate_prices_prompt_and_delivery_at_char_quarter():
    got = _settle_unmeasured_stream({}, 4_000, _body("y" * 400))
    assert got == {"prompt_tokens": 100, "completion_tokens": 1000}


def test_content_part_lists_count_their_text():
    body = SimpleNamespace(messages=[SimpleNamespace(
        content=[{"type": "text", "text": "z" * 800}, {"type": "image_url"}]
    )])
    got = _settle_unmeasured_stream({}, 400, body)
    assert got == {"prompt_tokens": 200, "completion_tokens": 100}
