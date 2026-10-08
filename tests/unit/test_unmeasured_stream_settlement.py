"""Delivery estimates only price what nothing else measured."""

from __future__ import annotations

from types import SimpleNamespace

from app.routes.chat import _countable_usage, _estimate_usage, _text_chars


def _body(prompt: str):
    return SimpleNamespace(messages=[SimpleNamespace(content=prompt)])


def test_measured_usage_is_never_replaced_by_an_estimate():
    assert _countable_usage({"prompt_tokens": 11, "completion_tokens": 22})
    assert _countable_usage({"input_tokens": 3, "output_tokens": 4})


def test_nothing_delivered_stays_unbilled():
    # A failure before the first content chunk delivered no tokens; this is the
    # input the table treats as known-zero rather than fail-closed.
    assert not _countable_usage({})
    assert not _countable_usage({"total_tokens": 123})


def test_empty_client_bail_still_costs_the_prompt():
    # Character math behind the prompt-only estimate for a disconnect before
    # the first byte.
    assert _estimate_usage(400, 0) == {"prompt_tokens": 100, "completion_tokens": 1}


def test_estimate_prices_prompt_and_delivery_at_char_quarter():
    got = _estimate_usage(400, 4_000)
    assert got == {"prompt_tokens": 100, "completion_tokens": 1000}


def test_content_part_lists_count_their_text():
    content = [{"type": "text", "text": "z" * 800}, {"type": "image_url"}]
    assert _text_chars(content) == 800
    assert _text_chars("plain") == 5
    assert _text_chars(None) == 0
