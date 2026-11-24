"""Connectors for Gemini CLI, Codex, OpenCode, Command Code and Cline.

Same promises as the Claude Code and Aider connectors (see
test_desktop_agents.py): connect touches only the settings it needs, and
disconnect puts every file back byte-for-byte when the user hasn't edited it,
or reverts only our settings when they have.

Config shapes come from the agents' own code:
- Gemini CLI: GOOGLE_GEMINI_BASE_URL selects its "gateway" auth type, and a
  saved `security.auth.selectedType` overrides the environment, so both
  ~/.gemini/.env and ~/.gemini/settings.json are set.
- Codex: only the Responses API (`wire_api = "responses"`); the key goes in
  `experimental_bearer_token` so no environment variable is needed.
- OpenCode: a v1 `provider` entry with @ai-sdk/openai-compatible; the key is
  read with `{file:…}`.
- Command Code: ~/.commandcode/providers.json refuses raw keys, so `apiKey`
  is a `!command` that prints a key file.
"""

from __future__ import annotations

import json
import os
import stat
import tomllib

import pytest

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


def _connect(agent_id, home, state_dir, key=KEY):
    return ag.connect_agent(agent_id, home=home, state_dir=state_dir, base_url=BASE, api_key=key)


def _disconnect(agent_id, home, state_dir):
    ag.disconnect_agent(agent_id, home=home, state_dir=state_dir)


def _status(home, state_dir, agent_id, which=lambda _n: None):
    [s] = [a for a in ag.detect_agents(home=home, state_dir=state_dir, which=which) if a.id == agent_id]
    return s


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


# ── the agent list ──────────────────────────────────────────────────────


def test_supported_agents_are_the_ones_we_connect():
    assert {"claude-code", "codex", "gemini-cli", "opencode", "cline", "command-code"} <= set(ag.AGENTS)
    assert "continue" not in ag.AGENTS
    for agent_id in ("codex", "gemini-cli", "opencode", "command-code"):
        assert ag.AGENTS[agent_id].setup == "auto", agent_id
    assert ag.AGENTS["cline"].setup == "manual"


@pytest.mark.parametrize(
    "agent_id, marker",
    [
        ("gemini-cli", ".gemini"),
        ("codex", ".codex"),
        ("opencode", ".config/opencode"),
        ("command-code", ".commandcode"),
        ("cline", ".cline"),
    ],
)
def test_detected_from_its_config_folder(home, state_dir, agent_id, marker):
    assert _status(home, state_dir, agent_id).installed is False
    (home / marker).mkdir(parents=True)
    assert _status(home, state_dir, agent_id).installed is True


def test_command_code_is_not_detected_from_windows_cmd(home, state_dir):
    # Command Code installs a `cmd` alias, but on Windows that's cmd.exe.
    assert _status(home, state_dir, "command-code", which=lambda n: "/x/cmd" if n == "cmd" else None).installed is False
    assert _status(home, state_dir, "command-code", which=lambda n: "/x/cc" if n == "command-code" else None).installed


# ── Gemini CLI ──────────────────────────────────────────────────────────


def _gemini(home):
    return home / ".gemini" / ".env", home / ".gemini" / "settings.json"


def test_gemini_connect_sets_gateway_env_and_auth_type(home, state_dir):
    env, settings = _gemini(home)
    env.parent.mkdir()
    env.write_text("# my env\nGOOGLE_CLOUD_PROJECT=my-proj\n")
    settings.write_text(json.dumps({"ui": {"theme": "Dracula"}, "security": {"auth": {"selectedType": "oauth-personal"}}}))

    _connect("gemini-cli", home, state_dir)

    text = env.read_text()
    assert "# my env" in text and "GOOGLE_CLOUD_PROJECT=my-proj" in text
    assert f"GOOGLE_GEMINI_BASE_URL={BASE}\n" in text  # the SDK appends /v1beta itself
    assert f"GEMINI_API_KEY={KEY}\n" in text
    s = json.loads(settings.read_text())
    assert s["security"]["auth"]["selectedType"] == "gateway"
    assert s["ui"] == {"theme": "Dracula"}
    assert _status(home, state_dir, "gemini-cli").connected


