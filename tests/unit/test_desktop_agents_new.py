"""Connectors for Hermes, Pi, OMP, Kilo, OpenClaw, Kimi Code and Goose,
and the guided (manual) setups for Zed, Cursor, OpenHands, DeepSeek Harness
and ZCode.

Same promises as the other connectors (test_desktop_agents*.py): connect
changes only the settings it needs, and disconnect puts every file back
byte-for-byte when the user hasn't edited it, or reverts only our settings
when they have.

Config shapes come from each agent's own docs and source:
- Hermes Agent: ~/.hermes/config.yaml, a named `providers.<id>` entry
  selected with `model.provider: custom:<id>`.
- Pi: ~/.pi/agent/models.json `providers` and settings.json
  `defaultProvider`/`defaultModel`.
- OMP (oh-my-pi): ~/.omp/agent/models.yml `providers` and
  ~/.omp/agent/config.yml `modelRoles.default`.
- Kilo: an OpenCode fork; ~/.config/kilo/kilo.json, key read with {file:}.
- OpenClaw: ~/.openclaw/openclaw.json `models.providers` and
  `agents.defaults.model.primary`.
- Kimi Code: ~/.kimi-code/config.toml `[providers.*]`, `[models.*]` and
  `default_model`.
- Goose: a declarative provider file in ~/.config/goose/custom_providers
  whose key comes from `auth.command`, selected in config.yaml.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib

import pytest
import yaml

from packages.desktop import agents as ag

BASE = "http://127.0.0.1:8765"
KEY = "sk-orca-0123456789abcdef0123456789abcdef"

NEW_AUTO = ["hermes", "pi", "omp", "kilo", "openclaw", "kimi-code", "goose"]
NEW_MANUAL = ["zed", "cursor", "openhands", "deepseek-harness", "zcode"]


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


def _files(agent_id, home):
    return [home / rel for rel, _fmt in ag.AGENTS[agent_id].files]


def _snapshot(home):
    return {p.relative_to(home).as_posix(): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()}


# ── the agent list ──────────────────────────────────────────────────────


def test_every_requested_agent_is_listed():
    for agent_id in NEW_AUTO:
        assert ag.AGENTS[agent_id].setup == "auto", agent_id
    for agent_id in NEW_MANUAL:
        assert ag.AGENTS[agent_id].setup == "manual", agent_id


@pytest.mark.parametrize(
    "agent_id, marker",
    [
        ("hermes", ".hermes"),
        ("pi", ".pi"),
        ("omp", ".omp"),
        ("kilo", ".config/kilo"),
        ("openclaw", ".openclaw"),
        ("kimi-code", ".kimi-code"),
        ("goose", ".config/goose"),
        ("zed", ".config/zed"),
        ("openhands", ".openhands"),
        ("deepseek-harness", ".dsh"),
        ("zcode", ".zcode"),
    ],
)
def test_detected_from_its_config_folder(home, state_dir, agent_id, marker):
    assert _status(home, state_dir, agent_id).installed is False
    (home / marker).mkdir(parents=True)
    assert _status(home, state_dir, agent_id).installed is True


@pytest.mark.parametrize(
    "agent_id, binary",
    [("hermes", "hermes"), ("pi", "pi"), ("omp", "omp"), ("kilo", "kilo"), ("openclaw", "openclaw"),
     ("kimi-code", "kimi"), ("goose", "goose"), ("zed", "zed"), ("openhands", "openhands"),
     ("deepseek-harness", "dsh"), ("zcode", "zcode")],
)
def test_detected_from_its_command(home, state_dir, agent_id, binary):
    assert _status(home, state_dir, agent_id, which=lambda n: f"/bin/{n}" if n == binary else None).installed


# ── shared guarantees for every new auto connector ──────────────────────


@pytest.mark.parametrize("agent_id", NEW_AUTO)
def test_connect_then_disconnect_on_a_fresh_install_leaves_nothing_behind(home, state_dir, agent_id):
    _connect(agent_id, home, state_dir)
    assert all(p.exists() for p in _files(agent_id, home))
    _disconnect(agent_id, home, state_dir)
    assert _snapshot(home) == {}
    keys = state_dir / "keys"
    assert not keys.exists() or list(keys.iterdir()) == []


@pytest.mark.parametrize("agent_id", NEW_AUTO)
def test_reconnect_with_a_new_key_then_disconnect_restores_the_first_backup(home, state_dir, agent_id):
    _connect(agent_id, home, state_dir)
    _connect(agent_id, home, state_dir, key="sk-orca-" + "f" * 32)
    _disconnect(agent_id, home, state_dir)
    assert _snapshot(home) == {}


@pytest.mark.parametrize("agent_id", NEW_AUTO)
def test_connected_status_and_config_path(home, state_dir, agent_id):
    r = _connect(agent_id, home, state_dir)
    assert r.manual is False
    s = _status(home, state_dir, agent_id)
    assert s.connected is True
    assert s.config_path == str(_files(agent_id, home)[0])


# ── Hermes Agent ────────────────────────────────────────────────────────

HERMES_ORIGINAL = """\
# Hermes settings — keep this comment
model:
  default: anthropic/claude-sonnet-4.6
  provider: openrouter

