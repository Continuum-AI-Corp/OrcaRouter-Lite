"""`orca` — the command-line face of the desktop app."""

from __future__ import annotations

import json

import httpx
import pytest

from app import orca_cli
from packages.desktop import home as dh


@pytest.fixture
def orca_home(tmp_path, monkeypatch):
    h = tmp_path / "orca"
    monkeypatch.setenv("ORCA_HOME", str(h))
    return h


# ── orca up ─────────────────────────────────────────────────────────────


def test_up_starts_the_engine_on_loopback_in_desktop_mode(orca_home, monkeypatch):
    calls = {}

    def fake_run(*, host, port, env):
        calls.update(host=host, port=port, env=env)

    assert orca_cli.main(["up", "--port", "8799"], run_server=fake_run) == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8799
    assert calls["env"]["ORCA_DESKTOP_MODE"] == "1"
    assert calls["env"]["DATABASE_URL"].endswith(f"{orca_home / 'orca.db'}")
    assert dh.read_engine_info(orca_home)["base_url"] == "http://127.0.0.1:8799"


def test_up_refuses_a_non_loopback_host(orca_home, capsys):
    def fake_run(**_kw):  # pragma: no cover - must not be reached
        raise AssertionError("server must not start")

    assert orca_cli.main(["up", "--host", "0.0.0.0"], run_server=fake_run) == 2
    assert "127.0.0.1" in capsys.readouterr().err


# ── commands that talk to a running engine ──────────────────────────────


def _running(orca_home, key="sk-orca-app"):
    dh.prepare_home(orca_home)
    dh.write_engine_info(orca_home, base_url="http://127.0.0.1:8765", pid=1)
    (orca_home / "app.key").write_text(key)


def _transport(handler):
    seen = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), seen


def test_connect_calls_the_engine_with_the_app_key(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(200, json={
        "id": "claude-code", "name": "Claude Code", "connected": True, "manual": False,
        "config_path": "/home/u/.claude/settings.json", "note": "",
    }))
    assert orca_cli.main(["connect", "claude-code"], transport=transport) == 0
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "http://127.0.0.1:8765/v1/app/agents/claude-code/connect"
    assert req.headers["authorization"] == "Bearer sk-orca-app"
    out = capsys.readouterr().out
    assert "Claude Code connected" in out
    assert ".claude/settings.json" in out


def test_connect_manual_agent_prints_what_to_paste(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(200, json={
        "id": "cursor", "name": "Cursor", "connected": True, "manual": True,
        "base_url": "http://127.0.0.1:8765/v1", "api_key": "sk-orca-cursor", "note": "Paste it.",
    }))
    assert orca_cli.main(["connect", "cursor"], transport=transport) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8765/v1" in out
    assert "sk-orca-cursor" in out


def test_engine_error_is_shown_and_exit_code_is_nonzero(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(409, json={
        "error": {"message": "Codex needs the OpenAI Responses API, which Lite does not serve yet."}}))
    assert orca_cli.main(["connect", "codex"], transport=transport) == 1
    assert "Responses API" in capsys.readouterr().err


def test_disconnect(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(200, json={
        "id": "claude-code", "name": "Claude Code", "connected": False}))
    assert orca_cli.main(["disconnect", "claude-code"], transport=transport) == 0
    assert seen[0].url.path == "/v1/app/agents/claude-code/disconnect"
    assert "restored" in capsys.readouterr().out


def test_commands_explain_when_the_engine_is_not_running(orca_home, capsys):
    assert orca_cli.main(["status"]) == 1
    assert "orca up" in capsys.readouterr().err


def test_connection_refused_is_explained(orca_home, capsys):
    _running(orca_home)

    def boom(_r):
        raise httpx.ConnectError("refused")

    assert orca_cli.main(["status"], transport=httpx.MockTransport(boom)) == 1
    assert "orca up" in capsys.readouterr().err


SUMMARY = {
    "today": {"spend_microcents": 3_200_000, "requests": 41},
    "week": {"spend_microcents": 14_800_000, "requests": 300, "saved_microcents": 9_100_000,
             "baseline_model": "gpt-4o", "failures_avoided": 14},
    "budget": {"daily_cents": 2000, "used_percent": 16.0, "state": "ok"},
    "agents": [
        {"id": "claude-code", "name": "Claude Code", "today_microcents": 2_600_000, "week_microcents": 11_400_000, "requests_week": 200},
        {"id": "other", "name": "Other apps", "today_microcents": 600_000, "week_microcents": 3_400_000, "requests_week": 100},
    ],
    "providers": [{"provider": "anthropic", "source": "db", "state": "healthy"}],
    "hosted": {"configured": True},
}


def test_status_prints_spend_by_agent(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(200, json=SUMMARY))
    assert orca_cli.main(["status"], transport=transport) == 0
    assert seen[0].url.path == "/v1/app/summary"
    assert "tz_offset_minutes" in str(seen[0].url)
    out = capsys.readouterr().out
    assert "$3.20" in out and "$20.00" in out
    assert "$14.80" in out and "$9.10" in out
    assert "Claude Code" in out and "$11.40" in out


def test_status_json(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(200, json=SUMMARY))
    assert orca_cli.main(["status", "--json"], transport=transport) == 0
    assert json.loads(capsys.readouterr().out)["today"]["spend_microcents"] == 3_200_000


@pytest.mark.parametrize("micro,text", [(0, "$0.00"), (4_999, "$0.00"), (5_000, "$0.01"), (1_234_567, "$1.23"),
                                        (123_456_789_000, "$123,456.79")])
def test_money_format(micro, text):
    assert orca_cli.money(micro) == text


def test_status_uses_singular_for_one_rescued_request(orca_home, capsys):
    _running(orca_home)
    one = {**SUMMARY, "week": {**SUMMARY["week"], "failures_avoided": 1}}
    transport, _ = _transport(lambda r: httpx.Response(200, json=one))
    orca_cli.main(["status"], transport=transport)
    assert "1 request rescued" in capsys.readouterr().out