def test_gemini_disconnect_restores_both_files_exactly(home, state_dir):
    env, settings = _gemini(home)
    env.parent.mkdir()
    env_bytes = b"GEMINI_API_KEY=my-own-key\n# keep me\n"
    settings_bytes = b'{\n    "security": {"auth": {"selectedType": "gemini-api-key"}}\n}\n'
    env.write_bytes(env_bytes)
    settings.write_bytes(settings_bytes)

    _connect("gemini-cli", home, state_dir)
    _disconnect("gemini-cli", home, state_dir)

    assert env.read_bytes() == env_bytes
    assert settings.read_bytes() == settings_bytes
    assert not _status(home, state_dir, "gemini-cli").connected


def test_gemini_disconnect_removes_files_it_created(home, state_dir):
    env, settings = _gemini(home)
    _connect("gemini-cli", home, state_dir)
    assert _mode(env) == 0o600
    _disconnect("gemini-cli", home, state_dir)
    assert not env.exists() and not settings.exists()


def test_gemini_disconnect_after_user_edit_reverts_only_our_lines(home, state_dir):
    env, settings = _gemini(home)
    env.parent.mkdir()
    env.write_text("GEMINI_API_KEY=my-own-key\n")
    _connect("gemini-cli", home, state_dir)
    env.write_text(env.read_text() + "DEBUG=1\n")  # the user edits while connected

    _disconnect("gemini-cli", home, state_dir)

    text = env.read_text()
    assert "GEMINI_API_KEY=my-own-key\n" in text
    assert "DEBUG=1\n" in text
    assert "GOOGLE_GEMINI_BASE_URL" not in text


def test_gemini_settings_with_comments_are_refused_untouched(home, state_dir):
    env, settings = _gemini(home)
    env.parent.mkdir()
    raw = '{\n  // my theme\n  "ui": {"theme": "x"}\n}\n'
    settings.write_text(raw)
    with pytest.raises(ag.AgentConfigError):
        _connect("gemini-cli", home, state_dir)
    assert settings.read_text() == raw
    assert not env.exists()  # nothing half-done
    assert not _status(home, state_dir, "gemini-cli").connected


# ── Codex ───────────────────────────────────────────────────────────────


def _codex(home):
    return home / ".codex" / "config.toml"


CODEX_CONFIG = """\
# my codex settings
model = "gpt-5.1-codex"
approval_policy = "on-request"

[projects."/home/me/app"]
trust_level = "trusted"
"""


def test_codex_connect_adds_a_responses_provider_and_selects_it(home, state_dir):
    cfg = _codex(home)
    cfg.parent.mkdir()
    cfg.write_text(CODEX_CONFIG)

    _connect("codex", home, state_dir)

    text = cfg.read_text()
    assert "# my codex settings" in text
    data = tomllib.loads(text)
    assert data["model_provider"] == "orca"
    assert data["model"] == "auto"
    assert data["approval_policy"] == "on-request"
    assert data["projects"]["/home/me/app"]["trust_level"] == "trusted"
    assert data["model_providers"]["orca"] == {
        "name": "OrcaRouter Lite",
        "base_url": f"{BASE}/v1",
        "wire_api": "responses",
        "experimental_bearer_token": KEY,
    }


def test_codex_top_level_keys_stay_above_the_first_table(home, state_dir):
    cfg = _codex(home)
    cfg.parent.mkdir()
    cfg.write_text('[projects."/p"]\ntrust_level = "trusted"\n')
    _connect("codex", home, state_dir)
    data = tomllib.loads(cfg.read_text())
    assert data["model_provider"] == "orca"  # not swallowed by [projects."/p"]
    assert "model_provider" not in data["projects"]["/p"]


def test_codex_disconnect_restores_original_bytes(home, state_dir):
    cfg = _codex(home)
    cfg.parent.mkdir()
    cfg.write_text(CODEX_CONFIG)
    _connect("codex", home, state_dir)
    _disconnect("codex", home, state_dir)
    assert cfg.read_text() == CODEX_CONFIG