providers:
  local:
    api: http://localhost:8080/v1   # vLLM box

agent:
  max_turns: 50
"""


def _hermes(home):
    return home / ".hermes" / "config.yaml"


def test_hermes_connect_adds_a_named_provider_and_selects_it(home, state_dir):
    cfg = _hermes(home)
    cfg.parent.mkdir()
    cfg.write_text(HERMES_ORIGINAL)

    _connect("hermes", home, state_dir)

    text = cfg.read_text()
    data = yaml.safe_load(text)
    assert data["model"]["provider"] == "custom:orca"
    assert data["model"]["default"] == "auto"
    assert data["model"]["base_url"] == f"{BASE}/v1"
    orca = data["providers"]["orca"]
    assert orca["api"] == f"{BASE}/v1"
    assert orca["api_key"] == KEY
    assert orca["transport"] == "chat_completions"
    assert orca["default_model"] == "auto"
    assert data["providers"]["local"] == {"api": "http://localhost:8080/v1"}
    assert data["agent"] == {"max_turns": 50}
    # Line edits, not a re-dump: the user's comments survive.
    assert "# Hermes settings — keep this comment" in text
    assert "# vLLM box" in text


def test_hermes_disconnect_restores_the_exact_bytes(home, state_dir):
    cfg = _hermes(home)
    cfg.parent.mkdir()
    cfg.write_text(HERMES_ORIGINAL)
    _connect("hermes", home, state_dir)
    _disconnect("hermes", home, state_dir)
    assert cfg.read_text() == HERMES_ORIGINAL


def test_hermes_disconnect_after_an_edit_reverts_only_our_settings(home, state_dir):
    cfg = _hermes(home)
    cfg.parent.mkdir()
    cfg.write_text(HERMES_ORIGINAL)
    _connect("hermes", home, state_dir)
    cfg.write_text(cfg.read_text().replace("max_turns: 50", "max_turns: 60"))

    _disconnect("hermes", home, state_dir)

    data = yaml.safe_load(cfg.read_text())
    assert data["model"] == {"default": "anthropic/claude-sonnet-4.6", "provider": "openrouter"}
    assert data["providers"] == {"local": {"api": "http://localhost:8080/v1"}}
    assert data["agent"] == {"max_turns": 60}
    assert "# Hermes settings — keep this comment" in cfg.read_text()


def test_hermes_refuses_a_model_that_is_not_a_mapping(home, state_dir):
    cfg = _hermes(home)
    cfg.parent.mkdir()
    cfg.write_text("model: anthropic/claude-sonnet-4.6\n")
    with pytest.raises(ag.AgentConfigError):
        _connect("hermes", home, state_dir)
    assert cfg.read_text() == "model: anthropic/claude-sonnet-4.6\n"


# ── Pi ──────────────────────────────────────────────────────────────────


def test_pi_connect_adds_a_provider_and_makes_it_the_default(home, state_dir):
    agent_dir = home / ".pi" / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "settings.json").write_text(json.dumps({"theme": "dark", "defaultProvider": "anthropic"}))
    (agent_dir / "models.json").write_text(json.dumps({"providers": {"ollama": {"baseUrl": "http://localhost:11434/v1"}}}))

    _connect("pi", home, state_dir)

    models = json.loads((agent_dir / "models.json").read_text())
    assert set(models["providers"]) == {"ollama", "orca"}
    orca = models["providers"]["orca"]
    assert orca["baseUrl"] == f"{BASE}/v1"
    assert orca["api"] == "openai-completions"
    assert orca["apiKey"] == KEY
    assert [m["id"] for m in orca["models"]] == ["auto"]
    settings = json.loads((agent_dir / "settings.json").read_text())
    assert settings == {"theme": "dark", "defaultProvider": "orca", "defaultModel": "auto"}

    _disconnect("pi", home, state_dir)
    assert json.loads((agent_dir / "settings.json").read_text()) == {"theme": "dark", "defaultProvider": "anthropic"}
    assert set(json.loads((agent_dir / "models.json").read_text())["providers"]) == {"ollama"}


# ── OMP ─────────────────────────────────────────────────────────────────

OMP_CONFIG = """\
# omp settings
modelRoles:
  default: anthropic/claude-opus-4-5:high
  smol: "@fast"
