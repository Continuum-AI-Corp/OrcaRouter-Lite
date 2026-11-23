"""`orca` — the command-line face of the Orca desktop app.

    orca up                      start the engine on 127.0.0.1 (desktop mode)
    orca agents                  list coding agents and whether they're connected
    orca connect <agent>         point an agent at the engine (backs up its config)
    orca disconnect <agent>      restore the agent's original config
    orca status [--json]         spend today and this week, by agent
    orca statusline              one short line for Claude Code's status bar
    orca report [--format csv]   spend by agent, as Markdown or CSV
    orca link --key sk-orca-…    use your OrcaRouter account as the hosted fallback
    orca login <url> --key …     point your agents at your team's gateway
    orca logout                  undo `orca login`

The desktop app runs `orca up` and talks to the same /v1/app API, so every
action here is also a button in the app.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import TextIO

import httpx

from packages.desktop import home as dh

LOOPBACK = {"127.0.0.1", "localhost"}
NOT_RUNNING = "The Orca engine isn't running. Start it with `orca up`, or open the Orca app."
NOT_OURS = (
    "Something answered on {url}, but it isn't the Orca engine started from this folder "
    "(another program may be using the port). Orca didn't send it your key."
)
SLOW = "The Orca engine didn't answer in time. It may be busy; try again in a moment."


def money(microcents: int) -> str:
    dollars = (Decimal(max(0, int(microcents))) / Decimal(1_000_000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${dollars:,.2f}"


def _tz_offset_minutes() -> int:
    # Minutes east of UTC, the same convention the app's JavaScript sends.
    return int(-(time.altzone if time.localtime().tm_isdst > 0 else time.timezone) / 60)


def _run_uvicorn(*, host: str, port: int, env: dict[str, str]) -> None:  # pragma: no cover - starts a server
    os.environ.update(env)
    from app.config import get_settings

    get_settings.cache_clear()
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, log_level=os.environ.get("LOG_LEVEL", "info"))


def watch_stdin(stream: TextIO, on_eof: Callable[[], None]) -> None:
    """Block until `stream` closes, then call `on_eof`.

    The desktop app starts the engine with a pipe on stdin and never writes
    to it. When the app exits for any reason (quit, crash, force-quit) the OS
    closes the pipe, and the engine stops instead of lingering on the port.
    """
    try:
        while stream.read(4096):
            pass
    except (OSError, ValueError):
        pass
    on_eof()


def _default_port() -> int | None:
    raw = os.environ.get("ORCA_PORT")
    if raw is None:
        return dh.DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return None
    return port if 0 < port < 65536 else None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orca", description="Put a budget on every coding agent.")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="start the local engine")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=None)
    up.add_argument("--exit-with-stdin", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("agents", help="list coding agents")
    c = sub.add_parser("connect", help="point an agent at the engine")
    c.add_argument("agent")
    d = sub.add_parser("disconnect", help="restore an agent's original config")
    d.add_argument("agent")
    s = sub.add_parser("status", help="spend today and this week")
    s.add_argument("--json", action="store_true")
    sub.add_parser("statusline", help="one short line for Claude Code's status bar")
    r = sub.add_parser("report", help="spend by agent, as Markdown or CSV")
    r.add_argument("--format", choices=["md", "csv"], default="md")
    lk = sub.add_parser("link", help="use your OrcaRouter account as the hosted fallback")
    lk.add_argument("--key", required=True, help="your sk-orca-… key from orcarouter.ai")
    lg = sub.add_parser("login", help="point your agents at your team's gateway")
    lg.add_argument("url", help="the gateway's address, e.g. https://ai-gw.example.com")
    lg.add_argument("--key", required=True, help="the key your platform team gave you")
    sub.add_parser("logout", help="restore your agents' settings after `orca login`")
    return p


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text or f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):
            return body["error"].get("message") or str(body)
        if "detail" in body:
            return str(body["detail"])
    return str(body)


def _verify_identity(client: httpx.Client, secret: str) -> bool:
    challenge = secrets.token_hex(16)
    resp = client.get("/health/identity", params={"challenge": challenge})
    if resp.status_code != 200:
        return False
    expected = hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    try:
        proof = str(resp.json().get("proof", ""))
    except ValueError:
        return False
    return hmac.compare_digest(proof, expected)


def _request(method: str, path: str, *, transport, params=None, json_body=None, quiet: bool = False) -> dict | None:
    if quiet:
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            return _request(method, path, transport=transport, params=params, json_body=json_body)
    home = dh.default_home()
    try:
        info = dh.read_engine_info(home)
        key = dh.read_app_key(home)
        base_url, secret = info["base_url"], info["secret"]
    except (dh.EngineNotRunning, KeyError, TypeError):
        _err(NOT_RUNNING)
        return None
    try:
        with httpx.Client(base_url=base_url, transport=transport, timeout=15) as client:
            # Prove the listener is the engine we started before sending it the key.
            if not _verify_identity(client, secret):
                _err(NOT_OURS.format(url=base_url))
                return None
            resp = client.request(method, path, params=params, json=json_body,
                                  headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        _err(SLOW)
        return None
    except httpx.TransportError:
        _err(NOT_RUNNING)
        return None
    if resp.status_code >= 400:
        _err(_error_message(resp))
        return None
    try:
        return resp.json()
    except ValueError:
        _err(f"The Orca engine sent an unexpected reply (HTTP {resp.status_code}).")
        return None


MODEL_NAMES = {"gpt-4o": "GPT-4o"}


def _print_status(s: dict) -> None:
    # Same words as the menu-bar panel (desktop/ui/lib.js).
    budget = s.get("budget") or {}
    line = f"Today        {money(s['today']['spend_microcents'])}"
    if budget.get("daily_cents") is not None:
        kind = "daily budget (pauses agents)" if budget.get("mode") == "stop" else "daily alert"
        line += f" of {money(budget['daily_cents'] * 10_000)} {kind} ({budget['used_percent']:.0f}%)"
    print(line)
    week = s["week"]
    line = f"Last 7 days  {money(week['spend_microcents'])}"
    if week.get("saved_microcents", 0) > 0:
        vs = MODEL_NAMES.get(week["baseline_model"], week["baseline_model"])
        line += f"  ·  saved {money(week['saved_microcents'])} vs {vs}"
    print(line)
    n = week.get("failures_avoided") or 0
    if n:
        print(f"Fallback     {n} failed {'request was' if n == 1 else 'requests were'} retried on another provider")
    agents = s.get("agents") or []
    if agents:
        print()
        width = max(len(a["name"]) for a in agents)
        print(f"{'Agent'.ljust(width)}  {'Today':>10}  {'7 days':>10}")
        for a in agents:
            print(f"{a['name'].ljust(width)}  {money(a['today_microcents']):>10}  {money(a['week_microcents']):>10}")


def _report(s: dict, fmt: str) -> str:
    agents = s.get("agents") or []
    if fmt == "csv":
        rows = ["agent,today_usd,last_7_days_usd,requests_last_7_days"]
        for a in agents:
            name = a["name"].replace(",", " ")
            rows.append(f"{name},{money(a['today_microcents'])[1:].replace(',', '')},"
                        f"{money(a['week_microcents'])[1:].replace(',', '')},{a.get('requests_week', 0)}")
        return "\n".join(rows) + "\n"
    week = s["week"]
    lines = [
        "# Coding-agent spend",
        "",
        f"Today: {money(s['today']['spend_microcents'])} · Last 7 days: {money(week['spend_microcents'])}",
    ]
    if week.get("saved_microcents", 0) > 0:
        vs = MODEL_NAMES.get(week["baseline_model"], week["baseline_model"])
        lines.append(f"Saved {money(week['saved_microcents'])} vs {vs} by routing simple calls to cheaper models.")
    n = week.get("failures_avoided") or 0
    if n:
        lines.append(f"{n} failed {'request was' if n == 1 else 'requests were'} retried on another provider.")
    lines += ["", "| Agent | Today | Last 7 days | Requests (7 days) |", "|---|---:|---:|---:|"]
    for a in agents:
        lines.append(f"| {a['name']} | {money(a['today_microcents'])} | {money(a['week_microcents'])} | "
                     f"{a.get('requests_week', 0)} |")
    lines += ["", "_From OrcaRouter Lite (`orca report`)._"]
    return "\n".join(lines) + "\n"


def _statusline(s: dict) -> str:
    today = money(s["today"]["spend_microcents"])
    b = s.get("budget") or {}
    if b.get("daily_cents") is None:
        return f"orca {today} today"
    line = f"orca {today} / {money(b['daily_cents'] * 10_000)}"
    if b.get("state") == "over" and b.get("mode") == "stop":
        line += " · agents paused"
    return line


def _login(url: str, key: str, transport) -> int:
    from packages.desktop import agents as ag
    from packages.desktop import gateway as gw

    try:
        base = gw.normalize_url(url)
        gw.verify(base, key, transport=transport)
    except gw.GatewayError as exc:
        _err(str(exc))
        return 1
    home = dh.default_home()
    state_dir = home / "agents"
    state_dir.mkdir(parents=True, exist_ok=True)
    connected = []
    for status in ag.detect_agents(home=Path.home(), state_dir=state_dir):
        if not status.installed or status.setup != "auto":
            continue
        try:
            ag.connect_agent(status.id, home=Path.home(), state_dir=state_dir, base_url=base, api_key=key)
            connected.append(status.name)
        except ag.AgentError as exc:
            _err(f"{status.name}: {exc}")
    gw.save(home, base)
    if connected:
        print(f"Connected to {base}: {', '.join(connected)}. Restart open sessions to use it.")
    else:
        print(f"Signed in to {base}, but found no agent Orca can set up automatically.")
    return 0


def _logout() -> int:
    from packages.desktop import agents as ag
    from packages.desktop import gateway as gw

    home = dh.default_home()
    base = gw.load(home)
    state_dir = home / "agents"
    restored = []
    for status in ag.detect_agents(home=Path.home(), state_dir=state_dir):
        if status.connected and status.setup == "auto":
            try:
                ag.disconnect_agent(status.id, home=Path.home(), state_dir=state_dir)
                restored.append(status.name)
            except ag.AgentError as exc:
                _err(f"{status.name}: {exc}")
                return 1
    gw.forget(home)
    where = f" from {base}" if base else ""
    print(f"Signed out{where}. Restored: {', '.join(restored) or 'nothing to restore'}.")
    return 0


def main(
    argv: list[str] | None = None,
    *,
    run_server: Callable[..., None] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    args = _parser().parse_args(argv)

    if args.cmd == "up":
        if args.host not in LOOPBACK:
            _err("orca up only listens on 127.0.0.1: the desktop engine edits files in your home folder. "
                 "To serve a team, run `orcarouter-lite` instead.")
            return 2
        port = args.port if args.port is not None else _default_port()
        if port is None:
            _err("ORCA_PORT must be a port number between 1 and 65535.")
            return 2
        home = dh.default_home()
        instance_secret = secrets.token_urlsafe(32)
        env = dh.desktop_env(home, port=port)
        env["ORCA_INSTANCE_SECRET"] = instance_secret
        dh.write_engine_info(home, base_url=f"http://127.0.0.1:{port}", pid=os.getpid(), secret=instance_secret)
        if args.exit_with_stdin:
            def _parent_gone() -> None:
                dh.remove_engine_info(home, pid=os.getpid())
                os._exit(0)

            threading.Thread(
                target=watch_stdin, args=(sys.stdin, _parent_gone), daemon=True, name="orca-stdin-watch"
            ).start()
        try:
            (run_server or _run_uvicorn)(host="127.0.0.1", port=port, env=env)
        finally:
            dh.remove_engine_info(home, pid=os.getpid())
        return 0

    if args.cmd == "agents":
        body = _request("GET", "/v1/app/agents", transport=transport)
        if body is None:
            return 1
        for a in body["agents"]:
            state = "connected" if a["connected"] else ("installed" if a["installed"] else "not found")
            print(f"{a['id']:<12} {a['name']:<12} {state:<10} {a['setup']}")
        return 0

    if args.cmd == "connect":
        body = _request("POST", f"/v1/app/agents/{args.agent}/connect", transport=transport)
        if body is None:
            return 1
        if body.get("manual"):
            print(f"{body['name']} needs one manual step. {body.get('note', '')}".strip())
            print(f"  Base URL  {body['base_url']}")
            print(f"  API key   {body['api_key']}")
        else:
            print(f"{body['name']} connected. Updated {body.get('config_path')} (backup kept).")
        return 0

    if args.cmd == "disconnect":
        body = _request("POST", f"/v1/app/agents/{args.agent}/disconnect", transport=transport)
        if body is None:
            return 1
        print(f"{body['name']} disconnected; its original settings are restored.")
        return 0

    if args.cmd == "statusline":
        # Runs in Claude Code's status bar: never print errors, never fail.
        body = _request("GET", "/v1/app/summary", transport=transport, quiet=True,
                        params={"tz_offset_minutes": _tz_offset_minutes()})
        print(_statusline(body) if body else "orca —")
        return 0

    if args.cmd == "report":
        body = _request("GET", "/v1/app/summary", transport=transport,
                        params={"tz_offset_minutes": _tz_offset_minutes()})
        if body is None:
            return 1
        sys.stdout.write(_report(body, args.format))
        return 0

    if args.cmd == "link":
        key = args.key.strip()
        if not key.startswith("sk-orca-"):
            _err("That isn't an OrcaRouter key; they start with sk-orca-.")
            return 2
        body = _request("PUT", "/v1/providers/orcarouter", transport=transport, json_body={"api_key": key})
        if body is None:
            return 1
        print(f"Linked to OrcaRouter ({body.get('key_prefix', 'key saved')}). "
              "Requests fall back to it when your own providers fail.")
        return 0

    if args.cmd == "login":
        return _login(args.url, args.key, transport)

    if args.cmd == "logout":
        return _logout()

    if args.cmd == "status":
        body = _request("GET", "/v1/app/summary", transport=transport,
                        params={"tz_offset_minutes": _tz_offset_minutes()})
        if body is None:
            return 1
        if args.json:
            print(json.dumps(body, indent=2))
        else:
            _print_status(body)
        return 0

    return 2  # pragma: no cover - argparse enforces the choices


def entrypoint() -> None:  # pragma: no cover - console script shim
    sys.exit(main())