def test_codex_disconnect_after_user_edit_restores_previous_model_and_keeps_edits(home, state_dir):
    cfg = _codex(home)
    cfg.parent.mkdir()
    cfg.write_text(CODEX_CONFIG)
    _connect("codex", home, state_dir)
    cfg.write_text(cfg.read_text() + '\n[mcp_servers.docs]\ncommand = "docs-mcp"\n')

    _disconnect("codex", home, state_dir)

    text = cfg.read_text()
    data = tomllib.loads(text)
    assert data["model"] == "gpt-5.1-codex"
    assert "model_provider" not in data
    assert "orca" not in data.get("model_providers", {})
    assert data["mcp_servers"]["docs"]["command"] == "docs-mcp"
    assert "# my codex settings" in text


def test_codex_invalid_toml_is_refused_untouched(home, state_dir):
    cfg = _codex(home)
    cfg.parent.mkdir()
    cfg.write_text("model = \n")
    with pytest.raises(ag.AgentConfigError):
        _connect("codex", home, state_dir)
    assert cfg.read_text() == "model = \n"


# ── OpenCode ────────────────────────────────────────────────────────────


def _opencode(home):
    return home / ".config" / "opencode" / "opencode.json"


def test_opencode_connect_adds_provider_with_key_read_from_a_private_file(home, state_dir):
    cfg = _opencode(home)
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "theme": "tokyonight"}))

    _connect("opencode", home, state_dir)

    data = json.loads(cfg.read_text())
    assert data["theme"] == "tokyonight"
    assert data["model"] == "orca/auto"
    p = data["provider"]["orca"]
    assert p["npm"] == "@ai-sdk/openai-compatible"
    assert p["options"]["baseURL"] == f"{BASE}/v1"
    assert KEY not in cfg.read_text()  # the key isn't written into the agent's config
    ref = p["options"]["apiKey"]
    assert ref.startswith("{file:") and ref.endswith("}")
    key_file = ref[len("{file:"):-1]
    assert os.path.isabs(key_file)
    assert open(key_file).read() == KEY
    assert _mode(key_file) == 0o600
    assert "auto" in p["models"]


def test_opencode_disconnect_restores_and_removes_the_key_file(home, state_dir):
    cfg = _opencode(home)
    cfg.parent.mkdir(parents=True)
    original = b'{"theme": "tokyonight"}\n'
    cfg.write_bytes(original)
    _connect("opencode", home, state_dir)
    key_file = json.loads(cfg.read_text())["provider"]["orca"]["options"]["apiKey"][len("{file:"):-1]

    _disconnect("opencode", home, state_dir)

    assert cfg.read_bytes() == original
    assert not os.path.exists(key_file)


# ── Command Code ────────────────────────────────────────────────────────


def _commandcode(home):
    return home / ".commandcode" / "providers.json"


def test_command_code_connect_uses_a_key_command_not_a_raw_key(home, state_dir):
    _connect("command-code", home, state_dir)
    cfg = _commandcode(home)
    data = json.loads(cfg.read_text())
    p = data["provider"]["orca"]
    assert p["baseURL"] == f"{BASE}/v1"
    assert p["api"] == "openai-completions"
    assert "auto" in p["models"]
    assert KEY not in cfg.read_text()  # Command Code ignores raw keys in this file
    assert p["apiKey"].startswith("!")
    assert _mode(cfg) == 0o600


def test_command_code_key_command_prints_the_key(home, state_dir):
    import shlex
    import subprocess

    _connect("command-code", home, state_dir)
    cmd = json.loads(_commandcode(home).read_text())["provider"]["orca"]["apiKey"][1:]
    if os.name != "nt":
        assert shlex.split(cmd)[0] == "cat"
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True).stdout
        assert out.strip() == KEY


def test_key_command_quotes_paths_for_each_shell(tmp_path):
    p = tmp_path / "it's here" / "command-code.key"
    assert ag._key_command(p, windows=False) == f"!cat '{tmp_path}/it'\"'\"'s here/command-code.key'"
    assert ag._key_command(p, windows=True) == f'!type "{p}"'


