"""End to end: the engine's routing core against fake providers.

One engine (`orca up`) runs in a throwaway HOME next to a fake upstream
that plays OpenAI, OrcaRouter, Anthropic and Moonshot (each under its own
path, reached through the provider's base-URL variable) and a fake Ollama.
No provider key is set in the environment: each test adds the keys it
needs through the API, as the app does, so the tests run in order:

1. H0: with only an OrcaRouter key, requests run on free models at $0; an
   image request is refused with needs_paid_model until paid models are
   allowed.
2. H2: an overloaded Anthropic key fails with no fallback; with an
   OrcaRouter key the same request is rescued through it.
3. H4: OrcaRouter's reported cost prices a request; once it answers 402
   the engine says it's out of credit and own keys keep serving.
4. P2: the fake Ollama is discovered; local_first sends what fits to it
   at $0, the rest to the cloud, and the cloud takes over when it stops.
5. P1: a Moonshot key serves Kimi through a Moonshot-shaped upstream.
6. D2 + D3: Claude Code's model map applies, and its own daily budget
   pauses it while other agents keep working.
"""

from __future__ import annotations

import os
import site
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.e2e.test_desktop_e2e import _claude, _free_port, _opencode, _stop, _wait

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e
ANTHROPIC_HEADERS = {"anthropic-version": "2023-06-01"}
FREE = {"deepseek/deepseek-v4-pro-free", "deepseek/deepseek-v4-flash-free", "qwen/qwen3.8-27b-free",
        "orcarouter/free"}


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("routing-e2e")
    home = tmp / "home"
    for d in (".claude", ".config/opencode"):
        (home / d).mkdir(parents=True)
    orca_home = home / ".orcarouter-lite"
    logs = tmp / "logs"
    logs.mkdir()
    up_port, ollama_port, engine_port, closed_port = _free_port(), _free_port(), _free_port(), _free_port()
    up = f"http://127.0.0.1:{up_port}"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "ORCAROUTER_", "DATABASE_",
                                "CREDENTIAL_", "API_KEY_", "ORCA_", "MOONSHOT_", "OLLAMA_", "LMSTUDIO_",
                                "LLAMACPP_", "ROUTER_", "ARTIFICIAL_"))}
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "ORCA_HOME": str(orca_home),
        "ORCA_KEYCHAIN": "0", "ORCA_NO_UPDATE_CHECK": "1", "PYTHONPATH": str(ROOT),
        "PYTHONUSERBASE": site.getuserbase(),
        "OPENAI_BASE_URL": f"{up}/v1",
        "ORCAROUTER_BASE_URL": f"{up}/orca/v1",
        "ANTHROPIC_BASE_URL": f"{up}/anthropic",
        "MOONSHOT_API_BASE": f"{up}/moonshot/v1",
        "OLLAMA_HOST": f"127.0.0.1:{ollama_port}",
        # Never probe runtimes really running on this machine.
        "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{closed_port}",
        "LLAMACPP_BASE_URL": f"http://127.0.0.1:{closed_port}",
        # A failed provider isn't retried or rested, so each test sees exactly what it sets up.
        "ROUTER_NUM_RETRIES_DEFAULT": "0", "ROUTER_COOLDOWN_SECONDS": "0",
    })
    procs = {}
    for name, module, port in (("upstream", "fake_upstream", up_port), ("ollama", "fake_ollama", ollama_port)):
        procs[name] = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", f"tests.e2e.{module}:app", "--port", str(port), "--log-level",
             "warning"], cwd=ROOT, env=env, stdout=open(logs / f"{name}.log", "w"), stderr=subprocess.STDOUT)
    frozen = os.environ.get("ORCA_E2E_ENGINE")
    orca = [frozen] if frozen else [sys.executable, "-c",
                                    "import sys; from app.orca_cli import entrypoint; sys.argv[0]='orca'; entrypoint()"]
    engine = subprocess.Popen([*orca, "up", "--port", str(engine_port), "--exit-with-stdin"], cwd=ROOT, env=env,
                              stdin=subprocess.PIPE, stdout=open(logs / "engine.log", "w"), stderr=subprocess.STDOUT)
    try:
        _wait(f"{up}/_calls", procs["upstream"], "fake provider")
        _wait(f"http://127.0.0.1:{ollama_port}/_calls", procs["ollama"], "fake ollama")
        _wait(f"http://127.0.0.1:{engine_port}/health", engine, "engine")
        s = {"home": home, "orca_home": orca_home, "env": env, "orca": orca, "logs": logs, "procs": procs,
             "base": f"http://127.0.0.1:{engine_port}", "upstream": up,
             "ollama": f"http://127.0.0.1:{ollama_port}",
             "app_key": (orca_home / "app.key").read_text().strip()}
        for agent in ("claude-code", "opencode"):
            r = subprocess.run([*orca, "connect", agent], cwd=ROOT, env=env, capture_output=True, text=True,
                               timeout=60)
            assert r.returncode == 0, r.stderr
        yield s
    finally:
        engine.stdin.close()
        _stop(engine, graceful_seconds=15)
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
                _stop(p, graceful_seconds=10)


