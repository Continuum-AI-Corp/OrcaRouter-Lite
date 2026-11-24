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
        calls.update(host=host, port=port, env=env, info=dh.read_engine_info(orca_home))

    assert orca_cli.main(["up", "--port", "8799"], run_server=fake_run) == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8799
    assert calls["env"]["ORCA_DESKTOP_MODE"] == "1"
    assert calls["env"]["DATABASE_URL"].endswith(f"{orca_home / 'orca.db'}")
    assert calls["info"]["base_url"] == "http://127.0.0.1:8799"


def test_up_refuses_a_non_loopback_host(orca_home, capsys):
    def fake_run(**_kw):  # pragma: no cover - must not be reached
        raise AssertionError("server must not start")

    assert orca_cli.main(["up", "--host", "0.0.0.0"], run_server=fake_run) == 2
    assert "127.0.0.1" in capsys.readouterr().err


# ── commands that talk to a running engine ──────────────────────────────


SECRET = "instance-secret-for-tests"


def _running(orca_home, key="sk-orca-app"):
    dh.prepare_home(orca_home)
    dh.write_engine_info(orca_home, base_url="http://127.0.0.1:8765", pid=1, secret=SECRET)
    (orca_home / "app.key").write_text(key)


def _proof(request, secret=SECRET):
    import hashlib
    import hmac

    challenge = request.url.params["challenge"]
    return httpx.Response(200, json={"proof": hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()})


def _transport(handler, secret=SECRET):
    """Answer the identity challenge like the real engine, then delegate."""
    seen = []

    def wrapped(request: httpx.Request):
        if request.url.path == "/health/identity":
            return _proof(request, secret)
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


MONEY_VECTORS = json.loads(
    (__import__("pathlib").Path(__file__).resolve().parents[2] / "desktop" / "tests" / "money_vectors.json").read_text()
)


@pytest.mark.parametrize("micro,text", MONEY_VECTORS)
def test_money_format_matches_the_shared_vectors(micro, text):
    # The same vectors are checked by the desktop UI (JS) and the tray (Rust).
    assert orca_cli.money(micro) == text


def test_status_uses_singular_for_one_rescued_request(orca_home, capsys):
    _running(orca_home)
    one = {**SUMMARY, "week": {**SUMMARY["week"], "failures_avoided": 1}}
    transport, _ = _transport(lambda r: httpx.Response(200, json=one))
    orca_cli.main(["status"], transport=transport)
    assert "1 failed request was retried on another provider" in capsys.readouterr().out



# ── review fixes ────────────────────────────────────────────────────────


def test_up_passes_a_fresh_instance_secret_to_the_engine_and_engine_json(orca_home):
    calls = {}
    orca_cli.main(["up"], run_server=lambda **kw: calls.update(kw, info=dh.read_engine_info(orca_home)))
    secret = calls["env"]["ORCA_INSTANCE_SECRET"]
    assert len(secret) >= 32
    assert calls["info"]["secret"] == secret


def test_up_removes_engine_json_when_the_server_stops(orca_home):
    orca_cli.main(["up"], run_server=lambda **kw: None)
    with pytest.raises(dh.EngineNotRunning):
        dh.read_engine_info(orca_home)


def test_up_rejects_ipv6_loopback_it_would_not_bind(orca_home, capsys):
    assert orca_cli.main(["up", "--host", "::1"], run_server=lambda **kw: None) == 2


def test_bad_orca_port_is_a_clear_error(orca_home, monkeypatch, capsys):
    monkeypatch.setenv("ORCA_PORT", "eighty")
    assert orca_cli.main(["up"], run_server=lambda **kw: None) == 2
    assert "ORCA_PORT" in capsys.readouterr().err


def test_an_impostor_on_the_port_never_receives_the_key(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(200, json={}), secret="wrong")
    assert orca_cli.main(["status"], transport=transport) == 1
    assert seen == []  # no authenticated request was sent
    assert "another program" in capsys.readouterr().err


