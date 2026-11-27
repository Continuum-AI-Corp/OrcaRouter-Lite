"""Issue 9: kimi models think by default and then refuse a forced tool call
("tool_choice 'required' is incompatible with thinking enabled"). For that
deployment only, thinking is turned off when a tool call is forced."""

from __future__ import annotations

import pytest

from packages.litellm_adapter.client import adjust_for_forced_tools

TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {}}}}]


@pytest.mark.parametrize("choice", ["required", {"type": "function", "function": {"name": "f"}}])
@pytest.mark.parametrize("model", ["openai/kimi/kimi-k2.6", "moonshot/kimi-k2.6", "openai/kimi-k3.1-pro"])
def test_a_forced_tool_call_turns_kimi_thinking_off(model, choice):
    out = adjust_for_forced_tools({"model": model, "tools": TOOLS, "tool_choice": choice,
                                   "reasoning_effort": "medium", "extra_body": {"keep": 1}})
    assert out["extra_body"] == {"keep": 1, "thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in out


@pytest.mark.parametrize("kwargs", [
    {"model": "openai/kimi/kimi-k2.6", "tools": TOOLS, "tool_choice": "auto"},
    {"model": "openai/kimi/kimi-k2.6", "tools": TOOLS},
    {"model": "openai/qwen/qwen3.6-plus", "tools": TOOLS, "tool_choice": "required"},
    {"model": "anthropic/claude-sonnet-4.6", "tools": TOOLS, "tool_choice": {"type": "function", "function": {"name": "f"}}},
])
def test_everything_else_is_sent_as_asked(kwargs):
    assert adjust_for_forced_tools(kwargs) is None
