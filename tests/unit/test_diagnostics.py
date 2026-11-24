"""D8: the diagnostics report leaves out keys, prompts and the home path."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.desktop import diagnostics as dg

HOME = Path("/home/alice")


@pytest.mark.parametrize("secret,shown", [
    ("sk-orca-AbCdEf0123456789xyz3f2", "sk-…3f2"),
    ("sk-ant-api03-AbCdEf0123456789-xyz", "sk-…xyz"),
    ("sk-proj-0123456789abcdefABCDEF", "sk-…DEF"),
    ("AIzaSyA0123456789abcdefghijklmnop", "AIza…nop"),
    ("xai-0123456789abcdefghijk", "xai-…ijk"),
    ("gsk_0123456789abcdefghijk", "gsk_…ijk"),
    ("aa-0123456789abcdef3f2", "aa-…3f2"),
])
def test_key_shaped_strings_are_masked(secret, shown):
    out = dg.redact(f"auth failed for {secret} at 12:00", home=HOME)
    assert secret not in out and shown in out


def test_bearer_tokens_and_key_fields_are_masked():
    line = 'headers={"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz012345"} api_key=plainsecretvalue99'
    out = dg.redact(line, home=HOME)
    assert "abcdefghijklmnopqrstuvwxyz012345" not in out
    assert "plainsecretvalue99" not in out


def test_home_directory_becomes_tilde():
    out = dg.redact("reading /home/alice/.claude/settings.json and /Users/bob/x and C:\\Users\\carol\\y", home=HOME)
    assert out.startswith("reading ~/.claude/settings.json")
    assert "alice" not in out and "bob" not in out and "carol" not in out


def test_prompt_text_is_left_out():
    line = ('chat_request messages=[{"role": "user", "content": "tell me about pelicans"}] '
            'prompt="secret plans" input=\'more words\'')
    out = dg.redact(line, home=HOME)
    for words in ("pelicans", "secret plans", "more words"):
        assert words not in out


def test_long_lines_are_cut():
    assert len(dg.redact("x" * 5000, home=HOME)) <= dg.MAX_LINE + 1


def test_log_tail_reads_the_last_lines(tmp_path):
    log = tmp_path / "engine.log"
    log.write_text("".join(f"line {i}\n" for i in range(100)))
    assert dg.log_tail(log, 40) == [f"line {i}" for i in range(60, 100)]
    assert dg.log_tail(tmp_path / "missing.log", 40) == []


def test_report_layout():
    text = dg.build(
        version="0.2.0",
        engine="running",
        agents=[{"id": "claude-code", "state": "connected", "test": {"ok": True, "at": "14:30", "error": None}},
                {"id": "gemini-cli", "state": "connected",
                 "test": {"ok": False, "at": "14:31", "error": "Google Gemini rejected the key (401)."}},
                {"id": "codex", "state": "changed", "test": None}],
        providers=[{"provider": "openai", "state": "healthy", "source": "db"}],
        routing="balanced · OrcaRouter: free models only",
        local=["Ollama 127.0.0.1:11434 running, 2 models"],
        log_lines=["a line with sk-orca-AbCdEf0123456789xyz3f2"],
        home=HOME,
    )
    assert text.startswith("OrcaRouter Lite 0.2.0")
    assert "claude-code" in text and "test ok 14:30" in text
    assert "test failed: Google Gemini rejected the key (401)." in text
    assert "codex" in text and "changed" in text
    assert "openai healthy" in text
    assert "Last 1 engine log lines (keys masked)" in text or "engine log" in text
    assert "sk-orca-AbCdEf" not in text


def test_prompt_text_after_a_bracket_inside_a_message_is_left_out():
    line = "request body messages=[{'role': 'user', 'content': 'see a[0] then the secret plan'}] model=gpt-4o"
    out = dg.redact(line, home=HOME)
    assert "secret plan" not in out


def test_a_line_that_continues_a_message_is_left_out():
    # A prompt printed over several lines: the continuation lines carry no
    # field name, but they still hold message structure.
    out = dg.redact("    {'role': 'user', 'content': 'the merger closes friday'},", home=HOME)
    assert "merger" not in out


def test_windows_profiles_in_any_case_and_with_spaces_become_tilde():
    out = dg.redact(r"opened c:\users\bob\x and C:\Users\John Smith\.claude\settings.json", home=HOME)
    assert "bob" not in out and "John" not in out and "Smith" not in out


def test_a_bare_key_parameter_in_a_url_is_masked():
    secret = "AbCdEf0123456789AbCdEf0123456789"  # unprefixed, 32 chars
    out = dg.redact(f"GET https://api.example.com/v1/models?key={secret}", home=HOME)
    assert secret not in out