def test_command_code_adds_to_an_existing_providers_map(home, state_dir):
    cfg = _commandcode(home)
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"providers": {"local": {"baseURL": "http://localhost:1234/v1", "apiKey": False,
                                                        "models": {"qwen": {}}}}}))
    _connect("command-code", home, state_dir)
    data = json.loads(cfg.read_text())
    assert set(data["providers"]) == {"local", "orca"}
    assert "provider" not in data


def test_command_code_round_trip(home, state_dir):
    cfg = _commandcode(home)
    cfg.parent.mkdir()
    original = b'{\n  "provider": {}\n}\n'
    cfg.write_bytes(original)
    _connect("command-code", home, state_dir)
    _disconnect("command-code", home, state_dir)
    assert cfg.read_bytes() == original
    keys = state_dir / "keys"
    assert not keys.exists() or list(keys.iterdir()) == []


# ── Cline ───────────────────────────────────────────────────────────────


def test_cline_is_manual_with_the_exact_steps(home, state_dir):
    (home / ".cline").mkdir()
    s = _status(home, state_dir, "cline")
    assert s.setup == "manual"
    assert "OpenAI Compatible" in s.note
    r = _connect("cline", home, state_dir)
    assert r.manual is True
    assert r.base_url == f"{BASE}/v1"
    assert r.api_key == KEY


# ── shared guarantees ───────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", ["gemini-cli", "codex", "opencode", "command-code"])
def test_reconnect_with_a_new_key_keeps_the_first_backup(home, state_dir, agent_id):
    _connect(agent_id, home, state_dir, key=KEY)
    _connect(agent_id, home, state_dir, key=KEY.replace("0", "1"))
    _disconnect(agent_id, home, state_dir)
    # Nothing existed before the first connect, so nothing is left behind.
    leftovers = [p for p in home.rglob("*") if p.is_file()]
    assert leftovers == []


# ── review fixes ────────────────────────────────────────────────────────


def test_reconnect_after_a_user_edit_then_disconnect_keeps_the_edit(home, state_dir):
    # A key rotation or joining a gateway reconnects every agent; the first
    # connect's byte backup must not wipe edits made since then.
    cfg = home / ".claude" / "settings.json"
    cfg.parent.mkdir()
    cfg.write_text('{"theme": "dark"}')
    _connect("claude-code", home, state_dir)
    data = json.loads(cfg.read_text())
    data["model"] = "opus"
    cfg.write_text(json.dumps(data))
    _connect("claude-code", home, state_dir, key=KEY.replace("0", "2"))

    _disconnect("claude-code", home, state_dir)

    assert json.loads(cfg.read_text()) == {"theme": "dark", "model": "opus"}


def test_reconnect_without_edits_still_restores_bytes(home, state_dir):
    cfg = home / ".claude" / "settings.json"
    cfg.parent.mkdir()
    cfg.write_bytes(b'{\n    "theme": "dark"\n}\n')
    _connect("claude-code", home, state_dir)
    _connect("claude-code", home, state_dir, key=KEY.replace("0", "2"))
    _disconnect("claude-code", home, state_dir)
    assert cfg.read_bytes() == b'{\n    "theme": "dark"\n}\n'


def test_codex_restores_a_previous_orca_table_with_inline_tables_and_arrays(home, state_dir):
    cfg = _codex(home)
    cfg.parent.mkdir()
    cfg.write_text(
        '[model_providers.orca]\nname = "mine"\nbase_url = "https://x/v1"\n'
        'query_params = { api-version = "2025-01-01" }\nretries = [1, 2]\n'
    )
    before = tomllib.loads(cfg.read_text())["model_providers"]["orca"]
    _connect("codex", home, state_dir)
    cfg.write_text(cfg.read_text() + '\n[mcp_servers.docs]\ncommand = "docs"\n')  # user edit

    _disconnect("codex", home, state_dir)

    data = tomllib.loads(cfg.read_text())
    assert data["model_providers"]["orca"] == before
    assert data["mcp_servers"]["docs"]["command"] == "docs"


