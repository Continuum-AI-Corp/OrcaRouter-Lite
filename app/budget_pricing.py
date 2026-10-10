"""Pure pricing helpers for budgeted requests.

A budgeted key is charged for what the upstream delivered. Most of the time the
provider reports token usage and the charge is that measurement. When it does
not, the charge is estimated from the characters that actually reached the
client. Everything here is a pure function over plain dicts and strings, so it
has no database, no FastAPI, and no route state.
"""

from __future__ import annotations

import json

# Crude character-to-token divisor, used only to price a delivery the provider
# did not measure.
CHARS_PER_TOKEN = 4

_PROMPT_USAGE_KEYS = ("prompt_tokens", "input_tokens")
_COMPLETION_USAGE_KEYS = ("completion_tokens", "output_tokens")
_COUNTABLE_USAGE_KEYS = _PROMPT_USAGE_KEYS + _COMPLETION_USAGE_KEYS

# Stands in for a delivered part with no character count (an image, an audio
# clip). One character: enough to be a delivery, floored to one token.
_OPAQUE_PART_MARKER = "?"


def _part_texts(part) -> list[str]:
    """The character-bearing strings one content part carries.

    A part is a bare string, a `{"text": ...}` dict, an Anthropic
    `{"type": "tool_use", "name": ..., "input": ...}` block, or some other
    non-text part (an image, an audio clip, a b64 payload).

    A tool_use block is billed as its name plus its input serialized the same
    way the translators serialize it (`json.dumps(input or {})`), so an object
    input is counted in full, not dropped. A non-text part has no honest
    character count, but it was delivered, so it counts as one character: that
    keeps it from settling at zero while `chars_to_tokens` floors it to a token.
    """
    if isinstance(part, str):
        return [part]
    if not isinstance(part, dict):
        return []
    if part.get("type") == "tool_use":
        texts = [part["name"]] if isinstance(part.get("name"), str) else []
        raw_input = part.get("input")
        if isinstance(raw_input, str):
            texts.append(raw_input)
        else:
            texts.append(json.dumps(raw_input or {}, separators=(", ", ": ")))
        return texts
    if isinstance(part.get("text"), str):
        return [part["text"]]
    if part.get("type") == "tool_result":
        # A tool result's billable text is its `content`: a string, or a list of
        # parts in the same shape a message's content takes. Count that text,
        # not a single marker character for the whole tool output.
        return _content_texts(part.get("content"))
    if part.get("type") in (None, "text"):
        return []
    # A non-text part (image, audio, ...) has no honest character count, but it
    # was sent or delivered and is billed. Count it as one character, so it
    # floors to a token and never prices at zero.
    return [_OPAQUE_PART_MARKER]


def _content_texts(content) -> list[str]:
    """Text strings of a content value: a bare string, or a list of parts."""
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            texts.extend(_part_texts(part))
        return texts
    return []


def text_chars(content) -> int:
    """Character count of message content, for a str or a list of content parts.

    Counts every character of the text it is given, whitespace included. The
    prompt is billed for all of it. This is deliberately not `blocking_delivery_chars`'
    rule: that function drops whitespace-only values from a completion, which is
    right for deciding whether something was delivered, but the streaming path
    also prices each delta through here, and a whitespace-only delta is real
    output that must not be dropped.
    """
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(text) for part in content for text in _part_texts(part))
    return 0


def message_chars(content, tool_calls=None) -> int:
    """Character count of one prompt message: its content plus its tool calls.

    An assistant turn that only called tools has `content` of None and its
    billable text in `tool_calls`; pricing content alone would charge it zero.
    """
    return text_chars(content) + len(tool_call_text(tool_calls))


def _positive_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def countable_usage(usage, *, delivered: bool = False) -> bool:
    """Whether a usage dict carries a measured token total.

    A truthy usage dict is not proof of measurement. Some upstreams report
    `{"total_tokens": 123}` and nothing else, and LiteLLM emits a frame of
    `{"prompt_tokens": 0, "completion_tokens": 0}` when the upstream reported
    nothing at all. Settling on either records a zero cost for a delivered
    completion, so only a countable key holding a positive number counts as a
    measurement.

    When `delivered` is True the frame must also carry a positive completion-side
    count. A prompt-only frame such as `{"prompt_tokens": 100,
    "completion_tokens": 0}` would otherwise settle a delivered completion at
    zero. A delivered completion that really cost tokens always reports them.

    `bool` is rejected explicitly: `True` is an `int` in Python, and a flag that
    leaked into a token field is not a measurement.
    """
    if not isinstance(usage, dict) or not usage:
        return False
    if delivered:
        return any(_positive_number(usage.get(key)) for key in _COMPLETION_USAGE_KEYS)
    return any(_positive_number(usage.get(key)) for key in _COUNTABLE_USAGE_KEYS)


def chars_to_tokens(chars: int) -> int:
    """Characters to tokens. Zero characters is zero tokens.

    A non-zero count floors at one, so a prompt that was really sent is never
    recorded as empty just because it is shorter than one token's worth of text.
    """
    if chars <= 0:
        return 0
    return max(1, chars // CHARS_PER_TOKEN)


def estimate_usage(prompt_chars: int, completion_chars: int) -> dict:
    """Token counts priced from characters, for a delivery never measured."""
    return {
        "prompt_tokens": chars_to_tokens(prompt_chars),
        "completion_tokens": chars_to_tokens(completion_chars),
    }


def tool_call_text(tool_calls) -> str:
    """Text a message's tool calls carry: function names and string arguments.

    A tool call is delivered content the upstream bills for. Arguments sent as
    an object rather than a string have no honest character count, so they
    contribute nothing.
    """
    if not isinstance(tool_calls, list):
        return ""
    parts: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function")
        if not isinstance(fn, dict):
            continue
        for key in ("name", "arguments"):
            value = fn.get(key)
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def blocking_delivery_chars(response: dict) -> tuple[bool, int]:
    """Whether a blocking completion delivered content, and how many characters.

    Whitespace-only values are not a delivery, and they add nothing to the
    count either: the flag and the count answer the same question and must agree.
    """
    choices = response.get("choices")
    if not isinstance(choices, list):
        return False, 0
    has_content = False
    chars = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        candidates: list[str] = []
        text = choice.get("text")
        if isinstance(text, str):
            candidates.append(text)
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                candidates.append(content)
            elif isinstance(content, list):
                for part in content:
                    candidates.extend(_part_texts(part))
            # A refusal is the completion itself when content is None: it
            # reached the client, so it is billed output.
            refusal = message.get("refusal")
            if isinstance(refusal, str):
                candidates.append(refusal)
            candidates.append(tool_call_text(message.get("tool_calls")))
        for value in candidates:
            if not value.strip():
                continue
            chars += len(value)
            has_content = True
    return has_content, chars
