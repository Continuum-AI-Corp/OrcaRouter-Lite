"""Connect coding agents to the local Lite engine, and put them back.

The desktop app (and the `orca` CLI) point agents such as Claude Code at the
engine by editing the agent's own config file. Two promises:

1. A connect never destroys settings it does not own. Only the handful of
   keys listed in the agent's spec are written; everything else in the file
   is loaded, kept and written back.
2. A disconnect restores the user's config. If the file is byte-for-byte what
   we wrote, the original bytes (and file mode) come back exactly, or the
   file is removed if we created it. If the user edited the file while
   connected, only our keys are reverted to their previous values, and only
   where they still hold the value we wrote; everything the user changed is
   kept. YAML files are edited line by line so comments survive.

Symlinked configs (dotfile managers) are written through to their target, so
the link stays a link. Connect and disconnect hold a lock on the state folder,
so the app and the CLI can't interleave and lose the original backup.

The original file contents and the previous values live in
`<state_dir>/connections.json`, which can contain the user's earlier
credentials, so it is written with mode 0600 like the configs themselves.

Kept free of FastAPI so the CLI, the API route and the tests share it.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

STATE_FILE = "connections.json"

# Returned by _get for a key that isn't in the file. Never persisted: keys
# that were absent before a connect are recorded in the entry's "absent" list.
_MISSING = object()
_PROCESS_LOCK = threading.Lock()


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


# ── locking and files ───────────────────────────────────────────────────


@contextlib.contextmanager
def _locked(state_dir: Path):
    """Serialise connect/disconnect across threads and processes."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK:
        fd = os.open(state_dir / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":  # pragma: no cover - Windows
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing releases the lock


def _load_state(state_dir: Path) -> dict[str, Any]:
    p = Path(state_dir) / STATE_FILE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise AgentConfigError(f"Can't read {p}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _target(path: Path) -> Path:
    """Write through symlinks so a dotfile-managed config stays a link."""
    return path.resolve() if path.is_symlink() else path


def _write_atomic(path: Path, data: bytes, mode: int | None = None) -> None:
    """Atomic replace of `path` (or its symlink target).

    New files get 0600; existing files keep their mode unless `mode` is given.
    """
    real = _target(path)
    real.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = os.stat(real).st_mode & 0o777 if real.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=f".{real.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _save_state(state_dir: Path, state: dict[str, Any]) -> None:
    _write_atomic(Path(state_dir) / STATE_FILE, json.dumps(state, indent=2).encode(), 0o600)


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AgentConfigError(f"Can't read {path}: {exc.strerror or exc}") from exc


# ── config formats ──────────────────────────────────────────────────────


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


def _get(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _check_containers(data: dict[str, Any], dotted: str, path: Path) -> None:
    """Refuse rather than overwrite a parent that exists but isn't an object."""
    cur: Any = data
    parts = dotted.split(".")
    for i, part in enumerate(parts[:-1]):
        nxt = cur.get(part, _MISSING) if isinstance(cur, dict) else _MISSING
        if nxt is _MISSING:
            return
        if not isinstance(nxt, dict):
            where = ".".join(parts[: i + 1])
            raise AgentConfigError(f"{path}: `{where}` should be an object; fix it before connecting.")
        cur = nxt


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
    for i in range(len(parts) - 1, 0, -1):  # prune containers we emptied
        parent, child = stack[i - 1], parts[i - 1]
        if isinstance(parent.get(child), dict) and not parent[child]:
            parent.pop(child)
        else:
            break


def _yaml_scalar(value: Any) -> str:
    # JSON strings, numbers, booleans and null are valid YAML flow scalars.
    return json.dumps(value, ensure_ascii=False)


def _yaml_key_span(lines: list[str], key: str) -> tuple[int, int] | None:
    """Line range [start, end) of a top-level `key:` and its indented continuation."""
    pat = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(lines):
        if pat.match(line):
            j = i + 1
            while j < len(lines) and lines[j][:1] in (" ", "\t") and lines[j].strip():
                j += 1
            return i, j
    return None


def _edit_yaml(raw: bytes, changes: dict[str, Any], path: Path) -> bytes:
    """Set (or, for _MISSING, remove) top-level keys line by line.

    Keeps every comment and every other line as it was. Falls back to a full
    re-dump only if the line edit wouldn't parse back to the intended values.
    """
    text = raw.decode("utf-8") if raw else ""
    lines = text.splitlines()
    for key, value in changes.items():
        span = _yaml_key_span(lines, key)
        new = [] if value is _MISSING else [f"{key}: {_yaml_scalar(value)}"]
        if span:
            lines[span[0] : span[1]] = new
        else:
            lines.extend(new)
    out = "\n".join(lines) + ("\n" if lines else "")
    parsed = _parse(out.encode(), "yaml", path)
    if all((_get(parsed, k) is _MISSING) if v is _MISSING else parsed.get(k) == v for k, v in changes.items()):
        return out.encode("utf-8")
    data = _parse(raw or b"", "yaml", path)  # pragma: no cover - exotic layouts
    for key, value in changes.items():
        if value is _MISSING:
            data.pop(key, None)
        else:
            data[key] = value
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode("utf-8")


def _apply(raw: bytes | None, fmt: str, changes: dict[str, Any], path: Path) -> bytes:
    if fmt == "yaml":
        return _edit_yaml(raw or b"", changes, path)
    data = _parse(raw or b"", "json", path)
    for key, value in changes.items():
        if value is _MISSING:
            _delete(data, key)
        else:
            _set(data, key, value)
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


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

    with _locked(state_dir):
        state = _load_state(state_dir)

        if spec.setup == "manual":
            state[agent_id] = {"manual": True}
            _save_state(state_dir, state)
            return ConnectResult(agent_id, True, None, f"{base_url.rstrip('/')}/v1", api_key)

        assert spec.config_file and spec.fmt
        path = Path(home) / spec.config_file
        raw = _read(path)
        data = _parse(raw or b"", spec.fmt, path)
        desired = _desired_values(agent_id, base_url, api_key)
        for key in desired:
            _check_containers(data, key, path)

        entry = state.get(agent_id)
        if entry is None:
            previous = {k: _get(data, k) for k in desired}
            real = _target(path)
            entry = {
                "path": str(path),
                "original": base64.b64encode(raw).decode() if raw is not None else None,
                "mode": (os.stat(real).st_mode & 0o777) if raw is not None else None,
                "previous": {k: v for k, v in previous.items() if v is not _MISSING},
                "absent": [k for k, v in previous.items() if v is _MISSING],
            }

        written = _apply(raw, spec.fmt, desired, path)
        try:
            _write_atomic(path, written)
        except OSError as exc:
            raise AgentConfigError(f"Can't write {path}: {exc.strerror or exc}") from exc

        entry["written_sha256"] = _sha(written)
        entry["values"] = desired
        state[agent_id] = entry
        _save_state(state_dir, state)
        return ConnectResult(agent_id, False, str(path), base_url, api_key)


def disconnect_agent(agent_id: str, *, home: Path, state_dir: Path) -> None:
    spec = _spec(agent_id)
    with _locked(state_dir):
        state = _load_state(state_dir)
        entry = state.get(agent_id)
        if entry is None:
            return
        if not isinstance(entry, dict) or not (entry.get("manual") or "path" in entry):
            raise AgentConfigError(f"The saved connection for {spec.name} is damaged; reconnect it to repair.")

        if not entry.get("manual"):
            path = Path(entry["path"])
            current = _read(path)
            try:
                if current is not None and _sha(current) == entry.get("written_sha256"):
                    original = entry.get("original")
                    if original is None:
                        _target(path).unlink()
                    else:
                        _write_atomic(path, base64.b64decode(original), entry.get("mode"))
                elif current is not None:
                    data = _parse(current, spec.fmt or "json", path)
                    changes: dict[str, Any] = {}
                    for key, ours in (entry.get("values") or {}).items():
                        if _get(data, key) != ours:
                            continue  # the user changed it after we connected; leave it
                        if key in (entry.get("absent") or []):
                            changes[key] = _MISSING
                        elif key in (entry.get("previous") or {}):
                            changes[key] = entry["previous"][key]
                    if changes:
                        _write_atomic(path, _apply(current, spec.fmt or "json", changes, path))
            except OSError as exc:
                raise AgentConfigError(f"Can't restore {path}: {exc.strerror or exc}") from exc

        del state[agent_id]
        _save_state(state_dir, state)
