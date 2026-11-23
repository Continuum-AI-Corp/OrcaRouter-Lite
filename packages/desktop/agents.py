"""Connect coding agents to the local Lite engine, and put them back.

The desktop app (and the `orca` CLI) point agents such as Claude Code at the
engine by editing the agent's own config file. Two promises:

1. A connect never destroys settings it does not own. Only the handful of
   keys listed in the agent's spec are written; everything else in the file
   is loaded, kept and written back.
2. A disconnect restores the user's config. If the file is byte-for-byte what
   we wrote, the original bytes come back exactly (or the file is removed if
   we created it). If the user edited the file while connected, only our
   keys are reverted to their previous values, and only where they still
   hold the value we wrote; everything the user changed is kept.

The original file contents and the previous values live in
`<state_dir>/connections.json`, which can contain the user's earlier
credentials, so it is written with mode 0600 like the configs themselves.

Kept free of FastAPI so the CLI, the API route and the tests share it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

STATE_FILE = "connections.json"

# Sentinel stored for keys that did not exist before we wrote them.
_ABSENT = {"__orca_absent__": True}


class AgentError(Exception):
    """Base class for connector errors that should reach the user."""


class UnknownAgent(AgentError):
    pass


class AgentNotSupported(AgentError):
    pass


class AgentConfigError(AgentError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    binaries: tuple[str, ...]
    config_dirs: tuple[str, ...]
    setup: str  # "auto" | "manual" | "unsupported"
    note: str = ""
    config_file: str | None = None  # relative to home, for "auto"
    fmt: str | None = None  # "json" | "yaml"


AGENTS: dict[str, AgentSpec] = {
    spec.id: spec
    for spec in (
        AgentSpec(
            id="claude-code",
            name="Claude Code",
            binaries=("claude",),
            config_dirs=(".claude",),
            setup="auto",
            note="Requests go through your provider keys instead of a Claude subscription while connected.",
            config_file=".claude/settings.json",
            fmt="json",
        ),
        AgentSpec(
            id="codex",
            name="Codex",
            binaries=("codex",),
            config_dirs=(".codex",),
            setup="unsupported",
            note="Codex needs the OpenAI Responses API, which Lite does not serve yet.",
        ),
        AgentSpec(
            id="cursor",
            name="Cursor",
            binaries=("cursor",),
            config_dirs=(".cursor",),
            setup="manual",
            note="Cursor keeps this setting in its own app. Paste the base URL and key under Settings → Models.",
        ),
        AgentSpec(
            id="aider",
            name="Aider",
            binaries=("aider",),
            config_dirs=(),
            setup="auto",
            note="Aider uses model openai/auto while connected.",
            config_file=".aider.conf.yml",
            fmt="yaml",
        ),
        AgentSpec(
            id="gemini-cli",
            name="Gemini CLI",
            binaries=("gemini",),
            config_dirs=(".gemini",),
            setup="unsupported",
            note="Gemini CLI can't be pointed at a custom endpoint from its config yet.",
        ),
    )
}


@dataclass(frozen=True)
class AgentStatus:
    id: str
    name: str
    installed: bool
    setup: str
    connected: bool
    note: str
    config_path: str | None


@dataclass(frozen=True)
class ConnectResult:
    agent_id: str
    manual: bool
    config_path: str | None
    base_url: str
    api_key: str


# ── state file ──────────────────────────────────────────────────────────


def _load_state(state_dir: Path) -> dict[str, Any]:
    p = Path(state_dir) / STATE_FILE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise AgentConfigError(f"Can't read {p}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _write_private(path: Path, data: bytes) -> None:
    """Atomic write with mode 0600 (keeps an existing file's mode if stricter)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600
    if path.exists():
        mode = os.stat(path).st_mode & 0o777 & 0o600 or 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_state(state_dir: Path, state: dict[str, Any]) -> None:
    _write_private(Path(state_dir) / STATE_FILE, json.dumps(state, indent=2).encode())


# ── config file helpers ─────────────────────────────────────────────────


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse(raw: bytes, fmt: str, path: Path) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw) if fmt == "json" else yaml.safe_load(raw)
    except (ValueError, yaml.YAMLError) as exc:
        raise AgentConfigError(f"{path} isn't valid {fmt.upper()}; fix it or move it aside first.") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise AgentConfigError(f"{path} doesn't contain a {fmt.upper()} object.")
    return data


def _dump(data: dict[str, Any], fmt: str) -> bytes:
    if fmt == "json":
        return (json.dumps(data, indent=2) + "\n").encode()
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False).encode()


