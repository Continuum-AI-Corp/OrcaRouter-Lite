"""Unit tests for app.budget_pricing: estimating what an unmeasured delivery cost."""

import pytest

from app.budget_pricing import (
    blocking_delivery_chars,
    chars_to_tokens,
    countable_usage,
    estimate_usage,
    text_chars,
    tool_call_text,
)


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens": 0}, True),
        ({"completion_tokens": 0}, True),
        ({"input_tokens": 5}, True),
        ({"output_tokens": 5}, True),
        ({"total_tokens": 123}, False),
        ({"prompt_tokens": None}, False),
        ({}, False),
        (None, False),
        ("not a dict", False),
    ],
)
def test_countable_usage_requires_a_countable_key(usage, expected):
    assert countable_usage(usage) is expected


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
