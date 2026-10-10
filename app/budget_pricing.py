"""Pure pricing helpers for budgeted requests.

A budgeted key is charged for what the upstream delivered. Most of the time the
provider reports token usage and the charge is that measurement. When it does
not, the charge is estimated from the characters that actually reached the
client. Everything here is a pure function over plain dicts and strings, so it
has no database, no FastAPI, and no route state.
"""

from __future__ import annotations

# Crude character-to-token divisor, used only to price a delivery the provider
# did not measure.
CHARS_PER_TOKEN = 4

_COUNTABLE_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "input_tokens",
    "output_tokens",
)


def text_chars(content) -> int:
    """Character count of message content, for a str or a list of text parts.

    Anthropic-style content may be either a plain string or a list of parts,
    where each part may be a dict (`{"text": "..."}`) or a plain `str`. Both
    shapes are counted so a prompt prices the same characters the completion
    delivery path (`blocking_delivery_chars`) would count.
    """
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += len(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                total += len(part["text"])
        return total
    return 0


def countable_usage(usage) -> bool:
    """Whether a usage dict carries a measured token total.

    A truthy usage dict is not proof of measurement. Some upstreams report
    `{"total_tokens": 123}` and nothing else, and LiteLLM emits a frame of
    `{"prompt_tokens": 0, "completion_tokens": 0}` when the upstream reported
    nothing at all. Settling on either records a zero cost for a delivered
    completion, so only a countable key holding a positive number counts as a
    measurement — anything else is treated as no measurement at all.

    `bool` is rejected explicitly: `True` is an `int` in Python, and a flag that
    leaked into a token field is not a measurement.
    """
    if not isinstance(usage, dict) or not usage:
        return False
    return any(
        isinstance(value := usage.get(key), (int, float))
        and not isinstance(value, bool)
        and value > 0
        for key in _COUNTABLE_USAGE_KEYS
    )


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
                    if isinstance(part, str):
                        candidates.append(part)
                    elif isinstance(part, dict) and isinstance(part.get("text"), str):
                        candidates.append(part["text"])
            candidates.append(tool_call_text(message.get("tool_calls")))
        for value in candidates:
            if not value.strip():
                continue
            chars += len(value)
            has_content = True
    return has_content, chars
