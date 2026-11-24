"""End to end: a real engine, real agent configs, every wire protocol.

One engine process (`orca up`, or the frozen binary in ORCA_E2E_ENGINE) runs
in a throwaway HOME next to a fake OpenAI-compatible provider. The test:

1. connects every automatic agent with the real `orca connect`;
2. reads each agent's written config the way that agent does and sends a
   request in that agent's own protocol (Anthropic Messages for Claude Code,
   Responses for Codex, Gemini for Gemini CLI, Chat Completions for
   OpenCode, Command Code and Aider), all reaching the fake provider;
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

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e

# Configs the user already had: a connect must keep them and a disconnect
# must put them back exactly.
EXISTING = {
    ".claude/settings.json": '{\n  "theme": "dark"\n}\n',
    ".codex/config.toml": '# my codex settings\nmodel = "gpt-5.1-codex"\n\n[projects."/home/me/app"]\ntrust_level = "trusted"\n',
    ".gemini/settings.json": '{"ui": {"theme": "GitHub"}, "security": {"auth": {"selectedType": "oauth-personal"}}}\n',
    ".aider.conf.yml": "# my aider settings\nauto-commits: false\n",
}
AGENT_DIRS = [".claude", ".codex", ".gemini", ".config/opencode", ".commandcode", ".cline"]
AUTO_AGENTS = ["claude-code", "codex", "gemini-cli", "opencode", "command-code", "aider"]


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
    engine = subprocess.Popen([*orca, "up", "--port", str(engine_port)], cwd=ROOT, env=env,
                              stdout=open(logs / "engine.log", "w"), stderr=subprocess.STDOUT)
    try:
        _wait(f"http://127.0.0.1:{up_port}/v1/models", upstream, "fake provider")
        _wait(f"http://127.0.0.1:{engine_port}/health", engine, "engine")
        yield {
            "home": home, "orca_home": orca_home, "env": env, "orca": orca, "logs": logs,
            "base": f"http://127.0.0.1:{engine_port}", "upstream": f"http://127.0.0.1:{up_port}",
            "app_key": (orca_home / "app.key").read_text().strip(),
        }
    finally:
        for p in (engine, upstream):
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


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


# ── the tests, in order ─────────────────────────────────────────────────


def test_1_every_automatic_agent_connects(stack):
    listed = _orca(stack, "agents")
    assert listed.returncode == 0, listed.stderr
    for agent in AUTO_AGENTS:
        r = _orca(stack, "connect", agent)
        assert r.returncode == 0, f"{agent}: {r.stderr}"
    r = _orca(stack, "connect", "cline")
    assert r.returncode == 0 and "OpenAI Compatible" in r.stdout  # manual: shows what to paste
    data = _app(stack, "GET", "/v1/app/agents").json()
    connected = {a["id"] for a in data["agents"] if a["connected"]}
    assert set(AUTO_AGENTS) | {"cline"} <= connected
    # The user's own settings are still there.
    assert json.loads((stack["home"] / ".claude/settings.json").read_text())["theme"] == "dark"
    assert "# my codex settings" in (stack["home"] / ".codex/config.toml").read_text()


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


@pytest.mark.parametrize("read", [_opencode, _command_code, _aider], ids=["opencode", "command-code", "aider"])
def test_5_chat_completions_agents(stack, read):
    base, key, model = read(stack["home"])
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "messages": [{"role": "user", "content": "ping"}]}, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "pong"


def test_6_every_request_reached_the_provider_and_spend_is_per_agent(stack):
    calls = httpx.get(f"{stack['upstream']}/_calls").json()["calls"]
    assert len(calls) >= 6
    assert all(c["auth"] == "Bearer sk-e2e-upstream" for c in calls)  # the provider key, never an agent key
    r = _orca(stack, "status", "--json")
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout)
    assert summary["today"]["requests"] >= 6
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
    for agent in [*AUTO_AGENTS, "cline"]:
        r = _orca(stack, "disconnect", agent)
        assert r.returncode == 0, f"{agent}: {r.stderr}"
    for rel, text in EXISTING.items():
        assert (home / rel).read_text() == text, f"{rel} wasn't restored exactly"
    for created in (".gemini/.env", ".config/opencode/opencode.json", ".commandcode/providers.json"):
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


def test_11_nothing_leaked_into_the_engine_log(stack):
    log = (stack["logs"] / "engine.log").read_text()
    for secret in ("sk-e2e-upstream", stack["app_key"]):
        assert secret not in log
    assert shlex.quote  # keep the import used for readers of _command_code