def test_a_slow_engine_is_reported_as_slow_not_stopped(orca_home, capsys):
    _running(orca_home)

    def slow(request):
        if request.url.path == "/health/identity":
            return _proof(request)
        raise httpx.ReadTimeout("slow")

    assert orca_cli.main(["status"], transport=httpx.MockTransport(slow)) == 1
    err = capsys.readouterr().err
    assert "didn't answer" in err and "orca up" not in err


def test_watch_stdin_calls_back_on_eof():
    import io

    fired = []
    orca_cli.watch_stdin(io.StringIO("ignored\n"), lambda: fired.append(True))
    assert fired == [True]



def test_status_uses_the_same_words_as_the_app(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(200, json=SUMMARY))
    orca_cli.main(["status"], transport=transport)
    out = capsys.readouterr().out
    assert "of $20.00 daily alert" in out
    assert "Last 7 days" in out and "vs GPT-4o" in out


def test_status_hides_zero_savings(orca_home, capsys):
    _running(orca_home)
    none = {**SUMMARY, "week": {**SUMMARY["week"], "saved_microcents": 0}}
    transport, _ = _transport(lambda r: httpx.Response(200, json=none))
    orca_cli.main(["status"], transport=transport)
    assert "saved" not in capsys.readouterr().out


def test_status_says_when_the_budget_pauses_agents(orca_home, capsys):
    _running(orca_home)
    stop = {**SUMMARY, "budget": {**SUMMARY["budget"], "mode": "stop"}}
    transport, _ = _transport(lambda r: httpx.Response(200, json=stop))
    orca_cli.main(["status"], transport=transport)
    assert "of $20.00 daily budget (pauses agents)" in capsys.readouterr().out


# ── statusline, report, login/logout ────────────────────────────────────


def test_statusline_is_one_compact_line(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(200, json=SUMMARY))
    assert orca_cli.main(["statusline"], transport=transport) == 0
    assert capsys.readouterr().out == "orca $3.20 / $20.00\n"


def test_statusline_without_budget(orca_home, capsys):
    _running(orca_home)
    none = {**SUMMARY, "budget": {"daily_cents": None, "used_percent": None, "state": "none", "mode": "alert"}}
    transport, _ = _transport(lambda r: httpx.Response(200, json=none))
    orca_cli.main(["statusline"], transport=transport)
    assert capsys.readouterr().out == "orca $3.20 today\n"


def test_statusline_never_breaks_the_status_bar(orca_home, capsys):
    # Engine down: print a placeholder, exit 0, nothing on stderr.
    assert orca_cli.main(["statusline"]) == 0
    out = capsys.readouterr()
    assert out.out == "orca —\n" and out.err == ""


def test_report_markdown(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(200, json=SUMMARY))
    assert orca_cli.main(["report"], transport=transport) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Coding-agent spend")
    assert "| Claude Code | $2.60 | $11.40 | 200 |" in out
    assert "Saved $9.10 vs GPT-4o" in out


def test_report_csv(orca_home, capsys):
    _running(orca_home)
    transport, _ = _transport(lambda r: httpx.Response(200, json=SUMMARY))
    assert orca_cli.main(["report", "--format", "csv"], transport=transport) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "agent,today_usd,last_7_days_usd,requests_last_7_days"
    assert lines[1] == "Claude Code,2.60,11.40,200"


def _team_transport(status=200):
    def handler(request):
        if request.url.host == "gw.example.com":
            if status != 200:
                return httpx.Response(status, json={"error": {"message": "Invalid API key"}})
            return httpx.Response(200, json={"data": [{"id": "auto"}]})
        raise AssertionError(f"unexpected request {request.url}")

    return httpx.MockTransport(handler)


def test_login_points_installed_agents_at_the_team_gateway(orca_home, tmp_path, monkeypatch, capsys):
    import json as _json

    home = tmp_path / "user"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    rc = orca_cli.main(["login", "https://gw.example.com", "--key", "sk-orca-team"], transport=_team_transport())
    assert rc == 0, capsys.readouterr().err
    env = _json.loads((home / ".claude" / "settings.json").read_text())["env"]
    assert env == {"ANTHROPIC_BASE_URL": "https://gw.example.com", "ANTHROPIC_AUTH_TOKEN": "sk-orca-team"}
    assert "Claude Code" in capsys.readouterr().out