# ── helpers ─────────────────────────────────────────────────────────────


def _app(stack, method, path, **kw):
    return httpx.request(method, f"{stack['base']}{path}", headers={"Authorization": f"Bearer {stack['app_key']}"},
                         timeout=60, **kw)


def _key(stack, provider, key):
    r = _app(stack, "PUT", f"/v1/providers/{provider}", json={"api_key": key})
    assert r.status_code == 200, r.text


def _drop_key(stack, provider):
    assert _app(stack, "DELETE", f"/v1/providers/{provider}").status_code in (204, 404)


def _settings(stack, **values):
    r = _app(stack, "PUT", "/v1/app/settings", json=values)
    assert r.status_code == 200, r.text


def _upstream_state(stack, **state):
    httpx.post(f"{stack['upstream']}/_state", json=state, timeout=10).raise_for_status()


def _calls(stack, upstream=None):
    calls = httpx.get(f"{stack['upstream']}/_calls", timeout=10).json()["calls"]
    return [c for c in calls if upstream is None or c.get("upstream", "openai") == upstream]


def _ollama_calls(stack):
    return httpx.get(f"{stack['ollama']}/_calls", timeout=10).json()["calls"]


def _last_row(stack) -> dict:
    with sqlite3.connect(stack["orca_home"] / "orca.db") as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM requests_log ORDER BY rowid DESC LIMIT 1").fetchone()
    return dict(row)


def _claude_code(stack, *, model="claude-sonnet-4-6", content="ping", stream=False):
    base, token = _claude(stack["home"])
    return httpx.post(f"{base}/v1/messages", headers={"Authorization": f"Bearer {token}", **ANTHROPIC_HEADERS},
                      json={"model": model, "max_tokens": 64, "stream": stream,
                            "messages": [{"role": "user", "content": content}]}, timeout=60)


def _opencode_chat(stack, *, model=None, content="ping", stream=False):
    base, key, default_model = _opencode(stack["home"])
    return httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": model or default_model, "stream": stream,
                            "messages": [{"role": "user", "content": content}]},
                      timeout=60)