@pytest.mark.parametrize("previous", ["abc\\def", 'has "quotes"', "it's", "ünïcode", "a b # c"])
def test_gemini_restores_awkward_previous_values_exactly(home, state_dir, previous):
    env, _settings = _gemini(home)
    env.parent.mkdir()
    env.write_text(f"GEMINI_API_KEY={ag._dotenv_value(previous)}\n")
    assert ag._parse_dotenv(env.read_text())["GEMINI_API_KEY"] == previous
    _connect("gemini-cli", home, state_dir)
    env.write_text(env.read_text() + "DEBUG=1\n")  # user edit: surgical revert path

    _disconnect("gemini-cli", home, state_dir)

    assert ag._parse_dotenv(env.read_text())["GEMINI_API_KEY"] == previous


def test_one_file_failing_to_restore_does_not_stop_the_others(home, state_dir, monkeypatch):
    env, settings = _gemini(home)
    settings.parent.mkdir()
    settings.write_text('{"security": {"auth": {"selectedType": "oauth-personal"}}}')
    _connect("gemini-cli", home, state_dir)

    real = ag._restore_file

    def flaky(fentry, fmt):
        if fentry["path"].endswith(".env"):
            raise ag.AgentConfigError("disk full")
        return real(fentry, fmt)

    monkeypatch.setattr(ag, "_restore_file", flaky)
    with pytest.raises(ag.AgentConfigError, match="disk full"):
        _disconnect("gemini-cli", home, state_dir)
    # settings.json was still put back, and only .env is left to restore.
    assert json.loads(settings.read_text())["security"]["auth"]["selectedType"] == "oauth-personal"
    assert _status(home, state_dir, "gemini-cli").connected

    monkeypatch.setattr(ag, "_restore_file", real)
    _disconnect("gemini-cli", home, state_dir)
    assert not env.exists()
    assert not _status(home, state_dir, "gemini-cli").connected


def _fail_writes_to(monkeypatch, name):
    real = ag._write_atomic

    def write(path, data, mode=None):
        if path.name == name:
            raise OSError(28, "No space left on device")
        return real(path, data, mode)

    monkeypatch.setattr(ag, "_write_atomic", write)


def test_a_failed_first_connect_leaves_no_key_file(home, state_dir, monkeypatch):
    _fail_writes_to(monkeypatch, "opencode.json")
    with pytest.raises(ag.AgentConfigError):
        _connect("opencode", home, state_dir)
    assert not (state_dir / "keys" / "opencode.key").exists()


def test_a_failed_reconnect_keeps_the_working_key(home, state_dir, monkeypatch):
    _connect("opencode", home, state_dir, key=KEY)
    _fail_writes_to(monkeypatch, "opencode.json")
    with pytest.raises(ag.AgentConfigError):
        _connect("opencode", home, state_dir, key=KEY.replace("0", "3"))
    assert (state_dir / "keys" / "opencode.key").read_text() == KEY


def test_only_real_warnings_are_flagged_as_warnings(home, state_dir):
    # Claude Code's note says billing moves off the subscription: a warning.
    # The others just say which model they'll use.
    flagged = {s.id for s in ag.detect_agents(home=home, state_dir=state_dir, which=lambda _n: None) if s.warn}
    assert flagged == {"claude-code"}


@pytest.mark.parametrize("agent_id", ["gemini-cli", "opencode"])
def test_a_failed_state_save_puts_every_file_back(home, state_dir, monkeypatch, agent_id):
    # connections.json lives in another folder than the agent's config; if
    # recording the backup fails, the agent must not be left pointing at a
    # key the engine is about to delete, with no record to restore from.
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text('{"ui": {"theme": "GitHub"}}\n')
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.json").write_text('{"theme": "tokyonight"}\n')
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}

    def disk_full(*_a, **_kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ag, "_save_state", disk_full)
    with pytest.raises(ag.AgentConfigError, match="No space left"):
        _connect(agent_id, home, state_dir)

    assert {p: p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    keys = state_dir / "keys"
    assert not keys.exists() or list(keys.iterdir()) == []
