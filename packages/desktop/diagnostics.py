"""D8: a diagnostics report to paste into a GitHub issue.

Versions, the OS, each agent's state and last test, providers' health (never
their keys), the routing strategy, local runtimes, and the engine log's last
lines. Orca has no telemetry: the user copies this themselves, so it must be
safe to post. Everything that goes in passes through `redact`: key-shaped
strings are masked (sk-…3f2), the home folder becomes ~, and prompt text in
log lines is left out. Lines are cut short too.

The engine builds the full report (`GET /v1/app/diagnostics`); `orca
diagnostics` prints it, or builds what it can without the engine when the
engine isn't running.
"""

from __future__ import annotations

import os
import platform
import re
from collections import deque
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

LOG_LINES = 40
MAX_LINE = 400

_KEY_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-"),
    (re.compile(r"\bsk_[A-Za-z0-9_\-]{8,}"), "sk_"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{12,}"), "AIza"),
    (re.compile(r"\bxai-[A-Za-z0-9_\-]{8,}"), "xai-"),
    (re.compile(r"\bgsk_[A-Za-z0-9_\-]{8,}"), "gsk_"),
    (re.compile(r"\bfw_[A-Za-z0-9_\-]{8,}"), "fw_"),
    (re.compile(r"\baa-[A-Za-z0-9_\-]{8,}"), "aa-"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}"), "gh_"),
)
_BEARER = re.compile(r"(\b(?:Bearer|Basic)\s+)([A-Za-z0-9_\-\.=+/]{8,})")
_KEY_FIELD = re.compile(
    r"""((?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|x-api-key|x-goog-api-key|\bkey)"""
    r"""["']?\s*[:=]\s*["']?)(?!Bearer\b|Basic\b)([^"'\s,;}\]]{6,})""",
    re.IGNORECASE,
)
# Anything else long and random-looking (40+ letters and digits).
_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{40,}\b")
_PROMPT_FIELD = re.compile(
    r"""(["']?\b(?:messages|content|prompt|input|text|instructions|system|contents|parts|query)\b["']?\s*[:=]\s*)"""
    # A list or object (a messages array) runs to the end of the line: its
    # strings can hold brackets, so it can't be matched to its close.
    r"""(?:"(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?|[\[{].*$)""",
    re.IGNORECASE,
)
_OTHER_HOMES = (
    re.compile(r"/(?:home|Users)/[^/\s\"':]+"),
    # Any case (c:\users\bob) and names with spaces (C:\Users\John Smith).
    re.compile(r"[A-Za-z]:\\\\?Users\\\\?[^\\\"':]+", re.IGNORECASE),
)


def _mask(value: str, prefix: str = "") -> str:
    return f"{prefix}…{value[-3:]}"


def redact(text: str, *, home: Path | str | None) -> str:
    """`text` with keys masked, the home folder as ~ and prompt text left out."""
    out = text
    if home:
        for h in {str(home), str(Path(home).expanduser().resolve())}:
            if h and h not in ("/", "~"):
                out = out.replace(h, "~")
    for pattern in _OTHER_HOMES:
        out = pattern.sub("~", out)
    out = _PROMPT_FIELD.sub(lambda m: f'{m.group(1)}"…"', out)
    for pattern, prefix in _KEY_PATTERNS:
        out = pattern.sub(lambda m, p=prefix: _mask(m.group(0), p), out)
    out = _BEARER.sub(lambda m: m.group(1) + _mask(m.group(2)), out)
    out = _KEY_FIELD.sub(lambda m: m.group(1) + _mask(m.group(2)), out)
    out = _LONG_TOKEN.sub(lambda m: _mask(m.group(0)), out)
    return out if len(out) <= MAX_LINE else out[:MAX_LINE] + "…"


def log_tail(path: Path, lines: int = LOG_LINES) -> list[str]:
    """The last `lines` lines of the engine log (none if there isn't one)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in deque(f, maxlen=lines)]
    except OSError:
        return []


def os_line() -> str:
    system = platform.system()
    if system == "Darwin":
        name = f"macOS {platform.mac_ver()[0]}".strip()
    elif system == "Windows":
        name = f"Windows {platform.release()}"
    else:
        name = f"{system} {platform.release()}"
    return f"{name} {platform.machine()}".strip()


def versions() -> tuple[str, str]:
    """(app, engine) versions. They ship together, so the app's is the
    engine's unless the app says otherwise."""
    from packages.desktop.updates import current_version

    engine = current_version()
    return os.environ.get("ORCA_APP_VERSION") or engine, engine


def last_test_note(test: dict | None) -> str:
    if not test:
        return ""
    at = test.get("at")
    when = at.astimezone().strftime("%H:%M") if isinstance(at, datetime) else (at or "")
    if test.get("ok") is None:
        return ""
    if test.get("ok"):
        return f" (test ok {when})"
    return f" (test failed: {test.get('error') or 'unknown error'})"


def agent_rows(statuses: Iterable, last_tests: dict[str, dict]) -> list[dict]:
    """Installed or connected agents, with their state and last test."""
    rows = []
    for s in statuses:
        if not (s.installed or s.connected):
            continue
        state = ("changed" if s.changed else "connected") if s.connected else "not connected"
        rows.append({"id": s.id, "state": state, "test": last_tests.get(s.id)})
    return rows


def local_lines(runtimes: Iterable) -> list[str]:
    return [
        f"{r.name} {r.url} " + (f"running, {len(r.models)} model{'s' if len(r.models) != 1 else ''}"
                                if r.running else "not running")
        for r in runtimes
    ]


def build(
    *,
    version: str,
    engine: str,
    agents: list[dict],
    providers: list[dict] | None,
    routing: str | None,
    local: list[str] | None,
    log_lines: list[str],
    home: Path | str | None,
    engine_version: str | None = None,
) -> str:
    """The report as plain text, every line redacted."""
    head = f"OrcaRouter Lite {version}"
    if engine_version and engine_version != version:
        head += f" · engine {engine_version}"
    lines = [f"{head} · {os_line()}", f"Engine: {engine}"]
    lines.append(f"Routing: {routing}" if routing else "Routing: unknown (the engine isn't running)")
    lines.append("Agents:" if agents else "Agents: none found")
    width = max((len(a["id"]) for a in agents), default=0)
    for a in agents:
        lines.append(f"  {a['id'].ljust(width)}  {a['state']}{last_test_note(a.get('test'))}")
    if providers is None:
        lines.append("Providers: unknown (the engine isn't running)")
    else:
        shown = [f"{p['provider']} {p['state']}" + (" (env)" if p.get("source") == "env" else "") for p in providers]
        lines.append("Providers: " + (" · ".join(shown) if shown else "none"))
    if local is None:
        lines.append("Local models: not checked")
    else:
        lines.append("Local models: " + (" · ".join(local) if local else "none found"))
    lines.append(f"Last {len(log_lines)} engine log lines (keys masked as sk-…3f2, prompts left out):"
                 if log_lines else "Engine log: empty or missing")
    lines += [f"  {line}" for line in log_lines]
    return "\n".join(redact(line, home=home) for line in lines) + "\n"
