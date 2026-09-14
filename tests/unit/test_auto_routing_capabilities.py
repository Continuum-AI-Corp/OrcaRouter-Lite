"""Edge-case coverage for required_capabilities.

The auto-routing layer decides which catalog models are eligible based
on the capabilities the request needs (tools, vision, json_mode). A
model that doesn"t support a needed capability is filtered out of the
fallback chain.

These tests guard the tool_choice + tools-payload interaction: a string
tool_choice without a tools payload should NOT require a tool-capable
model (OpenAI silently ignores tool_choice when no tools are defined).
A dict tool_choice always requires tools regardless of the payload.
"""

from __future__ import annotations

from app.auto_routing import required_capabilities


class TestToolChoiceWithoutTools:
    def test_string_tool_choice_no_tools_payload(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": "auto",
        }
        needs = required_capabilities(body)
        assert "tools" not in needs

    def test_string_tool_choice_required_no_tools_payload(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": "required",
        }
        needs = required_capabilities(body)
        # "required" without tools is still a no-op per OpenAI spec
        assert "tools" not in needs

    def test_string_tool_choice_with_tools_payload(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "foo"}}],
            "tool_choice": "auto",
        }
        needs = required_capabilities(body)
        assert "tools" in needs

    def test_dict_tool_choice_always_requires_tools(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "function", "function": {"name": "foo"}},
        }
        needs = required_capabilities(body)
        assert "tools" in needs

    def test_tool_choice_none_no_tools(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": "none",
        }
        needs = required_capabilities(body)
        assert "tools" not in needs

    def test_tool_choice_empty_string_no_tools(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": "",
        }
        needs = required_capabilities(body)
        assert "tools" not in needs

    def test_tools_payload_only(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "foo"}}],
        }
        needs = required_capabilities(body)
        assert "tools" in needs

    def test_no_tools_no_choice(self):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        }
        needs = required_capabilities(body)
        assert "tools" not in needs
