"""D5: notice when an agent undoes Orca.

Agents rewrite their configs when they update or when the user runs the
agent's own setup. Orca records the values it wrote, so on each poll it can
tell that an agent it connected no longer points at it ("changed"). Connect
again re-applies Orca's values and keeps the very first backup, so a later
disconnect still puts back what the user had before Orca.
"""

from __future__ import annotations

import json

import pytest

from packages.desktop import agents as ag

BASE = "http://127.0.0.1:8765"
KEY = "sk-orca-0123456789abcdef0123456789abcdef"
KEY2 = "sk-orca-fedcba9876543210fedcba9876543210"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".codex").mkdir()
    return h


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def _status(home, state_dir, agent_id):
    return next(a for a in ag.detect_agents(home=home, state_dir=state_dir, which=lambda _n: None) if a.id == agent_id)


ORIGINAL = b'{\n  "theme": "dark"\n}\n'


def _connect(home, state_dir, agent="claude-code", key=KEY):
    ag.connect_agent(agent, home=home, state_dir=state_dir, base_url=BASE, api_key=key)


def test_a_connected_agent_is_not_changed(home, state_dir):
    (home / ".claude/settings.json").write_bytes(ORIGINAL)
    _connect(home, state_dir)
    s = _status(home, state_dir, "claude-code")
    assert s.connected is True and s.changed is False


def test_an_updater_replacing_the_settings_marks_the_agent_changed(home, state_dir):
    settings = home / ".claude/settings.json"
    settings.write_bytes(ORIGINAL)
    _connect(home, state_dir)
    # Like an update rewriting the file without Orca's env block.
    settings.write_text(json.dumps({"theme": "dark", "autoUpdates": True}, indent=2))
    s = _status(home, state_dir, "claude-code")
    assert s.connected is True and s.changed is True


def test_a_deleted_config_is_changed(home, state_dir):
    _connect(home, state_dir)
    (home / ".claude/settings.json").unlink()
    assert _status(home, state_dir, "claude-code").changed is True


def test_user_edits_that_keep_orcas_values_are_not_a_change(home, state_dir):
    settings = home / ".claude/settings.json"
    settings.write_bytes(ORIGINAL)
    _connect(home, state_dir)
    data = json.loads(settings.read_text())
    data["theme"] = "light"
    data["model"] = "opus"
    settings.write_text(json.dumps(data))
    assert _status(home, state_dir, "claude-code").changed is False


def test_choosing_another_model_in_the_agent_is_not_a_change(home, state_dir):
    _connect(home, state_dir, "codex")
    cfg = home / ".codex/config.toml"
    cfg.write_text(cfg.read_text().replace('model = "auto"', 'model = "gpt-5"'))
    assert _status(home, state_dir, "codex").changed is False


def test_switching_the_agent_back_to_its_own_provider_is_a_change(home, state_dir):
    _connect(home, state_dir, "codex")
    cfg = home / ".codex/config.toml"
    cfg.write_text(cfg.read_text().replace('model_provider = "orca"', 'model_provider = "openai"'))
    assert _status(home, state_dir, "codex").changed is True


def test_a_manual_agent_is_never_changed(home, state_dir):
    _connect(home, state_dir, "cursor")
    s = _status(home, state_dir, "cursor")
    assert s.connected is True and s.changed is False


def test_reconnect_restores_orcas_values_and_disconnect_the_first_original(home, state_dir):
    settings = home / ".claude/settings.json"
    settings.write_bytes(ORIGINAL)
    _connect(home, state_dir)
    settings.write_bytes(ORIGINAL)  # the agent's own setup put its file back
    assert _status(home, state_dir, "claude-code").changed is True

    _connect(home, state_dir, key=KEY2)
    env = json.loads(settings.read_text())["env"]
    assert env == {"ANTHROPIC_BASE_URL": BASE, "ANTHROPIC_AUTH_TOKEN": KEY2}
    assert _status(home, state_dir, "claude-code").changed is False

    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert settings.read_bytes() == ORIGINAL


def test_reconnect_after_a_change_to_a_file_orca_created_removes_it_on_disconnect(home, state_dir):
    settings = home / ".claude/settings.json"
    _connect(home, state_dir)
    settings.unlink()  # the update removed it
    _connect(home, state_dir, key=KEY2)
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert not settings.exists()


def test_what_an_update_added_survives_reconnect_and_disconnect(home, state_dir):
    # An update rewrote the file with new settings of its own (and without
    # Orca's). Reconnect re-applies Orca's values; disconnect must then take
    # out only Orca's values, not roll the file back to before the update.
    settings = home / ".claude/settings.json"
    settings.write_bytes(ORIGINAL)
    _connect(home, state_dir)
    updated = {"theme": "dark", "hooks": {"Stop": [{"command": "notify"}]}}
    settings.write_text(json.dumps(updated, indent=2))
    _connect(home, state_dir, key=KEY2)
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert json.loads(settings.read_text()) == updated


@pytest.mark.parametrize(("agent", "path", "old", "new"), [
    ("opencode", ".config/opencode/opencode.json", '"orca/auto"', '"anthropic/claude-sonnet-4-6"'),
    ("kimi-code", ".kimi-code/config.toml", 'default_model = "orca-auto"', 'default_model = "kimi-k2"'),
])
def test_selecting_another_provider_by_model_name_is_a_change(home, state_dir, agent, path, old, new):
    # These agents pick the provider through the model string; moving it off
    # orca/ (or orca-) means requests no longer go through Orca.
    _connect(home, state_dir, agent)
    cfg = home / path
    assert old in cfg.read_text()
    cfg.write_text(cfg.read_text().replace(old, new))
    assert _status(home, state_dir, agent).changed is True


def test_picking_another_orca_model_by_name_is_not_a_change(home, state_dir):
    _connect(home, state_dir, "opencode")
    cfg = home / ".config/opencode/opencode.json"
    cfg.write_text(cfg.read_text().replace('"orca/auto"', '"orca/gpt-4o"'))
    assert _status(home, state_dir, "opencode").changed is False


def test_a_damaged_state_file_reads_as_nothing_connected(home, state_dir):
    # Read-only callers (the panel's poll, diagnostics) must not fail on it.
    (state_dir / "connections.json").write_text("{not json")
    agents = ag.detect_agents(home=home, state_dir=state_dir, which=lambda _n: None)
    assert agents and not any(a.connected for a in agents)


def test_ordinary_user_edits_still_survive_a_disconnect(home, state_dir):
    # Unchanged behaviour: edits that keep Orca's values aren't thrown away.
    settings = home / ".claude/settings.json"
    settings.write_bytes(ORIGINAL)
    _connect(home, state_dir)
    data = json.loads(settings.read_text())
    data["theme"] = "light"
    settings.write_text(json.dumps(data))
    _connect(home, state_dir, key=KEY2)
    ag.disconnect_agent("claude-code", home=home, state_dir=state_dir)
    assert json.loads(settings.read_text()) == {"theme": "light"}
