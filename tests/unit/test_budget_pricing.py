"""Unit tests for app.budget_pricing: estimating what an unmeasured delivery cost."""

import pytest

from app.budget_pricing import (
    blocking_delivery_chars,
    chars_to_tokens,
    countable_usage,
    estimate_usage,
    message_chars,
    text_chars,
    tool_call_text,
)


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens": 5}, True),
        ({"completion_tokens": 1}, True),
        ({"input_tokens": 5}, True),
        ({"output_tokens": 5}, True),
        # A zero on one side is still a measurement when the other side counts.
        ({"prompt_tokens": 0, "completion_tokens": 7}, True),
        ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, False),
        ({"total_tokens": 123}, False),
        ({"prompt_tokens": None}, False),
        ({"prompt_tokens": "12"}, False),
        ({"prompt_tokens": True}, False),
        ({"prompt_tokens": -5}, False),
        ({}, False),
        (None, False),
        ("not a dict", False),
    ],
)
def test_countable_usage_requires_a_positive_measurement(usage, expected):
    assert countable_usage(usage) is expected


def test_countable_usage_rejects_a_zero_placeholder_frame():
    """The frame LiteLLM emits when the upstream reported nothing.

    A delivered completion settled on this records a zero cost, which is the
    bypass the guard exists to prevent.
    """
    assert countable_usage({"prompt_tokens": 0, "completion_tokens": 0}) is False
    assert (
        countable_usage(
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        is False
    )


@pytest.mark.parametrize(
    ("chars", "expected"),
    [(-5, 0), (0, 0), (1, 1), (3, 1), (4, 1), (8, 2), (9, 2)],
)
def test_chars_to_tokens_floors_nonzero_at_one(chars, expected):
    assert chars_to_tokens(chars) == expected


def test_zero_characters_is_zero_tokens_not_one():
    assert estimate_usage(0, 0) == {"prompt_tokens": 0, "completion_tokens": 0}


def test_estimate_usage_prices_both_sides_from_characters():
    assert estimate_usage(400, 40) == {"prompt_tokens": 100, "completion_tokens": 10}


def test_text_chars_across_str_and_content_parts():
    assert text_chars("hello") == 5
    assert text_chars([{"type": "text", "text": "ab"}, {"type": "image_url"}]) == 2
    assert text_chars(None) == 0


def test_text_chars_counts_bare_string_parts():
    """Anthropic-style content may be a list of plain strings, not just dicts.

    Mirrors `blocking_delivery_chars`, which accepts a bare `str` part: a
    prompt and a completion carrying the same bare-string content must price
    the same characters rather than the prompt pricing at zero.
    """
    assert text_chars(["hello", "world"]) == 10
    assert text_chars([{"text": "ab"}, "cd", {"no": "text"}, 42]) == 4


def test_tool_call_text_counts_names_and_string_arguments():
    calls = [
        {"function": {"name": "search", "arguments": '{"q":"x"}'}},
        {"function": {"name": "fetch", "arguments": {"url": "obj-not-counted"}}},
    ]
    assert tool_call_text(calls) == 'search{"q":"x"}fetch'


def test_tool_call_text_ignores_malformed_entries():
    assert tool_call_text(None) == ""
    assert tool_call_text(["oops", {"function": "nope"}]) == ""


def test_blocking_delivery_counts_content_and_tool_calls():
    response = {
        "choices": [
            {
                "message": {
                    "content": "hi",
                    "tool_calls": [{"function": {"name": "f", "arguments": "{}"}}],
                }
            }
        ]
    }
    assert blocking_delivery_chars(response) == (True, len("hi") + len("f{}"))


def test_whitespace_only_is_not_a_delivery_and_adds_no_characters():
    response = {"choices": [{"message": {"content": "   \n"}}]}
    assert blocking_delivery_chars(response) == (False, 0)


def test_blocking_delivery_reads_legacy_text_and_part_lists():
    response = {
        "choices": [
            {"text": "abc"},
            {"message": {"content": [{"text": "de"}, "f"]}},
        ]
    }
    assert blocking_delivery_chars(response) == (True, 6)


def test_blocking_delivery_empty_or_malformed_response():
    assert blocking_delivery_chars({}) == (False, 0)
    assert blocking_delivery_chars({"choices": "nope"}) == (False, 0)


def test_message_chars_counts_tool_calls_on_an_assistant_turn():
    """An assistant turn with content None and only tool_calls must not price at zero."""
    calls = [{"function": {"name": "search", "arguments": '{"q":"x"}'}}]
    assert message_chars(None, calls) == len('search{"q":"x"}')
    assert message_chars("hi", calls) == len("hi") + len('search{"q":"x"}')
    assert message_chars("hi") == 2


def test_prompt_and_completion_price_the_same_tool_call_characters():
    """A tool-call turn in the prompt and the same turn delivered must agree."""
    calls = [{"function": {"name": "search", "arguments": '{"q":"x"}'}}]
    prompt_side = message_chars(None, calls)
    _, delivered_side = blocking_delivery_chars(
        {"choices": [{"message": {"content": None, "tool_calls": calls}}]}
    )
    assert prompt_side == delivered_side > 0


def test_prompt_only_frame_is_not_countable_when_content_was_delivered():
    """A prompt-measured frame with a zero completion would settle a delivered completion at zero."""
    frame = {"prompt_tokens": 100, "completion_tokens": 0}
    assert countable_usage(frame) is True
    assert countable_usage(frame, delivered=True) is False


def test_delivered_frame_with_positive_completion_is_countable():
    assert countable_usage({"prompt_tokens": 100, "completion_tokens": 7}, delivered=True) is True
    assert countable_usage({"output_tokens": 7}, delivered=True) is True


def test_anthropic_tool_use_part_is_counted_as_delivered_content():
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "search", "input": '{"q":"x"}'},
                    ]
                }
            }
        ]
    }
    assert blocking_delivery_chars(response) == (True, len("search") + len('{"q":"x"}'))


def test_tool_use_part_with_object_input_counts_only_its_name():
    part = {"type": "tool_use", "name": "search", "input": {"q": "x"}}
    assert text_chars([part]) == len("search")


def test_tool_use_only_completion_is_a_delivery_not_zero():
    response = {"choices": [{"message": {"content": [{"type": "tool_use", "name": "f"}]}}]}
    assert blocking_delivery_chars(response) == (True, 1)