theme: dark
"""


def test_omp_connect_adds_a_provider_and_sets_the_default_role(home, state_dir):
    agent_dir = home / ".omp" / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yml").write_text(OMP_CONFIG)

    _connect("omp", home, state_dir)

    models = yaml.safe_load((agent_dir / "models.yml").read_text())
    orca = models["providers"]["orca"]
    assert orca["baseUrl"] == f"{BASE}/v1"
    assert orca["api"] == "openai-completions"
    assert orca["apiKey"] == KEY
    assert [m["id"] for m in orca["models"]] == ["auto"]
    text = (agent_dir / "config.yml").read_text()
    config = yaml.safe_load(text)
    assert config["modelRoles"] == {"default": "orca/auto", "smol": "@fast"}
    assert config["theme"] == "dark"
    assert "# omp settings" in text

    _disconnect("omp", home, state_dir)
    assert (agent_dir / "config.yml").read_text() == OMP_CONFIG
    assert not (agent_dir / "models.yml").exists()


# ── Kilo ────────────────────────────────────────────────────────────────


def test_kilo_connect_uses_its_own_config_and_a_key_file(home, state_dir):
    cfg = home / ".config" / "kilo" / "kilo.json"
    cfg.parent.mkdir(parents=True)
    original = b'{"$schema": "https://app.kilo.ai/config.json", "theme": "kilo"}\n'
    cfg.write_bytes(original)

    _connect("kilo", home, state_dir)

    data = json.loads(cfg.read_text())
    assert data["theme"] == "kilo"
    assert data["model"] == "orca/auto"
    p = data["provider"]["orca"]
    assert p["npm"] == "@ai-sdk/openai-compatible"
    assert p["options"]["baseURL"] == f"{BASE}/v1"
    assert KEY not in cfg.read_text()
    key_file = p["options"]["apiKey"][len("{file:"):-1]
    assert open(key_file).read() == KEY
    assert not (home / ".config" / "opencode").exists()  # Kilo no longer reads OpenCode's folder

    _disconnect("kilo", home, state_dir)
    assert cfg.read_bytes() == original
    assert not os.path.exists(key_file)


# ── OpenClaw ────────────────────────────────────────────────────────────


def _openclaw(home):
    return home / ".openclaw" / "openclaw.json"


def test_openclaw_connect_registers_a_provider_and_the_primary_model(home, state_dir):
    cfg = _openclaw(home)
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({
        "agents": {"defaults": {"model": {"primary": "anthropic/claude-opus-4-6", "fallbacks": ["openai/gpt-5.5"]},
                                "workspace": "~/work"}},
        "models": {"mode": "merge", "providers": {"local": {"baseUrl": "http://localhost:4000/v1"}}},
    }))

    _connect("openclaw", home, state_dir)

    data = json.loads(cfg.read_text())
    assert data["agents"]["defaults"]["model"] == {"primary": "orca/auto", "fallbacks": ["openai/gpt-5.5"]}
    assert data["agents"]["defaults"]["workspace"] == "~/work"
    providers = data["models"]["providers"]
    assert set(providers) == {"local", "orca"}
    orca = providers["orca"]
    assert orca["baseUrl"] == f"{BASE}/v1"
    assert orca["api"] == "openai-completions"
    assert orca["apiKey"] == KEY
    [model] = orca["models"]
    assert model["id"] == "auto"
    # Lite picks the real model per request; tell OpenClaw that's expected.
    assert model["responseModelEquivalent"] is True

    _disconnect("openclaw", home, state_dir)
    data = json.loads(cfg.read_text())
    assert data["agents"]["defaults"]["model"]["primary"] == "anthropic/claude-opus-4-6"
    assert set(data["models"]["providers"]) == {"local"}


def test_openclaw_short_model_string_is_replaced_and_restored(home, state_dir):
    cfg = _openclaw(home)
    cfg.parent.mkdir()
    original = json.dumps({"agents": {"defaults": {"model": "anthropic/claude-opus-4-6"}}}, indent=2) + "\n"
    cfg.write_text(original)

    _connect("openclaw", home, state_dir)
    assert json.loads(cfg.read_text())["agents"]["defaults"]["model"] == "orca/auto"

    _disconnect("openclaw", home, state_dir)
    assert cfg.read_text() == original


def test_openclaw_json5_with_comments_is_refused_untouched(home, state_dir):
    cfg = _openclaw(home)
    cfg.parent.mkdir()
    original = '// my config\n{ agents: { defaults: { workspace: "~/w" } } }\n'
    cfg.write_text(original)
    with pytest.raises(ag.AgentConfigError):
        _connect("openclaw", home, state_dir)
    assert cfg.read_text() == original


# ── Kimi Code ───────────────────────────────────────────────────────────

KIMI_ORIGINAL = """\
default_model = "kimi-code/k3"
telemetry = false