def _get(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _ABSENT
        cur = cur[part]
    return cur


def _set(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _delete(data: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    stack = [data]
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            return
        stack.append(nxt)
        cur = nxt
    cur.pop(parts[-1], None)
    # prune containers we emptied (e.g. an "env" block that only held our keys)
    for i in range(len(parts) - 1, 0, -1):
        parent = stack[i - 1]
        child_key = parts[i - 1]
        if isinstance(parent.get(child_key), dict) and not parent[child_key]:
            parent.pop(child_key)
        else:
            break


def _desired_values(agent_id: str, base_url: str, api_key: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    if agent_id == "claude-code":
        # Claude Code appends /v1/messages itself, so no /v1 suffix here.
        return {"env.ANTHROPIC_BASE_URL": base, "env.ANTHROPIC_AUTH_TOKEN": api_key}
    if agent_id == "aider":
        return {"openai-api-base": f"{base}/v1", "openai-api-key": api_key, "model": "openai/auto"}
    raise AgentNotSupported(agent_id)  # pragma: no cover - guarded by spec.setup


def _spec(agent_id: str) -> AgentSpec:
    spec = AGENTS.get(agent_id)
    if spec is None:
        raise UnknownAgent(f"Unknown agent: {agent_id}")
    return spec


# ── public API ──────────────────────────────────────────────────────────


def detect_agents(
    *,
    home: Path,
    state_dir: Path,
    which: Callable[[str], str | None] = shutil.which,
) -> list[AgentStatus]:
    home = Path(home)
    state = _load_state(state_dir)
    out: list[AgentStatus] = []
    for spec in AGENTS.values():
        config_path = home / spec.config_file if spec.config_file else None
        installed = (
            any((home / d).is_dir() for d in spec.config_dirs)
            or any(which(b) for b in spec.binaries)
            or bool(config_path and config_path.exists())
        )
        out.append(
            AgentStatus(
                id=spec.id,
                name=spec.name,
                installed=installed,
                setup=spec.setup,
                connected=spec.id in state,
                note=spec.note,
                config_path=str(config_path) if config_path else None,
            )
        )
    return out


def connect_agent(
    agent_id: str,
    *,
    home: Path,
    state_dir: Path,
    base_url: str,
    api_key: str,
) -> ConnectResult:
    spec = _spec(agent_id)
    if spec.setup == "unsupported":
        raise AgentNotSupported(spec.note or f"{spec.name} can't be connected yet.")

    state = _load_state(state_dir)

    if spec.setup == "manual":
        state[agent_id] = {"manual": True}
        _save_state(state_dir, state)
        return ConnectResult(agent_id, True, None, f"{base_url.rstrip('/')}/v1", api_key)

    assert spec.config_file and spec.fmt
    path = Path(home) / spec.config_file
    raw = path.read_bytes() if path.exists() else None
    data = _parse(raw or b"", spec.fmt, path)
    desired = _desired_values(agent_id, base_url, api_key)

    entry = state.get(agent_id)
    if entry is None:
        entry = {
            "path": str(path),
            "original": base64.b64encode(raw).decode() if raw is not None else None,
            "previous": {k: _get(data, k) for k in desired},
        }

    for k, v in desired.items():
        _set(data, k, v)
    written = _dump(data, spec.fmt)
    _write_private(path, written)

    entry["written_sha256"] = _sha(written)
    entry["values"] = desired
    state[agent_id] = entry
    _save_state(state_dir, state)
    return ConnectResult(agent_id, False, str(path), base_url, api_key)


def disconnect_agent(agent_id: str, *, home: Path, state_dir: Path) -> None:
    spec = _spec(agent_id)
    state = _load_state(state_dir)
    entry = state.get(agent_id)
    if entry is None:
        return

    if not entry.get("manual"):
        path = Path(entry["path"])
        current = path.read_bytes() if path.exists() else None
        if current is not None and _sha(current) == entry.get("written_sha256"):
            original = entry.get("original")
            if original is None:
                path.unlink()
            else:
                _write_private(path, base64.b64decode(original))
        elif current is not None:
            data = _parse(current, spec.fmt or "json", path)
            for k, ours in (entry.get("values") or {}).items():
                if _get(data, k) != ours:
                    continue  # the user changed it after we connected; leave it
                prev = entry.get("previous", {}).get(k, _ABSENT)
                if prev == _ABSENT:
                    _delete(data, k)
                else:
                    _set(data, k, prev)
            _write_private(path, _dump(data, spec.fmt or "json"))

    del state[agent_id]
    _save_state(state_dir, state)
