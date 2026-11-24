"""Desktop agent connectors: detect, connect and disconnect coding agents.

The desktop app points coding agents (Claude Code, Aider, ...) at the local
Lite engine by editing their config files. The hard requirement is that a
disconnect puts the user's config back exactly as it was, and that a
connect never destroys settings it does not own.
"""

from __future__ import annotations

import json
import os
import stat

import pytest
import yaml

from packages.desktop import agents as ag

BASE = "http://127.0.0.1:8765"
KEY = "sk-orca-0123456789abcdef0123456789abcdef"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def _no_binaries(_name: str):
    return None


def _status(home, state_dir, agent_id, which=_no_binaries):
    found = [a for a in ag.detect_agents(home=home, state_dir=state_dir, which=which) if a.id == agent_id]
    assert len(found) == 1
    return found[0]


def _claude_settings(home):
    return home / ".claude" / "settings.json"


# ── detection ────────────────────────────────────────────────────────────


def test_claude_code_detected_when_config_dir_exists(home, state_dir):
    (home / ".claude").mkdir()
    s = _status(home, state_dir, "claude-code")
    assert s.installed is True
    assert s.setup == "auto"
    assert s.connected is False


def test_claude_code_not_installed_without_config_dir_or_binary(home, state_dir):
    assert _status(home, state_dir, "claude-code").installed is False


def test_claude_code_detected_from_binary_on_path(home, state_dir):
    s = _status(home, state_dir, "claude-code", which=lambda n: "/usr/local/bin/claude" if n == "claude" else None)
    assert s.installed is True


def test_codex_is_detected_and_connects_automatically(home, state_dir):
    (home / ".codex").mkdir()
    s = _status(home, state_dir, "codex")
    assert s.installed is True
    assert s.setup == "auto"


def test_cursor_needs_manual_setup(home, state_dir):
    s = _status(home, state_dir, "cursor", which=lambda n: "/usr/bin/cursor" if n == "cursor" else None)
    assert s.installed is True
    assert s.setup == "manual"


def test_every_agent_has_a_display_name(home, state_dir):
    ids = {a.id for a in ag.detect_agents(home=home, state_dir=state_dir, which=_no_binaries)}
    assert ids == {
        "claude-code", "codex", "cursor", "aider", "gemini-cli", "opencode", "cline", "command-code",
        "hermes", "pi", "omp", "kilo", "openclaw", "kimi-code", "goose",
        "zed", "openhands", "deepseek-harness", "zcode",
    }
    for a in ag.detect_agents(home=home, state_dir=state_dir, which=_no_binaries):
        assert a.name


# ── Claude Code connect / disconnect ────────────────────────────────────


def test_connect_claude_code_creates_settings_with_gateway_env(home, state_dir):
    (home / ".claude").mkdir()
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)

    data = json.loads(_claude_settings(home).read_text())
    assert data["env"]["ANTHROPIC_BASE_URL"] == BASE
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == KEY
    assert _status(home, state_dir, "claude-code").connected is True


def test_new_settings_file_is_private(home, state_dir):
    (home / ".claude").mkdir()
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert stat.S_IMODE(os.stat(_claude_settings(home)).st_mode) == 0o600


def test_connect_preserves_unrelated_settings(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    p.write_text(json.dumps({"model": "opus", "env": {"DISABLE_TELEMETRY": "1"}}))

    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)

    data = json.loads(p.read_text())
    assert data["model"] == "opus"
    assert data["env"]["DISABLE_TELEMETRY"] == "1"
    assert data["env"]["ANTHROPIC_BASE_URL"] == BASE


def test_disconnect_restores_original_bytes_when_untouched(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    original = '{\n    "model": "opus"   ,\n  "theme": "dark"\n}\n'  # odd formatting on purpose
    p.write_text(original)

    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)

    assert p.read_text() == original
    assert _status(home, state_dir, "claude-code").connected is False


def test_disconnect_removes_file_it_created(home, state_dir):
    (home / ".claude").mkdir()
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert not _claude_settings(home).exists()


def test_disconnect_after_user_edit_keeps_edit_and_restores_previous_values(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    p.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://corp-proxy.example"}}))

    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    data = json.loads(p.read_text())
    data["theme"] = "light"  # user changes something while connected
    p.write_text(json.dumps(data))

    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)

    after = json.loads(p.read_text())
    assert after["theme"] == "light"
    assert after["env"]["ANTHROPIC_BASE_URL"] == "https://corp-proxy.example"
    assert "ANTHROPIC_AUTH_TOKEN" not in after["env"]


def test_disconnect_leaves_values_the_user_changed_after_connect(home, state_dir):
    (home / ".claude").mkdir()
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    p = _claude_settings(home)
    data = json.loads(p.read_text())
    data["env"]["ANTHROPIC_BASE_URL"] = "https://somewhere-else.example"
    p.write_text(json.dumps(data))

    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)

    assert json.loads(p.read_text())["env"]["ANTHROPIC_BASE_URL"] == "https://somewhere-else.example"


def test_reconnect_keeps_the_first_backup(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    original = json.dumps({"model": "sonnet"})
    p.write_text(original)

    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key="sk-orca-" + "f" * 32)
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)

    assert p.read_text() == original


