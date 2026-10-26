"""Native response usage must preserve the inclusive LiteLLM cache breakdown."""

import json

import pytest

from app.protocols.anthropic import stream_events, to_anthropic_response
from app.protocols.gemini import stream_chunks, to_gemini_response


async def _frames(usage):
    yield {"choices": [], "usage": usage}


@pytest.mark.parametrize("details,cache", [
    ({"cached_tokens": 90, "cache_write_tokens": 10},
     {"cache_read_input_tokens": 90, "cache_creation_input_tokens": 10}),
    ({"cached_tokens": 90, "cache_creation_tokens": 10},
     {"cache_read_input_tokens": 90, "cache_creation_input_tokens": 10}),
    ({"cached_tokens": 0}, {"cache_read_input_tokens": 0}),
    ({"cache_write_tokens": 0}, {"cache_creation_input_tokens": 0}),
    ({"cached_tokens": None, "cache_creation_tokens": None}, {}),
    ({}, {}),
])
async def test_blocking_and_terminal_stream_preserve_known_cache_components(details, cache):
    usage = {"prompt_tokens": 105, "completion_tokens": 2, "total_tokens": 107,
             "prompt_tokens_details": details}
    expected = {"input_tokens": 105 - sum(cache.values()), "output_tokens": 2, **cache}
    assert to_anthropic_response({"usage": usage})["usage"] == expected
    events = [json.loads(event.split("data: ")[1]) async for event in stream_events(_frames(usage))]
    assert events[-2]["usage"] == expected

    gemini = {"promptTokenCount": 105, "candidatesTokenCount": 2, "totalTokenCount": 107}
    if "cache_read_input_tokens" in cache:
        gemini["cachedContentTokenCount"] = cache["cache_read_input_tokens"]
    assert to_gemini_response({"usage": usage})["usageMetadata"] == gemini
    chunks = [chunk async for chunk in stream_chunks(_frames(usage))]
    assert chunks[-1]["usageMetadata"] == gemini


@pytest.mark.parametrize("details", [
    {"cached_tokens": -1}, {"cached_tokens": 106},
    {"cached_tokens": 100, "cache_write_tokens": 6},
    {"cached_tokens": True}, {"cached_tokens": "90"},
    {"cached_tokens": 90.5},
    {"cache_write_tokens": 10, "cache_creation_tokens": 11},
])
async def test_inconsistent_cache_breakdown_is_omitted_without_negative_input(details):
    usage = {"prompt_tokens": 105, "completion_tokens": 2, "prompt_tokens_details": details}
    assert to_anthropic_response({"usage": usage})["usage"] == {"input_tokens": 105, "output_tokens": 2}
    assert "cachedContentTokenCount" not in to_gemini_response({"usage": usage})["usageMetadata"]
    events = [json.loads(event.split("data: ")[1]) async for event in stream_events(_frames(usage))]
    assert events[-2]["usage"] == {"input_tokens": 105, "output_tokens": 2}


async def test_known_zero_ordinary_input_replaces_stream_estimate():
    usage = {"prompt_tokens": 90, "completion_tokens": 2,
             "prompt_tokens_details": {"cached_tokens": 90}}
    events = [json.loads(event.split("data: ")[1]) async for event in stream_events(_frames(usage), input_tokens=37)]
    assert events[0]["message"]["usage"]["input_tokens"] == 37
    assert events[-2]["usage"] == {"input_tokens": 0, "output_tokens": 2, "cache_read_input_tokens": 90}


def test_real_anthropic_normalizer_aliases_are_not_counted_twice():
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    usage = AnthropicConfig().calculate_usage({
        "input_tokens": 50, "output_tokens": 10,
        "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 1000,
    }, reasoning_content=None).model_dump(exclude_none=True)
    assert usage["prompt_tokens"] == 10050
    assert to_anthropic_response({"usage": usage})["usage"] == {
        "input_tokens": 50, "output_tokens": 10,
        "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 1000,
    }


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": 10, "cache_read_input_tokens": 7},
    {"prompt_tokens": 10, "cache_creation_input_tokens": 7},
])
def test_legacy_top_level_litellm_components(usage):
    expected = {"input_tokens": 3, "output_tokens": 0}
    expected.update({key: value for key, value in usage.items() if key.startswith("cache_")})
    assert to_anthropic_response({"usage": usage})["usage"] == expected


@pytest.mark.parametrize("prompt", [-1, None, "10"])
def test_unusable_prompt_count_cannot_establish_a_cache_breakdown(prompt):
    usage = {"prompt_tokens": prompt, "completion_tokens": 2,
             "prompt_tokens_details": {"cached_tokens": 1}}
    assert to_anthropic_response({"usage": usage})["usage"] == {"input_tokens": 0, "output_tokens": 2}
    assert to_gemini_response({"usage": usage})["usageMetadata"] == {
        "promptTokenCount": 0, "candidatesTokenCount": 2, "totalTokenCount": 2,
    }


def test_real_gemini_normalizer_preserves_inclusive_cached_count():
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import VertexGeminiConfig

    raw = {"promptTokenCount": 100, "candidatesTokenCount": 2,
           "totalTokenCount": 102, "cachedContentTokenCount": 90}
    usage = VertexGeminiConfig.calculate_usage({"usageMetadata": raw}).model_dump(exclude_none=True)
    assert to_gemini_response({"usage": usage})["usageMetadata"] == raw
