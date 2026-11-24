"""End to end: a real engine, real agent configs, every wire protocol.

One engine process (`orca up`, or the frozen binary in ORCA_E2E_ENGINE) runs
in a throwaway HOME next to a fake OpenAI-compatible provider. The test:

1. connects every automatic agent with the real `orca connect`;
2. reads each agent's written config the way that agent does and sends a
   request in that agent's own protocol (Anthropic Messages for Claude Code,
   Responses for Codex, Gemini for Gemini CLI, Chat Completions for
   OpenCode, Command Code, Aider, Hermes, Pi, OMP, Kilo, OpenClaw, Kimi Code
   and Goose), all reaching the fake provider;
3. checks spend is attributed to each agent, the budget stop returns 429,
   and agent keys can't reach the app API;
4. disconnects everything and checks every config is back byte for byte and
   the agent keys no longer work;
5. drives the panel in Chromium to connect and disconnect an agent.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import site
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import httpx
import pytest
import yaml

from packages.desktop.agents import _GOOSE_DIR, _HERMES_DIR

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e

# Configs the user already had: a connect must keep them and a disconnect
# must put them back exactly.
EXISTING = {
    ".claude/settings.json": '{\n  "theme": "dark"\n}\n',
    ".codex/config.toml": '# my codex settings\nmodel = "gpt-5.1-codex"\n\n[projects."/home/me/app"]\ntrust_level = "trusted"\n',
    ".gemini/settings.json": '{"ui": {"theme": "GitHub"}, "security": {"auth": {"selectedType": "oauth-personal"}}}\n',
    ".aider.conf.yml": "# my aider settings\nauto-commits: false\n",
    f"{_HERMES_DIR}/config.yaml": "# my hermes settings\nmodel:\n  default: anthropic/claude-sonnet-4.6\n  provider: openrouter\n",
    ".kimi-code/config.toml": '# my kimi settings\ndefault_model = "kimi-code/k3"\n\n[providers."managed:kimi-code"]\ntype = "kimi"\n',
    ".openclaw/openclaw.json": '{\n  "agents": {\n    "defaults": {\n      "model": {\n        "primary": "anthropic/claude-opus-4-6"\n      }\n    }\n  }\n}\n',
    f"{_GOOSE_DIR}/config.yaml": "# my goose settings\nGOOSE_PROVIDER: anthropic\nGOOSE_MODEL: claude-sonnet-4-6\n",
}
AGENT_DIRS = [".claude", ".codex", ".gemini", ".config/opencode", ".commandcode", ".cline", _HERMES_DIR, ".pi", ".omp",
              ".config/kilo", ".openclaw", ".kimi-code", _GOOSE_DIR, ".config/zed", ".cursor"]
AUTO_AGENTS = ["claude-code", "codex", "gemini-cli", "opencode", "command-code", "aider",
               "hermes", "pi", "omp", "kilo", "openclaw", "kimi-code", "goose"]
MANUAL_AGENTS = {"cline": "OpenAI Compatible", "zed": "openai_compatible"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str, proc: subprocess.Popen, what: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{what} exited early with {proc.returncode}")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{what} didn't come up at {url}")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    home = tmp / "home"
    for d in AGENT_DIRS:
        (home / d).mkdir(parents=True)
    for rel, text in EXISTING.items():
        (home / rel).write_text(text)
    orca_home = home / ".orcarouter-lite"

    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "ORCAROUTER_", "DATABASE_",
                                "CREDENTIAL_", "API_KEY_", "ORCA_"))}
    up_port, engine_port = _free_port(), _free_port()
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "ORCA_HOME": str(orca_home),
        "ORCA_KEYCHAIN": "0", "ORCA_NO_UPDATE_CHECK": "1", "PYTHONPATH": str(ROOT),
        "OPENAI_API_KEY": "sk-e2e-upstream", "OPENAI_BASE_URL": f"http://127.0.0.1:{up_port}/v1",
        # HOME moves to the throwaway folder; keep packages installed in the
        # runner's user site (pip --user) importable by the engine.
        "PYTHONUSERBASE": site.getuserbase(),
    })
    logs = tmp / "logs"
    logs.mkdir()
    upstream = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.fake_upstream:app", "--port", str(up_port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=open(logs / "upstream.log", "w"), stderr=subprocess.STDOUT,
    )
    frozen = os.environ.get("ORCA_E2E_ENGINE")
    orca = [frozen] if frozen else [sys.executable, "-c", "import sys; from app.orca_cli import entrypoint; sys.argv[0]='orca'; entrypoint()"]
    # Started the way the desktop app starts it: the engine exits when its
    # stdin closes. A frozen one-file engine runs as a launcher plus a child;
    # closing stdin stops both, where terminate() would leave the child
    # holding the exe open (on Windows that blocks signing it afterwards).
    engine = subprocess.Popen([*orca, "up", "--port", str(engine_port), "--exit-with-stdin"], cwd=ROOT, env=env,
                              stdin=subprocess.PIPE, stdout=open(logs / "engine.log", "w"), stderr=subprocess.STDOUT)
    try:
        _wait(f"http://127.0.0.1:{up_port}/_calls", upstream, "fake provider")
        _wait(f"http://127.0.0.1:{engine_port}/health", engine, "engine")
        yield {
            "home": home, "orca_home": orca_home, "env": env, "orca": orca, "logs": logs,
            "base": f"http://127.0.0.1:{engine_port}", "upstream": f"http://127.0.0.1:{up_port}",
            "app_key": (orca_home / "app.key").read_text().strip(),
        }
    finally:
        engine.stdin.close()
        _stop(engine, graceful_seconds=15)
        upstream.terminate()
        _stop(upstream, graceful_seconds=10)


def _stop(proc: subprocess.Popen, *, graceful_seconds: float) -> None:
    """Wait for a process to exit, then kill it and anything it started."""
    try:
        proc.wait(timeout=graceful_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()
    proc.wait(timeout=10)


def _orca(stack, *args) -> subprocess.CompletedProcess:
    return subprocess.run([*stack["orca"], *args], cwd=ROOT, env=stack["env"], capture_output=True, text=True, timeout=60)


def _app(stack, method, path, **kw):
    return httpx.request(method, f"{stack['base']}{path}", headers={"Authorization": f"Bearer {stack['app_key']}"},
                         timeout=30, **kw)


# ── each agent's own view of its config ─────────────────────────────────


def _claude(home):
    env = json.loads((home / ".claude/settings.json").read_text())["env"]
    return env["ANTHROPIC_BASE_URL"], env["ANTHROPIC_AUTH_TOKEN"]


def _codex(home):
    cfg = tomllib.loads((home / ".codex/config.toml").read_text())
    p = cfg["model_providers"][cfg["model_provider"]]
    return p["base_url"], p["experimental_bearer_token"], cfg["model"]


def _gemini(home):
    env = {}
    for line in (home / ".gemini/.env").read_text().splitlines():
        k, _, v = line.partition("=")
        env[k] = v
    return env["GOOGLE_GEMINI_BASE_URL"], env["GEMINI_API_KEY"]


def _opencode(home):
    cfg = json.loads((home / ".config/opencode/opencode.json").read_text())
    provider_id, model = cfg["model"].split("/", 1)
    opts = cfg["provider"][provider_id]["options"]
    ref = opts["apiKey"]
    assert ref.startswith("{file:") and ref.endswith("}")
    return opts["baseURL"], Path(ref[len("{file:"):-1]).read_text().strip(), model


def _command_code(home):
    p = json.loads((home / ".commandcode/providers.json").read_text())["provider"]["orca"]
    cmd = p["apiKey"]
    assert cmd.startswith("!")
    key = subprocess.run(cmd[1:], shell=True, capture_output=True, text=True, check=True).stdout.strip()  # what Command Code runs
    return p["baseURL"], key, next(iter(p["models"]))


def _aider(home):
    cfg = yaml.safe_load((home / ".aider.conf.yml").read_text())
    return cfg["openai-api-base"], cfg["openai-api-key"], cfg["model"].removeprefix("openai/")


def _hermes(home):
    cfg = yaml.safe_load((home / _HERMES_DIR / "config.yaml").read_text())
    kind, _, name = cfg["model"]["provider"].partition(":")
    assert kind == "custom"
    p = cfg["providers"][name]
    return p["api"], p["api_key"], cfg["model"]["default"]


def _pi(home):
    settings = json.loads((home / ".pi/agent/settings.json").read_text())
    p = json.loads((home / ".pi/agent/models.json").read_text())["providers"][settings["defaultProvider"]]
    assert p["api"] == "openai-completions"
    return p["baseUrl"], p["apiKey"], settings["defaultModel"]


def _omp(home):
    provider_id, model = yaml.safe_load((home / ".omp/agent/config.yml").read_text())["modelRoles"]["default"].split("/", 1)
    p = yaml.safe_load((home / ".omp/agent/models.yml").read_text())["providers"][provider_id]
    return p["baseUrl"], p["apiKey"], model


def _kilo(home):
    cfg = json.loads((home / ".config/kilo/kilo.json").read_text())
    provider_id, model = cfg["model"].split("/", 1)
    opts = cfg["provider"][provider_id]["options"]
    return opts["baseURL"], Path(opts["apiKey"][len("{file:"):-1]).read_text().strip(), model


def _openclaw(home):
    cfg = json.loads((home / ".openclaw/openclaw.json").read_text())
    provider_id, model = cfg["agents"]["defaults"]["model"]["primary"].split("/", 1)
    p = cfg["models"]["providers"][provider_id]
    return p["baseUrl"], p["apiKey"], model


def _kimi(home):
    cfg = tomllib.loads((home / ".kimi-code/config.toml").read_text())
    m = cfg["models"][cfg["default_model"]]
    p = cfg["providers"][m["provider"]]
    assert p["type"] == "openai"
    return p["base_url"], p["api_key"], m["model"]


def _goose(home):
    cfg = yaml.safe_load((home / _GOOSE_DIR / "config.yaml").read_text())
    p = json.loads((home / _GOOSE_DIR / "custom_providers" / f"{cfg['GOOSE_PROVIDER']}.json").read_text())
    auth = p["auth"]  # Goose runs this command (no shell) for the key
    key = subprocess.run([auth["command"], *auth["args"]], capture_output=True, text=True, check=True).stdout.strip()
    return p["base_url"], key, cfg["GOOSE_MODEL"]


# ── the tests, in order ─────────────────────────────────────────────────


def test_1_every_automatic_agent_connects(stack):
    listed = _orca(stack, "agents")
    assert listed.returncode == 0, listed.stderr
    for agent in AUTO_AGENTS:
        r = _orca(stack, "connect", agent)
        assert r.returncode == 0, f"{agent}: {r.stderr}"
    for agent, hint in MANUAL_AGENTS.items():
        r = _orca(stack, "connect", agent)
        assert r.returncode == 0 and hint in r.stdout, f"{agent}: {r.stdout}{r.stderr}"  # manual: what to paste
    data = _app(stack, "GET", "/v1/app/agents").json()
    connected = {a["id"] for a in data["agents"] if a["connected"]}
    assert set(AUTO_AGENTS) | set(MANUAL_AGENTS) <= connected
    # The user's own settings are still there.
    assert json.loads((stack["home"] / ".claude/settings.json").read_text())["theme"] == "dark"
    assert "# my codex settings" in (stack["home"] / ".codex/config.toml").read_text()
    assert "# my hermes settings" in (stack["home"] / _HERMES_DIR / "config.yaml").read_text()


def test_2_claude_code_speaks_anthropic_messages(stack):
    base, token = _claude(stack["home"])
    r = httpx.post(f"{base}/v1/messages", headers={"Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01"},
                   json={"model": "gpt-4o-mini", "max_tokens": 64, "messages": [{"role": "user", "content": "ping"}]},
                   timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["content"][0]["text"] == "pong"


def test_3_codex_speaks_responses_streaming(stack):
    base, token, model = _codex(stack["home"])
    with httpx.stream("POST", f"{base}/responses", headers={"Authorization": f"Bearer {token}"}, timeout=60,
                      json={"model": model, "stream": True, "store": False, "instructions": "be brief",
                            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "ping"}]}]}) as r:
        assert r.status_code == 200, r.read()
        events = [line[len("event: "):] for line in r.iter_lines() if line.startswith("event: ")]
    assert events[0] == "response.created"
    assert "response.output_text.delta" in events
    assert events[-1] == "response.completed"


def test_4_gemini_cli_speaks_gemini(stack):
    base, key = _gemini(stack["home"])
    r = httpx.post(f"{base}/v1beta/models/gpt-4o-mini:generateContent", headers={"x-goog-api-key": key},
                   json={"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["candidates"][0]["content"]["parts"][0]["text"] == "pong"
    settings = json.loads((stack["home"] / ".gemini/settings.json").read_text())
    assert settings["security"]["auth"]["selectedType"] == "gateway"


CHAT_AGENTS = {"opencode": _opencode, "command-code": _command_code, "aider": _aider, "hermes": _hermes, "pi": _pi,
               "omp": _omp, "kilo": _kilo, "openclaw": _openclaw, "kimi-code": _kimi, "goose": _goose}


@pytest.mark.parametrize("read", list(CHAT_AGENTS.values()), ids=list(CHAT_AGENTS))
def test_5_chat_completions_agents(stack, read):
    base, key, model = read(stack["home"])
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "messages": [{"role": "user", "content": "ping"}]}, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "pong"


def test_5b_agents_keep_working_with_their_own_model_names(stack):
    # Only an OpenAI key is set up here. Claude Code and Gemini CLI still ask
    # for their own vendors' models; the engine serves those with the best
    # model it can reach and says which one in the response headers.
    base, token = _claude(stack["home"])
    r = httpx.post(f"{base}/v1/messages", headers={"Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01"},
                   json={"model": "claude-sonnet-4-6", "max_tokens": 64,
                         "messages": [{"role": "user", "content": "ping"}]}, timeout=60)
    assert r.status_code == 200, r.text
    assert r.headers["x-orca-requested-model"] == "claude-sonnet-4-6"
    assert not r.headers["x-orca-resolved-model"].startswith("claude")
    gbase, gkey = _gemini(stack["home"])
    r = httpx.post(f"{gbase}/v1beta/models/gemini-2.5-pro:generateContent", headers={"x-goog-api-key": gkey},
                   json={"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}, timeout=60)
    assert r.status_code == 200, r.text
    # The dashboard's own key keeps strict pinned models.
    r = _app(stack, "POST", "/v1/chat/completions",
             json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "ping"}]})
    assert r.status_code >= 400


def test_5c_setup_checks_a_provider_key_before_saving_it(stack):
    good = _app(stack, "POST", "/v1/app/providers/openai/check", json={"api_key": "sk-e2e-upstream"})
    assert good.status_code == 200 and good.json()["status"] == "valid", good.text
    bad = _app(stack, "POST", "/v1/app/providers/openai/check", json={"api_key": "sk-wrong-key"})
    assert bad.status_code == 200 and bad.json()["status"] == "invalid", bad.text
    assert "sk-wrong-key" not in bad.text
    # Agent keys can't use it (it would let a leaked agent key probe other keys).
    _base, token = _claude(stack["home"])
    r = httpx.post(f"{stack['base']}/v1/app/providers/openai/check", headers={"Authorization": f"Bearer {token}"},
                   json={"api_key": "sk-e2e-upstream"}, timeout=10)
    assert r.status_code == 403


def test_6_every_request_reached_the_provider_and_spend_is_per_agent(stack):
    calls = httpx.get(f"{stack['upstream']}/_calls").json()["calls"]
    assert len(calls) >= len(AUTO_AGENTS)
    assert all(c["auth"] == "Bearer sk-e2e-upstream" for c in calls)  # the provider key, never an agent key
    r = _orca(stack, "status", "--json")
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout)
    assert summary["today"]["requests"] >= len(AUTO_AGENTS)
    by_agent = {a["id"]: a for a in summary["agents"]}
    for agent in AUTO_AGENTS:
        assert by_agent[agent]["today_microcents"] > 0, f"no spend recorded for {agent}"


def test_7_agent_keys_cannot_reach_the_app_api(stack):
    _base, token = _claude(stack["home"])
    r = httpx.get(f"{stack['base']}/v1/app/summary", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403


def test_8_the_budget_stop_pauses_agents(stack):
    assert _app(stack, "PUT", "/v1/app/settings", json={"daily_budget_cents": 1, "budget_mode": "stop"}).status_code == 200
    try:
        base, key, model = _opencode(stack["home"])
        r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "messages": [{"role": "user", "content": "ping"}]}, timeout=30)
        assert r.status_code == 429, r.text
        base, token, model = _codex(stack["home"])
        r = httpx.post(f"{base}/responses", headers={"Authorization": f"Bearer {token}"},
                       json={"model": model, "input": "ping"}, timeout=30)
        assert r.status_code == 429, r.text
    finally:
        assert _app(stack, "PUT", "/v1/app/settings", json={"daily_budget_cents": None, "budget_mode": "alert"}).status_code == 200


def test_9_disconnect_restores_every_file_and_revokes_the_keys(stack):
    home = stack["home"]
    old_keys = [_claude(home)[1], _codex(home)[1], _opencode(home)[1]]
    r = _orca(stack, "disconnect", "--all")
    assert r.returncode == 0, r.stderr
    for agent in [*AUTO_AGENTS, *MANUAL_AGENTS]:
        name = next(a["name"] for a in _app(stack, "GET", "/v1/app/agents").json()["agents"] if a["id"] == agent)
        assert name in r.stdout, f"{name} not restored: {r.stdout}"
    for rel, text in EXISTING.items():
        assert (home / rel).read_text() == text, f"{rel} wasn't restored exactly"
    for created in (".gemini/.env", ".config/opencode/opencode.json", ".commandcode/providers.json",
                    ".pi/agent/models.json", ".pi/agent/settings.json", ".omp/agent/models.yml",
                    ".omp/agent/config.yml", ".config/kilo/kilo.json", f"{_GOOSE_DIR}/custom_providers/orca.json"):
        assert not (home / created).exists(), f"{created} should be removed"
    assert not list((stack["orca_home"] / "agents" / "keys").glob("*"))
    for key in old_keys:
        r = httpx.get(f"{stack['base']}/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        assert r.status_code == 401


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10_the_panel_connects_and_disconnects_an_agent(stack):
    script = ROOT / "tests" / "e2e" / "panel_flow.cjs"
    proc = subprocess.Popen(["node", str(script), stack["base"], stack["app_key"], "OpenCode"], cwd=ROOT / "desktop",
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        first = json.loads(proc.stdout.readline() or "{}")
        if not first:
            pytest.skip(f"browser unavailable: {proc.stderr.read()[:300]}")
        assert first["phase"] == "connected" and first["errors"] == []
        cfg = stack["home"] / ".config/opencode/opencode.json"
        assert json.loads(cfg.read_text())["model"] == "orca/auto"
        proc.stdin.write("go\n")
        proc.stdin.flush()
        second = json.loads(proc.stdout.readline())
        assert second["phase"] == "disconnected" and second["errors"] == []
        assert not cfg.exists(), cfg.read_text() if cfg.exists() else ""
    finally:
        proc.kill()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10b_paste_steps_open_where_the_user_can_see_them(stack):
    # With every agent installed the list is long; the values to paste for a
    # one-paste-step agent must still appear on screen, not below the fold.
    script = ROOT / "tests" / "e2e" / "manual_card.cjs"
    r = subprocess.run(["node", str(script), stack["base"], stack["app_key"], "Cursor"], cwd=ROOT / "desktop",
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 and "Executable doesn't exist" in r.stderr:
        pytest.skip("browser unavailable")
    assert r.returncode == 0, r.stderr[-1500:]
    report = json.loads(r.stdout.strip().splitlines()[-1])
    assert report["errors"] == []
    assert report["title"] == "Finish in Cursor"
    assert report["onScreen"], report["box"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10c_setup_checks_keys_with_the_provider(stack):
    script = ROOT / "tests" / "e2e" / "setup_flow.cjs"
    r = subprocess.run(["node", str(script), stack["base"], stack["app_key"], "sk-e2e-upstream"], cwd=ROOT / "desktop",
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 and "Executable doesn't exist" in r.stderr:
        pytest.skip("browser unavailable")
    assert r.returncode == 0, r.stderr[-1500:]
    report = json.loads(r.stdout.strip().splitlines()[-1])
    assert report["errors"] == []
    assert {"Anthropic", "OpenAI", "Google Gemini", "DeepSeek", "xAI Grok"} <= set(report["providers"])
    assert "two OpenAI keys" in report["duplicate"]
    assert "rejected" in report["rejected"] and report["doneAfterReject"] is False
    assert report["done"] is True
    assert report["startAtLogin"] is True  # on by default
    assert _app(stack, "GET", "/v1/app/settings").json()["start_at_login"] is True
    keys = _app(stack, "GET", "/v1/providers").json()
    listed = keys.get("providers", keys) if isinstance(keys, dict) else keys
    assert any((p.get("provider") if isinstance(p, dict) else p) == "openai" for p in listed)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10d_disconnect_all_from_the_panel(stack):
    for agent in ("claude-code", "opencode"):
        assert _orca(stack, "connect", agent).returncode == 0
    key = _opencode(stack["home"])[1]
    script = ROOT / "tests" / "e2e" / "disconnect_all.cjs"
    r = subprocess.run(["node", str(script), stack["base"], stack["app_key"]], cwd=ROOT / "desktop",
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 and "Executable doesn't exist" in r.stderr:
        pytest.skip("browser unavailable")
    assert r.returncode == 0, r.stderr[-1500:]
    report = json.loads(r.stdout.strip().splitlines()[-1])
    assert report["errors"] == []
    assert report["label"] == "Disconnect all 2" and "again" in report["armed"]
    assert "Claude Code" in report["toast"] and "OpenCode" in report["toast"]
    agents = _app(stack, "GET", "/v1/app/agents").json()["agents"]
    assert not any(a["connected"] for a in agents)
    assert (stack["home"] / ".claude/settings.json").read_text() == EXISTING[".claude/settings.json"]
    r = httpx.get(f"{stack['base']}/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
    assert r.status_code == 401


def test_11_nothing_leaked_into_the_engine_log(stack):
    log = (stack["logs"] / "engine.log").read_text()
    for secret in ("sk-e2e-upstream", stack["app_key"]):
        assert secret not in log
    assert shlex.quote  # keep the import used for readers of _command_code