[providers."managed:kimi-code"]
type = "kimi"
base_url = "https://api.kimi.com/coding/v1"
api_key = ""

[models."kimi-code/k3"]
provider = "managed:kimi-code"
model = "k3"
max_context_size = 1048576
"""


def _kimi(home):
    return home / ".kimi-code" / "config.toml"


def test_kimi_code_connect_adds_provider_model_and_default(home, state_dir):
    cfg = _kimi(home)
    cfg.parent.mkdir()
    cfg.write_text(KIMI_ORIGINAL)

    _connect("kimi-code", home, state_dir)

    data = tomllib.loads(cfg.read_text())
    assert data["telemetry"] is False
    assert data["providers"]["managed:kimi-code"]["type"] == "kimi"
    assert data["providers"]["orca"] == {"type": "openai", "base_url": f"{BASE}/v1", "api_key": KEY}
    alias = data["default_model"]
    model = data["models"][alias]
    assert model["provider"] == "orca"
    assert model["model"] == "auto"
    assert model["max_context_size"] > 0
    assert "tool_use" in model["capabilities"]

    _disconnect("kimi-code", home, state_dir)
    assert cfg.read_text() == KIMI_ORIGINAL


# ── Goose ───────────────────────────────────────────────────────────────


def test_goose_connect_adds_a_custom_provider_whose_key_comes_from_a_command(home, state_dir):
    goose = home / ".config" / "goose"
    goose.mkdir(parents=True)
    original = "# goose\nGOOSE_PROVIDER: anthropic\nGOOSE_MODEL: claude-sonnet-4-6\nextensions:\n  developer:\n    enabled: true\n"
    (goose / "config.yaml").write_text(original)

    _connect("goose", home, state_dir)

    provider_file = goose / "custom_providers" / "orca.json"
    p = json.loads(provider_file.read_text())
    assert p["name"] == "orca"
    assert p["engine"] == "openai"
    assert p["base_url"] == f"{BASE}/v1"
    assert [m["name"] for m in p["models"]] == ["auto"]
    assert KEY not in provider_file.read_text()  # Goose never reads keys from its files
    if os.name != "nt":
        out = subprocess.run([p["auth"]["command"], *p["auth"]["args"]], capture_output=True, text=True, check=True)
        assert out.stdout.strip() == KEY
    config = yaml.safe_load((goose / "config.yaml").read_text())
    assert config["GOOSE_PROVIDER"] == "orca"
    assert config["GOOSE_MODEL"] == "auto"
    assert config["extensions"] == {"developer": {"enabled": True}}

    _disconnect("goose", home, state_dir)
    assert (goose / "config.yaml").read_text() == original
    assert not provider_file.exists()


def test_goose_auth_command_for_each_os(tmp_path):
    key = tmp_path / "goose.key"
    assert ag._goose_auth(key, windows=False) == {"command": "cat", "args": [str(key)]}
    assert ag._goose_auth(key, windows=True) == {"command": "cmd", "args": ["/d", "/c", "type", str(key)]}


# ── guided setups ───────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", NEW_MANUAL)
def test_manual_agents_give_the_values_and_where_to_paste_them(home, state_dir, agent_id):
    s = _status(home, state_dir, agent_id)
    assert s.setup == "manual"
    assert s.note and "auto" in s.note
    r = _connect(agent_id, home, state_dir)
    assert r.manual is True
    assert r.base_url == f"{BASE}/v1"
    assert r.api_key == KEY
    assert _snapshot(home) == {}  # nothing is written for a guided setup


def test_zed_note_names_the_provider_settings_and_key_variable():
    note = ag.AGENTS["zed"].note
    assert "openai_compatible" in note
    assert "ORCA_API_KEY" in note


# ── YAML line editor: nested keys ───────────────────────────────────────


def test_yaml_nested_set_keeps_siblings_comments_and_blank_lines(tmp_path):
    raw = b"# top\nmodel:\n  default: a   # keep\n\n  provider: p\nother: 1\n"
    out = ag._apply(raw, "yaml", {"model.provider": "custom:orca", "model.base_url": "http://x/v1"}, tmp_path / "c.yaml")
    text = out.decode()
    assert yaml.safe_load(text) == {"model": {"default": "a", "provider": "custom:orca", "base_url": "http://x/v1"}, "other": 1}
    assert "# top" in text and "# keep" in text


def test_yaml_nested_set_creates_the_parent_and_delete_prunes_it(tmp_path):
    path = tmp_path / "c.yaml"
    out = ag._apply(b"theme: dark\n", "yaml", {"providers.orca": {"api": "http://x/v1", "models": ["auto"]}}, path)
    assert yaml.safe_load(out) == {"theme": "dark", "providers": {"orca": {"api": "http://x/v1", "models": ["auto"]}}}
    back = ag._apply(out, "yaml", {"providers.orca": ag._MISSING}, path)
    assert yaml.safe_load(back) == {"theme": "dark"}


def test_yaml_nested_set_under_a_flow_mapping_still_lands(tmp_path):
    out = ag._apply(b"model: {default: a}\n", "yaml", {"model.provider": "custom:orca"}, tmp_path / "c.yaml")
    assert yaml.safe_load(out) == {"model": {"default": "a", "provider": "custom:orca"}}