def test_invalid_json_is_refused_and_left_alone(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    p.write_text("{ not json")
    with pytest.raises(ag.AgentConfigError):
        ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert p.read_text() == "{ not json"
    assert _status(home, state_dir, "claude-code").connected is False


def test_disconnect_when_not_connected_is_a_no_op(home, state_dir):
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert _status(home, state_dir, "claude-code").connected is False


def test_state_file_is_private(home, state_dir):
    (home / ".claude").mkdir()
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    state_file = state_dir / "connections.json"
    assert state_file.exists()
    assert stat.S_IMODE(os.stat(state_file).st_mode) == 0o600


# ── unsupported / manual agents ─────────────────────────────────────────


def test_connecting_an_unsupported_agent_is_refused(home, state_dir, monkeypatch):
    monkeypatch.setitem(ag.AGENTS, "future", ag.AgentSpec(
        id="future", name="Future", binaries=(), config_dirs=(), setup="unsupported", note="Not yet."))
    with pytest.raises(ag.AgentNotSupported, match="Not yet"):
        ag.connect_agent("future", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)


def test_unknown_agent_is_rejected(home, state_dir):
    with pytest.raises(ag.UnknownAgent):
        ag.connect_agent("notepad", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)


def test_cursor_connect_returns_manual_instructions_and_marks_connected(home, state_dir):
    result = ag.connect_agent("cursor", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert result.manual is True
    assert result.base_url == f"{BASE}/v1"
    assert result.api_key == KEY
    assert _status(home, state_dir, "cursor").connected is True
    ag.disconnect_agent("cursor", home=home, state_dir=state_dir)
    assert _status(home, state_dir, "cursor").connected is False


# ── Aider ───────────────────────────────────────────────────────────────


def test_aider_round_trip(home, state_dir):
    p = home / ".aider.conf.yml"
    original = "# my aider config\nmodel: gpt-4o\ndark-mode: true\n"
    p.write_text(original)

    ag.connect_agent("aider", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    data = yaml.safe_load(p.read_text())
    assert data["openai-api-base"] == f"{BASE}/v1"
    assert data["openai-api-key"] == KEY
    assert data["model"] == "openai/auto"
    assert data["dark-mode"] is True

    ag.disconnect_agent("aider", home=home, state_dir=state_dir)
    assert p.read_text() == original


def test_connect_result_tells_the_caller_what_changed(home, state_dir):
    (home / ".claude").mkdir()
    result = ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert result.manual is False
    assert result.config_path == str(_claude_settings(home))


# ── review fixes ────────────────────────────────────────────────────────


def test_symlinked_config_stays_a_symlink_and_target_is_updated(home, state_dir, tmp_path):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    target = dotfiles / "claude-settings.json"
    original = json.dumps({"model": "opus"})
    target.write_text(original)
    (home / ".claude").mkdir()
    link = _claude_settings(home)
    link.symlink_to(target)

    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert link.is_symlink()
    assert json.loads(target.read_text())["env"]["ANTHROPIC_BASE_URL"] == BASE

    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert link.is_symlink()
    assert target.read_text() == original


def test_non_object_env_is_refused_not_overwritten(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    p.write_text(json.dumps({"env": "not-an-object"}))
    with pytest.raises(ag.AgentConfigError):
        ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert json.loads(p.read_text()) == {"env": "not-an-object"}


def test_aider_comments_survive_a_connect_and_a_surgical_disconnect(home, state_dir):
    p = home / ".aider.conf.yml"
    p.write_text("# my aider config\nmodel: gpt-4o  # favourite\ndark-mode: true\nnote: café\n")
    ag.connect_agent("aider", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    connected = p.read_text()
    assert "# my aider config" in connected and "café" in connected
    assert yaml.safe_load(connected)["model"] == "openai/auto"

    p.write_text(connected + "# added while connected\n")  # forces the surgical path
    ag.disconnect_agent("aider", home=home, state_dir=state_dir)
    after = p.read_text()
    assert "# my aider config" in after and "# added while connected" in after and "café" in after
    data = yaml.safe_load(after)
    assert data["model"] == "gpt-4o"
    assert "openai-api-key" not in data and "openai-api-base" not in data


def test_original_file_mode_is_kept(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    p.write_text("{}")
    os.chmod(p, 0o644)
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o644
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o644


def test_malformed_state_entry_is_a_clean_error(home, state_dir):
    (state_dir / "connections.json").write_text(json.dumps({"claude-code": {"oops": 1}}))
    with pytest.raises(ag.AgentConfigError):
        ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)


def test_a_previous_value_that_looks_like_the_old_sentinel_is_restored(home, state_dir):
    p = _claude_settings(home)
    p.parent.mkdir()
    weird = {"__orca_absent__": True}
    p.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": weird}}))
    ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE, api_key=KEY)
    data = json.loads(p.read_text())
    data["x"] = 1
    p.write_text(json.dumps(data))
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert json.loads(p.read_text())["env"]["ANTHROPIC_BASE_URL"] == weird


def test_concurrent_connects_keep_the_users_original(home, state_dir):
    import threading

    p = _claude_settings(home)
    p.parent.mkdir()
    original = json.dumps({"model": "sonnet"})
    p.write_text(original)
    errors = []

    def go(i):
        try:
            ag.connect_agent("claude-code", home=home, state_dir=state_dir, base_url=BASE,
                             api_key=f"sk-orca-{i:032d}")
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert p.read_text() == original
