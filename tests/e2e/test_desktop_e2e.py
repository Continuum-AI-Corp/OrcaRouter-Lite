"""End to end: a real engine, real agent configs, every wire protocol.

One engine process (`orca up`, or the frozen binary in ORCA_E2E_ENGINE) runs
in a throwaway HOME next to a fake OpenAI-compatible provider. The test:

1. connects every automatic agent with the real `orca connect`;
2. reads each agent's written config the way that agent does and sends a
   request in that agent's own protocol (Anthropic Messages for Claude Code,
   Responses for Codex, Gemini for Gemini CLI, Chat Completions for
   OpenCode, Command Code, Aider, Hermes, Pi, OMP, Kilo, OpenClaw, Kimi Code
   and Goose), all reaching the fake provider;
3. checks spend is attributed to each agent, the budget stop refuses agents,
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
from pathlib import Path

import httpx
import pytest
import yaml

from packages.desktop import agent_test
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
                                "CREDENTIAL_", "API_KEY_", "ORCA_", "OLLAMA_", "LMSTUDIO_", "LLAMACPP_",
                                "ARTIFICIAL_"))}
    up_port, engine_port, ollama_port, closed_port = _free_port(), _free_port(), _free_port(), _free_port()
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "ORCA_HOME": str(orca_home),
        "ORCA_KEYCHAIN": "0", "ORCA_NO_UPDATE_CHECK": "1", "PYTHONPATH": str(ROOT),
        "OPENAI_API_KEY": "sk-e2e-upstream", "OPENAI_BASE_URL": f"http://127.0.0.1:{up_port}/v1",
        # OrcaRouter and Anthropic on the fake provider (the fake plays
        # OrcaRouter under /orca; no keys for them until a test adds one), and
        # a fake Ollama that a test starts on this port. Never probe runtimes
        # really running on this machine.
        "ORCAROUTER_BASE_URL": f"http://127.0.0.1:{up_port}/orca/v1",
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{up_port}/anthropic",
        "OLLAMA_HOST": f"127.0.0.1:{ollama_port}",
        "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{closed_port}",
        "LLAMACPP_BASE_URL": f"http://127.0.0.1:{closed_port}",
        # HOME moves to the throwaway folder; keep packages installed in the
        # runner's user site (pip --user) importable by the engine.
        "PYTHONUSERBASE": site.getuserbase(),
    })
    logs = tmp / "logs"
    logs.mkdir()
    # Where the app sends the engine's output; diagnostics read it there.
    orca_home.mkdir(mode=0o700)
    engine_log = orca_home / "engine.log"
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
                              stdin=subprocess.PIPE, stdout=open(engine_log, "w"), stderr=subprocess.STDOUT)
    try:
        _wait(f"http://127.0.0.1:{up_port}/_calls", upstream, "fake provider")
        _wait(f"http://127.0.0.1:{engine_port}/health", engine, "engine")
        yield {
            "home": home, "orca_home": orca_home, "env": env, "orca": orca, "logs": logs, "engine_log": engine_log,
            "base": f"http://127.0.0.1:{engine_port}", "upstream": f"http://127.0.0.1:{up_port}",
            "app_key": (orca_home / "app.key").read_text().strip(), "ollama_port": ollama_port,
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


def _read(home, agent_id):
    """The agent's base URL, key and model, read the way the agent reads its
    config (packages/desktop/agent_test.py, which the app's Test button uses)."""
    return agent_test.read_endpoint(agent_id, home=home, state_dir=home / ".orcarouter-lite" / "agents")


def _claude(home):
    ep = _read(home, "claude-code")
    return ep.base_url, ep.key


def _codex(home):
    ep = _read(home, "codex")
    return ep.base_url, ep.key, ep.model


def _gemini(home):
    ep = _read(home, "gemini-cli")
    return ep.base_url, ep.key


def _chat_reader(agent_id):
    def read(home):
        ep = _read(home, agent_id)
        return ep.base_url, ep.key, ep.model
    return read


def _command_code(home):
    base, key, model = _chat_reader("command-code")(home)
    cmd = json.loads((home / ".commandcode/providers.json").read_text())["provider"]["orca"]["apiKey"]
    assert cmd.startswith("!")
    ran = subprocess.run(cmd[1:], shell=True, capture_output=True, text=True, check=True).stdout.strip()  # what Command Code runs
    assert ran == key
    return base, key, model


def _goose(home):
    base, key, model = _chat_reader("goose")(home)
    cfg = yaml.safe_load((home / _GOOSE_DIR / "config.yaml").read_text())
    auth = json.loads((home / _GOOSE_DIR / "custom_providers" / f"{cfg['GOOSE_PROVIDER']}.json").read_text())["auth"]
    ran = subprocess.run([auth["command"], *auth["args"]], capture_output=True, text=True, check=True).stdout.strip()
    assert ran == key  # Goose runs this command (no shell) for the key
    return base, key, model


_opencode = _chat_reader("opencode")
_aider = _chat_reader("aider")
_hermes = _chat_reader("hermes")
_pi = _chat_reader("pi")
_omp = _chat_reader("omp")
_kilo = _chat_reader("kilo")
_openclaw = _chat_reader("openclaw")
_kimi = _chat_reader("kimi-code")


def _browser(script: str, *args: str) -> dict:
    """Run a Playwright script from tests/e2e and return its JSON report;
    skip where Playwright or its browser isn't installed (as on CI runners)."""
    r = subprocess.run(["node", str(ROOT / "tests" / "e2e" / script), *args], cwd=ROOT / "desktop",
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 and ("Cannot find module 'playwright'" in r.stderr or "Executable doesn't exist" in r.stderr):
        pytest.skip("playwright or its browser isn't installed")
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


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
    assert settings["security"]["auth"]["selectedType"] == "gemini-api-key"


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


def _sse(r):
    events, kind = [], None
    for line in r.iter_lines():
        if line.startswith("event: "):
            kind = line[len("event: "):]
        elif line.startswith("data: ") and line != "data: [DONE]":
            events.append((kind, json.loads(line[len("data: "):])))
    return events


def test_5d_claude_code_tool_use_round_trip_streaming(stack):
    base, token = _claude(stack["home"])
    headers = {"Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01"}
    tools = [{"name": "read_file", "description": "Read a file",
              "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}]
    ask = {"role": "user", "content": "What's in the README?"}
    with httpx.stream("POST", f"{base}/v1/messages", headers=headers, timeout=60,
                      json={"model": "claude-sonnet-4-6", "max_tokens": 256, "stream": True, "tools": tools,
                            "messages": [ask]}) as r:
        assert r.status_code == 200, r.read()
        events = _sse(r)
    starts = [d["content_block"] for k, d in events if k == "content_block_start"]
    tool = next(b for b in starts if b["type"] == "tool_use")
    assert tool["name"] == "read_file"
    args = "".join(d["delta"]["partial_json"] for k, d in events
                   if k == "content_block_delta" and d["delta"]["type"] == "input_json_delta")
    assert json.loads(args) == {"path": "README.md"}
    assert any(k == "message_delta" and d["delta"]["stop_reason"] == "tool_use" for k, d in events)
    # Send the tool's result back, as Claude Code does.
    r = httpx.post(f"{base}/v1/messages", headers=headers, timeout=60, json={
        "model": "claude-sonnet-4-6", "max_tokens": 256, "tools": tools, "messages": [
            ask,
            {"role": "assistant", "content": [{"type": "tool_use", "id": tool["id"], "name": "read_file",
                                                "input": {"path": "README.md"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool["id"], "content": "# Orca"}]},
        ]})
    assert r.status_code == 200, r.text
    assert r.json()["content"][0]["text"] == "done: # Orca"


def test_5e_gemini_cli_function_call(stack):
    base, key = _gemini(stack["home"])
    r = httpx.post(f"{base}/v1beta/models/gemini-2.5-pro:generateContent", headers={"x-goog-api-key": key}, timeout=60,
                   json={"contents": [{"role": "user", "parts": [{"text": "What's in the README?"}]}],
                         "tools": [{"functionDeclarations": [{"name": "read_file", "description": "Read a file",
                                    "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING"}}}}]}]})
    assert r.status_code == 200, r.text
    call = r.json()["candidates"][0]["content"]["parts"][0]["functionCall"]
    assert call == {"name": "read_file", "args": {"path": "README.md"}}


def test_5f_codex_function_call_streaming(stack):
    base, token, model = _codex(stack["home"])
    with httpx.stream("POST", f"{base}/responses", headers={"Authorization": f"Bearer {token}"}, timeout=60,
                      json={"model": model, "stream": True, "store": False, "input": "What's in the README?",
                            "tools": [{"type": "function", "name": "read_file", "description": "Read a file",
                                       "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}]}) as r:
        assert r.status_code == 200, r.read()
        events = _sse(r)
    done = [d["item"] for k, d in events if k == "response.output_item.done"]
    call = next(i for i in done if i["type"] == "function_call")
    assert call["name"] == "read_file" and json.loads(call["arguments"]) == {"path": "README.md"}
    assert events[-1][0] == "response.completed"


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


def test_6b_the_test_button_works_for_every_agent(stack):
    # D4: the engine reads each agent's config the way the agent does and
    # sends one tiny request back to its own port with the agent's key.
    for agent in AUTO_AGENTS:
        r = _app(stack, "POST", f"/v1/app/agents/{agent}/test")
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["ok"] is True, f"{agent}: {result}"
        assert result["model"] and result["seconds"] is not None and result["error"] is None
        assert result["config_path"].startswith("~/"), result
    assert stack["app_key"] not in r.text
    for agent, _hint in MANUAL_AGENTS.items():
        result = _app(stack, "POST", f"/v1/app/agents/{agent}/test").json()
        assert result["ok"] is None and "Paste the key" in result["error"]


def test_6c_the_test_button_explains_a_broken_key(stack):
    # The config still holds the key Orca wrote, but the engine no longer
    # accepts it (as when the Orca folder was reset).
    import sqlite3

    db_path = stack["orca_home"] / "orca.db"
    with sqlite3.connect(db_path) as db:
        (key_id,) = db.execute("SELECT id FROM api_keys WHERE name = 'agent:claude-code' AND revoked_at IS NULL").fetchone()

    def set_revoked(revoked: bool) -> None:
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ?",
                       ("2026-01-01 00:00:00" if revoked else None, key_id))

    set_revoked(True)
    try:
        result = _app(stack, "POST", "/v1/app/agents/claude-code/test").json()
    finally:
        set_revoked(False)
    assert result["ok"] is False
    assert result["error"] == "Orca didn't accept Claude Code's key. Connect Claude Code again, then test."
    assert _app(stack, "POST", "/v1/app/agents/claude-code/test").json()["ok"] is True


def test_6d_the_test_button_explains_a_stopped_provider(stack):
    httpx.post(f"{stack['upstream']}/_state", json={"openai": "down"}, timeout=10)
    try:
        r = _app(stack, "POST", "/v1/app/agents/opencode/test")
    finally:
        httpx.post(f"{stack['upstream']}/_state", json={"openai": "ok"}, timeout=10)
    result = r.json()
    assert result["ok"] is False, result
    assert result["error"].startswith("OpenAI isn't answering right now"), result


def test_6e_diagnostics_leave_out_keys_prompts_and_home(stack):
    # D8: after the real requests above (and their keys), from the engine
    # and from the CLI.
    home = stack["home"]
    secrets = ["sk-e2e-upstream", stack["app_key"], _claude(home)[1], _codex(home)[1], _opencode(home)[1]]
    r = _app(stack, "GET", "/v1/app/diagnostics")
    assert r.status_code == 200, r.text
    cli = _orca(stack, "diagnostics")
    assert cli.returncode == 0, cli.stderr
    for text in (r.json()["text"], cli.stdout):
        assert text.startswith("OrcaRouter Lite ")
        for agent in AUTO_AGENTS:
            assert agent in text
        for secret in secrets:
            assert secret not in text
        assert "What's in the README" not in text and "Reply with one word" not in text
        assert str(home) not in text


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
        assert r.status_code == 400, r.text
        base, token, model = _codex(stack["home"])
        r = httpx.post(f"{base}/responses", headers={"Authorization": f"Bearer {token}"},
                       json={"model": model, "input": "ping"}, timeout=30)
        assert r.status_code == 400, r.text
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
    report = _browser("manual_card.cjs", stack["base"], stack["app_key"], "Cursor")
    assert report["errors"] == []
    assert report["title"] == "Finish in Cursor"
    assert report["onScreen"], report["box"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10c_setup_checks_keys_with_the_provider(stack):
    report = _browser("setup_flow.cjs", stack["base"], stack["app_key"], "sk-e2e-upstream")
    assert report["errors"] == []
    # P1: setup's providers are the engine's list, in its order, the new five marked.
    supported = _app(stack, "GET", "/v1/providers/supported").json()["providers"]
    assert report["providers"] == [p["name"] for p in supported if not p.get("hosted")]
    assert report["newProviders"] == ["Moonshot (Kimi)", "Qwen (DashScope)", "MiniMax", "Z.ai (GLM)", "OpenRouter"]
    assert report["rows"] == ["OpenAI"] and report["placeholders"] == ["OpenAI key (sk-…)"]
    assert report["focusedAfterPick"] == "key-minimax"
    assert report["minimaxNote"] == "MiniMax has no key check, so Orca saves it without checking."
    assert report["rowsWithAnthropic"] == ["Anthropic", "OpenAI", "MiniMax"]  # the list's order
    assert report["rowsAfterUnpick"] == ["OpenAI", "MiniMax"]
    assert "rejected" in report["rejected"] and report["doneAfterReject"] is False
    assert report["done"] is True
    assert "OpenAI key: Checked and saved" in report["results"]
    assert "MiniMax key: Saved without checking" in report["results"]
    assert report["startAtLogin"] is True  # on by default
    assert _app(stack, "GET", "/v1/app/settings").json()["start_at_login"] is True
    listed = {p["provider"] for p in _app(stack, "GET", "/v1/providers").json()["providers"]}
    assert {"openai", "minimax"} <= listed
    assert _app(stack, "DELETE", "/v1/providers/minimax").status_code == 204  # keep later routing as it was


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10d_disconnect_all_from_the_panel(stack):
    for agent in ("claude-code", "opencode"):
        assert _orca(stack, "connect", agent).returncode == 0
    key = _opencode(stack["home"])[1]
    report = _browser("disconnect_all.cjs", stack["base"], stack["app_key"])
    assert report["errors"] == []
    assert report["label"] == "Disconnect all 2 agents" and "again" in report["armed"]
    assert "Claude Code" in report["toast"] and "OpenCode" in report["toast"]
    agents = _app(stack, "GET", "/v1/app/agents").json()["agents"]
    assert not any(a["connected"] for a in agents)
    assert (stack["home"] / ".claude/settings.json").read_text() == EXISTING[".claude/settings.json"]
    r = httpx.get(f"{stack['base']}/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
    assert r.status_code == 401


CLIPBOARD_KEY = "sk-orca-e2e-clipboard-key-7f3a"  # the fake OrcaRouter accepts it
DECLINED_KEY = "sk-orca-declined-by-the-user-0001"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10e_setup_puts_orcarouter_first_and_offers_a_key_from_the_clipboard(stack):
    report = _browser("setup_hosted.cjs", stack["base"], stack["app_key"], CLIPBOARD_KEY, DECLINED_KEY)
    assert report["errors"] == []
    # H0: three choices, OrcaRouter first and selected, free models, no "$5".
    assert report["choices"] == ["OrcaRouter gateway", "My own API keys", "My company's gateway"]
    assert report["descriptions"] == [
        "One key for every model, with failover between providers. Agents start on free models; paid models only when you choose them.",
        "Requests go straight to each provider.",
        "Use the key your platform team gave you.",
    ]
    assert report["pill"] == "Free models" and report["selected"] == "hosted"
    assert "$5" not in report["page"] and "Shown when" not in report["page"]
    # H1: the key page opens with its source tag.
    assert len(report["opened"]) == 1 and "ref=lite-setup" in report["opened"][0]
    assert report["opened"][0].startswith("https://www.orcarouter.ai/")
    # Offered only on focus, only for a key, only once; "No" leaves the clipboard.
    assert report["offerForText"] is False and report["offerBeforeFocus"] is False
    assert report["offerText"] == "OrcaRouter key found on your clipboard (sk-orca-…0001). Use it?"
    assert report["offerAfterNo"] is False and report["offerAgain"] is False
    assert report["clearedAfterNo"] == 0 and report["clipAfterNo"] == DECLINED_KEY
    assert "(sk-orca-…7f3a)" in report["secondOffer"]
    assert report["saved"] == "Key works. Checked with OrcaRouter and saved in your keychain. The clipboard was cleared."
    assert report["cleared"] == 1
    listed = _app(stack, "GET", "/v1/providers").json()["providers"]
    assert any(p["provider"] == "orcarouter" for p in listed)
    assert "OrcaRouter key: Checked and saved" in report["results"]
    # V6: the badge, tagged, copied as Markdown.
    badge = ("[![budgeted with OrcaRouter Lite](https://img.shields.io/badge/budgeted%20with-OrcaRouter%20Lite-2D7FF9)]"
             "(https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-badge)")
    assert report["badge"] == badge and report["copied"] == badge and report["copyLabel"] == "Copied"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10e2_add_orcarouter_backup_turns_on_paid_models_only_when_asked(stack):
    try:
        report = _browser("setup_paid.cjs", stack["base"], stack["app_key"], CLIPBOARD_KEY)
    finally:
        _app(stack, "PUT", "/v1/app/settings", json={"hosted_models": "free"})
    assert report["errors"] == []
    assert report["before"] == "free"  # 10e saved a key without the request: still free
    assert report["selected"] == "hosted"
    assert report["saved"].endswith(
        "Paid models are on as a backup: free models and your own keys still come first.")
    assert report["afterClipboard"] == "all"
    assert "OrcaRouter paid models: On as a backup" in report["results"] and report["afterPaste"] == "all"
    assert report["withoutRequest"] == "free" and "OrcaRouter paid models" not in report["resultsWithout"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10f_setup_offers_local_models_only_when_one_is_running(stack):
    env = {**stack["env"]}
    ollama = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.fake_ollama:app", "--port", str(stack["ollama_port"]),
         "--log-level", "warning"], cwd=ROOT, env=env, stdout=open(stack["logs"] / "ollama.log", "w"),
        stderr=subprocess.STDOUT)
    try:
        _wait(f"http://127.0.0.1:{stack['ollama_port']}/_calls", ollama, "fake ollama")
        found = _app(stack, "POST", "/v1/app/local/refresh").json()
        assert any(r["id"] == "ollama" and r["running"] for r in found["runtimes"]), found
        report = _browser("setup_local.cjs", stack["base"], stack["app_key"])
        assert report["errors"] == []
        local_hosted = ("Ollama first, OrcaRouter for the rest",
                        "Quick requests stay on this computer. Harder ones go to OrcaRouter's free models first, "
                        "paid ones only when needed.")
        rest = ["OrcaRouter gateway", "My own API keys", "My company's gateway"]
        # No cloud key: "Only this computer" really is only this computer.
        assert report["firstRunChoices"] == [local_hosted[0], "Only this computer", *rest]
        assert report["firstRunDescriptions"][:2] == [local_hosted[1], "Free and offline. Hard requests may fail."]
        # Own keys only: they stay as fallbacks, so the choice says so.
        assert report["ownKeysChoices"] == [local_hosted[0], "Ollama first, your keys for the rest", *rest]
        assert report["ownKeysDescriptions"][1] == "Local first; your keys handle the rest."
        # With an OrcaRouter key the first choice already is "local first, then the cloud".
        assert report["choices"] == [local_hosted[0], *rest]
        assert report["descriptions"][0] == local_hosted[1]
        assert "Free and offline" not in report["page"]
        # A returning user keeps their route until they pick another (a first run
        # starts on the local choice; see desktop/tests/setup.test.mjs).
        assert report["selected"] == "hosted"
        assert report["firstRunSelected"] == "local_hosted"
        assert report["keyStepUnderLocal"] is True
        assert report["afterArrow"] == "local_only"  # arrow keys move between the choices
        assert "Shown when" not in report["page"] and "$5" not in report["page"]
        assert "Local models: Ollama first, then OrcaRouter" in report["results"]
        assert _app(stack, "GET", "/v1/routing").json()["strategy"] == "local_first"
        assert report["reopenedSelected"] == "local_hosted"
    finally:
        _app(stack, "PUT", "/v1/routing", json={"strategy": "balanced"})
        ollama.terminate()
        _stop(ollama, graceful_seconds=10)
        _app(stack, "POST", "/v1/app/local/refresh")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10f2_setup_opens_at_the_step_the_panel_asked_for(stack):
    report = _browser("setup_step.cjs", stack["base"], stack["app_key"])
    assert report["errors"] == []
    assert report["fromHash"] == "company" and report["fromStorage"] == "company"
    assert report["storageLeft"] is None  # used once
    assert report["nextOpen"] != "company" and report["stale"] != "company"
    assert report["keyKept"] is True and "step=" not in report["hashAfter"]
    assert report["gatewayInertWhenSelected"] is False and report["gatewayInertWhenNot"] is True
    assert report["chipsInertWhenSelected"] is False
    # Already open: the request still lands, and is used up.
    assert report["whileOpen"] == "company" and report["whileOpenLeft"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10g_a_setup_link_fills_in_setup_only_after_the_user_continues(stack):
    report = _browser("setup_link.cjs", stack["base"], stack["app_key"])
    assert report["errors"] == []
    assert report["text"] == "A link wants to set up Orca: connect Claude Code, Codex; daily budget $5.00"
    assert report["dialog"] == {"role": "dialog", "modal": "true"}
    assert report["focused"] == "link-continue"
    # Cancel changes nothing; Escape closes it too.
    assert report["afterCancel"] == report["before"] and report["budgetAfterCancel"] == report["budgetBefore"]
    assert report["escapeClosed"] is True
    # Continue ticks exactly the linked agents and fills in the budget; nothing is connected.
    assert report["afterContinue"] == ["claude-code", "codex"]
    assert report["budgetAfterContinue"] == "5"
    assert report["button"] == "Connect 2 agents"
    agents = _app(stack, "GET", "/v1/app/agents").json()["agents"]
    assert not any(a["connected"] for a in agents if a["id"] in ("claude-code", "codex"))
    assert _app(stack, "GET", "/v1/app/settings").json()["daily_budget_cents"] != 500


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10h_the_dashboard_in_the_app(stack):
    report = _browser("dashboard_flow.cjs", stack["base"], stack["app_key"])
    assert report["errors"] == []
    # D7: in the app, the Quality tab points to Orca's Settings, not a .env.
    assert "Settings" in report["desktopSteps"] and ".env" not in report["desktopSteps"]
    assert "No restart" in report["desktopSteps"]
    # A server (no /v1/app) keeps the .env instructions.
    assert ".env" in report["serverSteps"] and "ARTIFICIAL_ANALYSIS_API_KEY" in report["serverSteps"]
    # P1: the Providers tab lists the engine's providers, the new five marked.
    supported = _app(stack, "GET", "/v1/providers/supported").json()["providers"]
    assert report["options"] == [p["id"] for p in supported]
    assert report["newChips"] == [p["name"] for p in supported if p.get("new")]
    assert report["moonshotPlaceholder"] == "sk-…"  # the key's shape, from the same list
    assert set(report["newChips"]) == {"Moonshot (Kimi)", "Qwen (DashScope)", "MiniMax", "Z.ai (GLM)", "OpenRouter"}
    # In the app OrcaRouter serves free models until paid ones are turned on: say that.
    assert "OrcaRouter's free models are ready; paid models only when you turn them on in Orca." in report["hostedActive"]
    assert "reachable" not in report["hostedActive"]
    assert "Every catalog model is reachable" in report["serverHostedActive"]
    # H0: the hosted card's links carry the dashboard's ref.
    for href in report["hostedLinks"]:
        assert href.startswith("https://www.orcarouter.ai/") and href.endswith("ref=lite-dashboard"), href


# ── the panel's roadmap features (tests/e2e/panel_features.cjs) ─────────


def _panel(stack, scenario: str) -> dict:
    report = _browser("panel_features.cjs", stack["base"], stack["app_key"], scenario)
    assert report["errors"] == [], report["errors"]
    return report


def _claude_request(stack, model="claude-sonnet-4-6"):
    base, token = _claude(stack["home"])
    return httpx.post(f"{base}/v1/messages", headers={"Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01"},
                      json={"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]},
                      timeout=60)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10p_the_agent_sheet(stack):
    # The panel tests start without the OrcaRouter key the setup tests saved
    # (the backup offer only shows then).
    _app(stack, "DELETE", "/v1/providers/orcarouter")
    # D2, D3, D4, D5, H3 in the panel.
    for agent in ("claude-code", "codex"):
        assert _orca(stack, "connect", agent).returncode == 0
    assert _claude_request(stack).status_code == 200  # only an OpenAI key: another model answers (H3)
    codex_cfg = stack["home"] / ".codex/config.toml"
    codex_cfg.write_text('model = "gpt-5.1-codex"\n')  # as Codex's own setup would (D5)
    try:
        report = _panel(stack, "agent")
        assert "Works." in report["reconnectToast"], report
        assert "orca" in codex_cfg.read_text().lower()
        assert "Works." in report["connectToast"], report  # tested right after Connect (D4)
        assert report["hint"].startswith("Claude Code asked for claude-sonnet-4-6"), report
        assert "You have no Anthropic key" in report["hint"]
        assert report["requests"] >= 1 and report["firstRequest"]
        assert report["test"].startswith("Works. Answered in"), report
        assert "~/.claude/settings.json" in report["test"]
        assert "Saved." in report["budgetStatus"] and "$5.00" in report["budgetStatus"]
        assert report["pickerGroups"][0] == "Your keys", report
        assert report["pickerClosedByEscape"] is True
        assert report["mainShown"] == "gpt-4o-mini"
        assert "needs an OrcaRouter key" in report["needsKey"], report
        assert report["focusAfterKeep"] == "view-title"  # the note went away while focused
        assert report["backOnHome"] is True
        settings = _app(stack, "GET", "/v1/app/settings").json()
        assert settings["agent_budgets"] == {"claude-code": 500}
        assert settings["agent_models"]["claude-code"] == {"main": "gpt-4o-mini", "background": None,
                                                         "fallback_to_auto": False}
    finally:
        _app(stack, "PUT", "/v1/app/settings", json={"agent_budgets": {}, "agent_models": {}, "kept_substitutions": []})


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10p2_a_failed_test_reads_as_words_and_disconnect_keeps_focus(stack):
    httpx.post(f"{stack['upstream']}/_state", json={"openai": "down"}, timeout=10)
    try:
        report = _panel(stack, "testfail")
    finally:
        httpx.post(f"{stack['upstream']}/_state", json={"openai": "ok"}, timeout=10)
    assert report["test"].startswith("OpenAI isn't answering right now"), report
    assert "null" not in report["test"] and "err" in report["testTone"]
    assert report["focusAfterDisconnect"] == "agents-h"
    assert not any(a["connected"] for a in _app(stack, "GET", "/v1/app/agents").json()["agents"] if a["id"] == "opencode")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10q_the_backup_offer_after_real_failures_and_not_now(stack):
    # H2: Anthropic overloaded, and no other key of the user's serves Claude.
    assert _app(stack, "PUT", "/v1/providers/anthropic", json={"api_key": "sk-ant-e2e"}).status_code == 200
    offers = _app(stack, "GET", "/v1/app/summary").json()["offers"]
    assert all(o["provider"] != "anthropic" for o in offers)  # nothing like it failed yet
    httpx.post(f"{stack['upstream']}/_state", json={"anthropic": "overloaded"}, timeout=10)
    try:
        for _ in range(3):
            assert _claude_request(stack).status_code >= 500
    finally:
        httpx.post(f"{stack['upstream']}/_state", json={"anthropic": "ok"}, timeout=10)
    try:
        report = _panel(stack, "offer")
        assert report["lead"] == "3 requests failed today.", report
        assert report["rest"] == "Anthropic didn't answer and none of your other keys has Claude."
        # No OrcaRouter key yet: setup opens at its step and turns paid models
        # on only once a key is saved; nothing is switched on here.
        assert "step=orcarouter" in report["setupUrlHash"] and "then=paid" in report["setupUrlHash"]
        assert report["stepRequest"]["step"] == "orcarouter" and report["stepRequest"]["then"] == "paid"
        assert report["hostedModelsAfterAdd"] == "free"
        assert report["body"].startswith("Add OrcaRouter's gateway as a backup")
        assert report["hiddenAfterReload"] is True
        dismissed = _app(stack, "GET", "/v1/app/settings").json()["dismissed_offers"]
        assert list(dismissed) == ["backup"]
        assert _app(stack, "GET", "/v1/app/summary").json()["offers"] == []
    finally:
        _app(stack, "DELETE", "/v1/providers/anthropic")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10r_orcarouter_spend_and_the_out_of_credit_banner(stack):
    # H4: a paid OrcaRouter request (with its reported cost), then a 402.
    assert _app(stack, "PUT", "/v1/providers/orcarouter", json={"api_key": "sk-orca-e2e-key"}).status_code == 200
    _app(stack, "PUT", "/v1/app/settings", json={"hosted_models": "all"})
    pin = {"model": "minimax-m2.7", "messages": [{"role": "user", "content": "ping"}]}
    try:
        assert _app(stack, "POST", "/v1/chat/completions", json=pin).status_code == 200
        httpx.post(f"{stack['upstream']}/_state", json={"orca": "no_credit"}, timeout=10)
        assert _app(stack, "POST", "/v1/chat/completions", json=pin).status_code == 402
        report = _panel(stack, "credit")
        assert report["banner"].startswith("OrcaRouter is out of credit. Orca is using your own keys only."), report
        assert report["firstProvider"] == "orcarouter"
        assert "OrcaRouter" in report["providerRow"] and "$0.01 this month" in report["providerRow"]
        assert "Out of credit" in report["providerRow"]
        assert len(report["opened"]) == 1 and "/console/topup" in report["opened"][0]
        assert "ref=lite-panel" in report["opened"][0]
    finally:
        httpx.post(f"{stack['upstream']}/_state", json={"orca": "ok"}, timeout=10)
        _app(stack, "PUT", "/v1/app/settings", json={"hosted_models": "free"})
        _app(stack, "DELETE", "/v1/providers/orcarouter")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10r2_the_paid_models_switch(stack):
    assert _app(stack, "PUT", "/v1/providers/orcarouter", json={"api_key": "sk-orca-e2e-key"}).status_code == 200
    _app(stack, "PUT", "/v1/app/settings", json={"hosted_models": "free"})
    try:
        report = _panel(stack, "paid")
        assert report["before"] == {"checked": "false", "text": "Off"}, report
        assert report["confirm"].startswith("Free models and your own keys still come first;")
        assert report["confirm"].endswith("This applies to all agents.")
        assert report["focusOnConfirm"] == "Use paid models"
        assert report["afterOn"] == "all"
        assert report["settingsState"] == "On"
        assert report["settingsText"] == ("Requests free models and your own keys can't handle go to OrcaRouter's "
                                          "paid models, at the provider's price.")
        assert report["afterOff"] == "free"
        assert report["retriesLabel"] == "Retries (pinned models)"
    finally:
        _app(stack, "PUT", "/v1/app/settings", json={"hosted_models": "free"})
        _app(stack, "DELETE", "/v1/providers/orcarouter")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10s_models_on_this_computer(stack):
    # P2 · D1: Ollama starts after the engine; Refresh finds it.
    ollama = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.fake_ollama:app", "--port", str(stack["ollama_port"]),
         "--log-level", "warning"], cwd=ROOT, env=stack["env"], stdout=open(stack["logs"] / "ollama.log", "w"),
        stderr=subprocess.STDOUT)
    try:
        _wait(f"http://127.0.0.1:{stack['ollama_port']}/_calls", ollama, "fake ollama")
        report = _panel(stack, "local")
        assert report["runtime"].startswith("OLOllama"), report  # its tile, then its name
        assert "found 1 model" in report["runtime"] and "Running" in report["runtime"]
        assert report["checked"] is True
        assert report["afterOff"] == []
        assert report["afterOn"] == ["ollama/qwen3-coder:30b"]
    finally:
        ollama.terminate()
        _stop(ollama, graceful_seconds=10)
        _app(stack, "PUT", "/v1/app/settings", json={"local_models": None})


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10t_savings_card_weekly_report_and_share_my_setup(stack):
    # V2, H8, H7, V3.
    report = _panel(stack, "share")
    assert report["alt"].startswith("This week, across ") and "Orca saved me $" in report["alt"], report
    assert report["painted"]["w"] == 1200 and report["painted"]["h"] == 630 and report["painted"]["alpha"] == 255
    assert "image/png" in report["clipboardTypes"]
    x, linkedin = report["opened"]
    assert x.startswith("https://x.com/intent/post?") and "ref%3Dlite-card" in x
    assert linkedin.startswith("https://www.linkedin.com/sharing/share-offsite/?") and "ref%3Dlite-card" in linkedin
    assert "Claude Code" in report["markdown"] and "|" in report["markdown"]
    saved = report["csvToast"].split("Saved to ", 1)[1].rstrip(".")
    assert saved.startswith("~/") and (stack["home"] / saved[2:]).is_file(), report["csvToast"]
    assert report["setupLink"].startswith("orca://setup?agents=")
    assert "sk-" not in report["setupLink"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10u_orca_links_only_open_a_confirmation(stack):
    try:
        report = _panel(stack, "links")
        assert report["connectTitle"] == "Connect Gemini CLI"
        assert report["focusOnCancel"] == "link-cancel"
        assert report["titleWhileQueued"] == "Connect Gemini CLI"  # a second link waits its turn
        assert report["queuedHost"] == "gw.example.dev"
        assert report["focusAfterSheets"] != "BODY"
        assert report["connectedAfterCancel"] is False
        assert "Works." in report["connectToast"] and report["connectedAfterConfirm"] is True
        assert report["joinTitle"] == "Join a team gateway" and report["joinHost"] == "192.168.1.20:8000"
        assert report["notEncrypted"] is True and report["keyField"] == ""
        assert "first" in report["keyHelp"]
        assert report["ignoredBadLinks"] is True and report["gatewayAfter"] is None
    finally:
        _orca(stack, "disconnect", "gemini-cli")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node with playwright")
def test_10v_settings_in_the_panel(stack):
    try:
        report = _panel(stack, "settings")
        assert report["keyShown"].startswith("aa-") and "3f2" in report["keyShown"] and "Saved" in report["keyShown"]
        assert report["keyStatus"] == {"configured": True, "source": "app", "hint": "aa-…3f2"}
        assert "0 to 5" in report["badRetries"]
        assert report["routerStatus"].startswith("Saved.") and report["saved"] == {"retries": 2, "cooldown": 60}
        assert report["keyAfterRemove"]["configured"] is False
        assert report["focusAfterRemove"] == "aa-key"
        assert (report["panelCollapsed"], report["panelOpened"]) == ("hidden", "visible")
        assert report["setupCollapses"], report
        for c in report["setupCollapses"]:  # closed ones are out of the tab order, open ones aren't
            assert c["visibility"] == ("visible" if c["open"] else "hidden"), report["setupCollapses"]
    finally:
        _app(stack, "PUT", "/v1/app/settings", json={"router_num_retries": None, "router_cooldown_seconds": None})
        _orca(stack, "disconnect", "--all")

def test_11_nothing_leaked_into_the_engine_log(stack):
    log = stack["engine_log"].read_text()
    for secret in ("sk-e2e-upstream", stack["app_key"], CLIPBOARD_KEY, "sk-orca-e2e-key", "sk-ant-e2e",
                   "aa-e2e-test-key-0003f2"):
        assert secret not in log
    assert shlex.quote  # keep the import used for readers of _command_code