def test_login_with_a_bad_key_changes_nothing(orca_home, tmp_path, monkeypatch, capsys):
    home = tmp_path / "user"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    rc = orca_cli.main(["login", "https://gw.example.com", "--key", "sk-orca-bad"], transport=_team_transport(401))
    assert rc == 1
    assert not (home / ".claude" / "settings.json").exists()


def test_logout_restores_agents(orca_home, tmp_path, monkeypatch, capsys):
    home = tmp_path / "user"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    orca_cli.main(["login", "https://gw.example.com", "--key", "sk-orca-team"], transport=_team_transport())
    assert orca_cli.main(["logout"]) == 0
    assert not (home / ".claude" / "settings.json").exists()


# ── orca link ───────────────────────────────────────────────────────────


def test_link_saves_the_orcarouter_key_as_the_hosted_provider(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(200, json={
        "provider": "orcarouter", "key_prefix": "sk-orca-…7f3a", "is_enabled": True}))
    assert orca_cli.main(["link", "--key", "  sk-orca-live-7f3a  "], transport=transport) == 0
    req = seen[0]
    assert req.method == "PUT"
    assert str(req.url) == "http://127.0.0.1:8765/v1/providers/orcarouter"
    assert req.headers["authorization"] == "Bearer sk-orca-app"
    assert json.loads(req.content) == {"api_key": "sk-orca-live-7f3a"}
    out = capsys.readouterr().out
    assert "OrcaRouter" in out
    assert "sk-orca-live-7f3a" not in out  # never echo the key back


def test_link_refuses_a_key_that_is_not_an_orcarouter_key(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(500))
    assert orca_cli.main(["link", "--key", "sk-ant-abc"], transport=transport) == 2
    assert seen == []
    assert "sk-orca-" in capsys.readouterr().err


def test_link_reports_when_the_engine_is_not_running(orca_home, capsys):
    assert orca_cli.main(["link", "--key", "sk-orca-x"]) == 1
    assert "orca up" in capsys.readouterr().err


def test_disconnect_all_through_the_engine(orca_home, capsys):
    _running(orca_home)
    transport, seen = _transport(lambda r: httpx.Response(200, json={"disconnected": ["Claude Code", "Codex"], "failed": []}))
    assert orca_cli.main(["disconnect", "--all"], transport=transport) == 0
    assert seen[0].url.path == "/v1/app/agents/disconnect-all"
    assert "Claude Code, Codex" in capsys.readouterr().out


def test_disconnect_all_works_without_the_engine(orca_home, tmp_path, monkeypatch, capsys):
    # Uninstalling runs this with no engine running: restore the files directly.
    from packages.desktop import agents as ag

    home = tmp_path / "userhome"
    (home / ".claude").mkdir(parents=True)
    original = b'{"theme": "dark"}\n'
    (home / ".claude" / "settings.json").write_bytes(original)
    monkeypatch.setattr(orca_cli.Path, "home", classmethod(lambda cls: home))
    ag.connect_agent("claude-code", home=home, state_dir=orca_home / "agents", base_url="http://127.0.0.1:8765",
                     api_key="sk-orca-x")
    ag.connect_agent("cursor", home=home, state_dir=orca_home / "agents", base_url="http://127.0.0.1:8765",
                     api_key="sk-orca-y")
    assert orca_cli.main(["disconnect", "--all"]) == 0
    assert (home / ".claude" / "settings.json").read_bytes() == original
    assert not any(s.connected for s in ag.detect_agents(home=home, state_dir=orca_home / "agents"))
    out = capsys.readouterr().out
    assert "Claude Code" in out and "Cursor" in out


def test_disconnect_needs_an_agent_or_all(orca_home, capsys):
    assert orca_cli.main(["disconnect"]) == 2