IMAGE = [{"type": "text", "text": "what is this"},
         {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]


# ── the tests, in order ─────────────────────────────────────────────────


def test_1_h0_only_an_orcarouter_key_runs_on_free_models(stack):
    _key(stack, "orcarouter", "sk-orca-e2e-key")
    r = _claude_code(stack)
    assert r.status_code == 200, r.text
    assert r.headers["x-orca-requested-model"] == "claude-sonnet-4-6"
    assert r.headers["x-orca-resolved-model"] in FREE
    call = _calls(stack, "orca")[-1]
    assert call["model"] in FREE and call["auth"] == "Bearer sk-orca-e2e-key"
    row = _last_row(stack)
    assert (row["route_note"], row["cost_microcents"], row["provider"]) == ("free", 0, "orcarouter")

    # A request free models can't serve is refused, and nothing is sent.
    sent = len(_calls(stack))
    r = _opencode_chat(stack, content=IMAGE)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "needs_paid_model"
    assert "needs a paid model (images)" in r.json()["error"]["message"]
    assert len(_calls(stack)) == sent
    assert _last_row(stack)["route_note"] == "needs_paid"

    # Allowing paid models lets it through to one of OrcaRouter's.
    _settings(stack, hosted_models="all")
    r = _opencode_chat(stack, content=IMAGE)
    assert r.status_code == 200, r.text
    call = _calls(stack, "orca")[-1]
    assert call["images"] and call["model"] not in FREE
    assert _last_row(stack)["cost_microcents"] == 12_300  # OrcaRouter's reported $0.0123


def test_2_h2_a_failure_with_no_backup_then_a_rescue_through_orcarouter(stack):
    _drop_key(stack, "orcarouter")
    _key(stack, "anthropic", "sk-ant-e2e")
    _upstream_state(stack, anthropic="overloaded")
    r = _claude_code(stack)
    assert r.status_code >= 500, r.text
    assert _calls(stack, "anthropic")[-1]["model"] == "claude-sonnet-4-6"
    row = _last_row(stack)
    assert (row["route_note"], row["provider"], row["status_code"] >= 500) == ("no_fallback", "anthropic", True)

    _key(stack, "orcarouter", "sk-orca-e2e-key")  # paid models are allowed since test 1
    r = _claude_code(stack)
    assert r.status_code == 200, r.text
    assert r.json()["content"][0]["text"] == "pong"
    assert _calls(stack, "orca")[-1]["model"] == "anthropic/claude-sonnet-4.6"
    row = _last_row(stack)
    assert (row["provider"], row["fallback_level"], row["route_note"]) == ("orcarouter", 1, None)
    _upstream_state(stack, anthropic="ok")


def test_3_h4_orcarouter_cost_then_out_of_credit_while_own_keys_keep_serving(stack):
    _key(stack, "openai", "sk-e2e-upstream")
    # A model only OrcaRouter serves here (an own-key twin would rescue it).
    pin = {"model": "minimax-m2.7", "messages": [{"role": "user", "content": "ping"}]}
    r = _app(stack, "POST", "/v1/chat/completions", json=pin)
    assert r.status_code == 200, r.text
    assert _last_row(stack)["cost_microcents"] == 12_300

    _upstream_state(stack, orca="no_credit")
    r = _app(stack, "POST", "/v1/chat/completions", json=pin)
    assert r.status_code == 402, r.text
    assert r.json()["error"]["code"] == "out_of_credit"
    assert r.json()["error"]["message"].startswith("OrcaRouter is out of credit. Add credit at https://")
    assert _last_row(stack)["route_note"] == "out_of_credit"

    orca_calls = len(_calls(stack, "orca"))
    r = _app(stack, "POST", "/v1/chat/completions", json={**pin, "model": "auto"})
    assert r.status_code == 200, r.text
    assert len(_calls(stack, "orca")) == orca_calls  # own keys served it
    assert _last_row(stack)["provider"] in {"openai", "anthropic"}
    r = _claude_code(stack, model="claude-opus-9")  # agent fallback keeps to own keys too
    assert r.status_code == 200, r.text
    assert len(_calls(stack, "orca")) == orca_calls
    _upstream_state(stack, orca="ok")


def test_4_p2_local_models_first_and_the_cloud_for_the_rest(stack):
    _settings(stack, hosted_models="free")
    assert _app(stack, "PUT", "/v1/routing", json={"strategy": "local_first"}).status_code == 200
    try:
        r = _opencode_chat(stack)
        assert r.status_code == 200, r.text
        assert r.json()["choices"][0]["message"]["content"] == "pong from ollama"
        assert _ollama_calls(stack)[-1] == {"model": "qwen3-coder:30b", "stream": False, "num_ctx": 32768,
                                            "tools": False}
        row = _last_row(stack)
        assert (row["provider"], row["route_note"], row["cost_microcents"]) == ("local", "local", 0)
        assert row["model_resolved"].endswith("qwen3-coder:30b") and row["input_tokens"] == 1200

        r = _opencode_chat(stack, stream=True)
        assert r.status_code == 200 and "pong from ollama" in r.text
        assert _ollama_calls(stack)[-1]["stream"] is True
        assert (_last_row(stack)["route_note"], _last_row(stack)["cost_microcents"]) == ("local", 0)

        local_calls = len(_ollama_calls(stack))
        r = _opencode_chat(stack, content=IMAGE)  # no vision: the cloud
        assert r.status_code == 200, r.text
        r = _opencode_chat(stack, content="word " * 30_000)  # beyond 80% of 32K: the cloud
        assert r.status_code == 200, r.text
        assert len(_ollama_calls(stack)) == local_calls

        stack["procs"]["ollama"].terminate()
        _stop(stack["procs"]["ollama"], graceful_seconds=10)
        r = _opencode_chat(stack)
        assert r.status_code == 200, r.text
        assert r.json()["choices"][0]["message"]["content"] == "pong"
        row = _last_row(stack)
        assert row["provider"] != "local" and row["fallback_level"] == 1
    finally:
        assert _app(stack, "PUT", "/v1/routing", json={"strategy": "balanced"}).status_code == 200


def test_5_p1_a_moonshot_key_serves_kimi(stack):
    check = _app(stack, "POST", "/v1/app/providers/moonshot/check", json={"api_key": "sk-moonshot-e2e"})
    assert check.json()["status"] == "valid", check.text
    bad = _app(stack, "POST", "/v1/app/providers/moonshot/check", json={"api_key": "sk-wrong"})
    assert bad.json()["status"] == "invalid"
    _key(stack, "moonshot", "sk-moonshot-e2e")
    r = _app(stack, "POST", "/v1/chat/completions",
             json={"model": "kimi-k2.6", "messages": [{"role": "user", "content": "ping"}]})
    assert r.status_code == 200, r.text
    call = _calls(stack, "moonshot")[-1]
    assert (call["model"], call["auth"]) == ("kimi-k2.6", "Bearer sk-moonshot-e2e")
    assert _last_row(stack)["provider"] == "moonshot"
    # An agent asking for a Kimi model the catalog doesn't know gets Moonshot's.
    r = _opencode_chat(stack, model="kimi-for-coding")
    assert r.status_code == 200, r.text
    assert _calls(stack, "moonshot")[-1]["model"].startswith(("kimi", "moonshot"))


def test_6_d2_model_map_and_d3_per_agent_budget(stack):
    _settings(stack, agent_models={"claude-code": {"main": "gpt-4o-mini", "background": None,
                                                   "fallback_to_auto": True}})
    r = _claude_code(stack)
    assert r.status_code == 200, r.text
    assert (r.headers["x-orca-requested-model"], r.headers["x-orca-resolved-model"]) == (
        "claude-sonnet-4-6", "gpt-4o-mini")
    assert _calls(stack, "openai")[-1]["model"] == "gpt-4o-mini"
    row = _last_row(stack)
    assert (row["route_note"], row["model_resolved"]) == ("mapped", "gpt-4o-mini") and row["cost_microcents"] > 0

    _settings(stack, agent_budgets={"claude-code": 1})  # $0.01, already spent
    r = _claude_code(stack)
    assert r.status_code == 429, r.text
    assert "Today's budget for Claude Code ($0.01) is used up, so Orca paused it." in r.text
    assert _opencode_chat(stack).status_code == 200  # other agents keep working
    _settings(stack, agent_budgets={}, agent_models={})
    assert _claude_code(stack).status_code == 200


def test_7_no_key_leaked_into_the_engine_log(stack):
    log = (stack["logs"] / "engine.log").read_text()
    for secret in ("sk-orca-e2e-key", "sk-moonshot-e2e", "sk-ant-e2e", "sk-e2e-upstream", stack["app_key"]):
        assert secret not in log
