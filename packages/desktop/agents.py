"""Connect coding agents to the local Lite engine, and put them back.

The desktop app (and the `orca` CLI) point agents such as Claude Code at the
engine by editing the agent's own config files. Two promises:

1. A connect never destroys settings it does not own. Only the handful of
   keys listed in the agent's spec are written; everything else in the file
   is loaded, kept and written back.
2. A disconnect restores the user's config. If the file is byte-for-byte what
   we wrote, the original bytes (and file mode) come back exactly, or the
   file is removed if we created it. If the user edited the file while
   connected, only our keys are reverted to their previous values, and only
   where they still hold the value we wrote; everything the user changed is
   kept. YAML, TOML and .env files are edited line by line so comments
   survive.

Agents whose config refuses (Command Code) or discourages literal keys get a
reference to a key file in `<state_dir>/keys/` (0600) instead; it is removed
on disconnect.

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
import shlex
import shutil
import tempfile
import threading
import tomllib
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
    # (path relative to home, format) for "auto"; format is json, yaml, toml or dotenv.
    files: tuple[tuple[str, str], ...] = ()
    # The note is a warning the user should read before connecting.
    warn: bool = False

    @property
    def config_file(self) -> str | None:
        return self.files[0][0] if self.files else None


PROVIDER_ID = "orca"  # the provider entry we add to agents that list providers

_WINDOWS = os.name == "nt"
# Hermes keeps its home in %LOCALAPPDATA% on Windows; Goose in %APPDATA%.
_HERMES_DIR = "AppData/Local/hermes" if _WINDOWS else ".hermes"
_GOOSE_DIR = "AppData/Roaming/Block/goose/config" if _WINDOWS else ".config/goose"


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
            files=((".claude/settings.json", "json"),),
            warn=True,
        ),
        AgentSpec(
            id="codex",
            name="Codex",
            binaries=("codex",),
            config_dirs=(".codex",),
            setup="auto",
            note="Codex uses Lite's auto model while connected; choose another with /model.",
            files=((".codex/config.toml", "toml"),),
        ),
        AgentSpec(
            id="gemini-cli",
            name="Gemini CLI",
            binaries=("gemini",),
            config_dirs=(".gemini",),
            setup="auto",
            note="Gemini CLI signs in through Lite while connected. It reads ~/.gemini/.env only in folders you trust.",
            files=((".gemini/.env", "dotenv"), (".gemini/settings.json", "json")),
        ),
        AgentSpec(
            id="opencode",
            name="OpenCode",
            binaries=("opencode",),
            config_dirs=(".config/opencode",),
            setup="auto",
            note="OpenCode uses the orca/auto model while connected.",
            files=((".config/opencode/opencode.json", "json"),),
        ),
        AgentSpec(
            id="cline",
            name="Cline",
            binaries=("cline",),
            config_dirs=(".cline",),
            setup="manual",
            note=(
                "Cline keeps this setting in its own storage. In Cline, choose API Provider → "
                "OpenAI Compatible, paste the base URL and key, and use model ID auto."
            ),
        ),
        AgentSpec(
            id="command-code",
            name="Command Code",
            # Not `cmd`: on Windows that's the command prompt.
            binaries=("command-code", "commandcode"),
            config_dirs=(".commandcode",),
            setup="auto",
            note="In Command Code, choose the Orca provider's auto model with /model.",
            files=((".commandcode/providers.json", "json"),),
        ),
        AgentSpec(
            id="hermes",
            name="Hermes Agent",
            binaries=("hermes",),
            config_dirs=(_HERMES_DIR,),
            setup="auto",
            note="Hermes uses the orca provider's auto model while connected; switch with /model.",
            files=((f"{_HERMES_DIR}/config.yaml", "yaml"),),
        ),
        AgentSpec(
            id="pi",
            name="Pi",
            binaries=("pi",),
            config_dirs=(".pi",),
            setup="auto",
            note="Pi starts on Lite's auto model while connected; choose another with /model.",
            files=((".pi/agent/models.json", "json"), (".pi/agent/settings.json", "json")),
        ),
        AgentSpec(
            id="omp",
            name="OMP",
            binaries=("omp",),
            config_dirs=(".omp",),
            setup="auto",
            note="OMP's default role uses orca/auto while connected; other roles keep their models.",
            files=((".omp/agent/models.yml", "yaml"), (".omp/agent/config.yml", "yaml")),
        ),
        AgentSpec(
            id="kilo",
            name="Kilo Code",
            binaries=("kilo", "kilocode"),
            config_dirs=(".config/kilo",),
            setup="auto",
            note="Kilo uses the orca/auto model while connected. A model set in kilo.jsonc takes precedence.",
            files=((".config/kilo/kilo.json", "json"),),
        ),
        AgentSpec(
            id="openclaw",
            name="OpenClaw",
            binaries=("openclaw",),
            config_dirs=(".openclaw",),
            setup="auto",
            note="OpenClaw agents use orca/auto as their primary model while connected; fallbacks stay as they are.",
            files=((".openclaw/openclaw.json", "json"),),
        ),
        AgentSpec(
            id="kimi-code",
            name="Kimi Code",
            binaries=("kimi",),
            config_dirs=(".kimi-code",),
            setup="auto",
            note="Kimi Code starts on Lite's auto model while connected; choose another with /model.",
            files=((".kimi-code/config.toml", "toml"),),
        ),
        AgentSpec(
            id="goose",
            name="Goose",
            binaries=("goose",),
            config_dirs=(_GOOSE_DIR,),
            setup="auto",
            note="Goose uses the orca provider's auto model while connected.",
            files=((f"{_GOOSE_DIR}/custom_providers/orca.json", "json"), (f"{_GOOSE_DIR}/config.yaml", "yaml")),
        ),
        AgentSpec(
            id="cursor",
            name="Cursor",
            binaries=("cursor",),
            config_dirs=(".cursor",),
            setup="manual",
            note=(
                "Cursor keeps this setting in its own app. Under Settings → Models, turn on Override OpenAI Base URL, paste the base URL and key, and add a custom model named auto."
            ),
        ),
        AgentSpec(
            id="aider",
            name="Aider",
            binaries=("aider",),
            config_dirs=(),
            setup="auto",
            note="Aider uses model openai/auto while connected.",
            files=((".aider.conf.yml", "yaml"),),
        ),
        AgentSpec(
            id="zed",
            name="Zed",
            binaries=("zed", "zeditor"),
            config_dirs=(".config/zed",),
            setup="manual",
            note=(
                "Zed keeps API keys in your keychain. In settings.json add "
                "language_models.openai_compatible.Orca with the base URL as api_url and a model named auto, "
                "then paste the key in the Agent panel's Orca settings (or set ORCA_API_KEY before starting Zed)."
            ),
        ),
        AgentSpec(
            id="openhands",
            name="OpenHands",
            binaries=("openhands",),
            config_dirs=(".openhands",),
            setup="manual",
            note=(
                "In OpenHands, open /settings → Advanced, set the custom model to openai/auto, "
                "and paste the base URL and key."
            ),
        ),
        AgentSpec(
            id="deepseek-harness",
            name="DeepSeek Harness",
            binaries=("dsh",),
            config_dirs=(".dsh",),
            setup="manual",
            note=(
                "In DeepSeek Harness, add a custom OpenAI-compatible provider under Settings → Models "
                "with the base URL and key, and use model auto."
            ),
        ),
        AgentSpec(
            id="zcode",
            name="ZCode",
            binaries=("zcode",),
            config_dirs=(".zcode",),
            setup="manual",
            note=(
                "In ZCode, choose Add provider → Create custom provider, pick OpenAI chat completions, "
                "paste the base URL and key, and add model auto."
            ),
        ),
    )
}

# Agents whose config reads the key from a file we keep, not a literal.
KEY_FILE_AGENTS = frozenset({"opencode", "command-code", "kilo", "goose"})


@dataclass(frozen=True)
class AgentStatus:
    id: str
    name: str
    installed: bool
    setup: str
    connected: bool
    note: str
    config_path: str | None
    warn: bool = False
    # D5: connected per Orca's records, but the values Orca wrote are gone
    # from the agent's config (an update or the agent's own setup replaced
    # them), so its requests no longer go through Orca.
    changed: bool = False


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
        if fmt == "json":
            data = json.loads(raw)
        elif fmt == "toml":
            data = tomllib.loads(raw.decode("utf-8"))
        elif fmt == "dotenv":
            data = _parse_dotenv(raw.decode("utf-8"))
        else:
            data = yaml.safe_load(raw)
    except (ValueError, UnicodeDecodeError, yaml.YAMLError) as exc:
        # tomllib.TOMLDecodeError and json.JSONDecodeError are ValueErrors.
        label = {"dotenv": ".env"}.get(fmt, fmt.upper())
        raise AgentConfigError(f"{path} isn't valid {label}; fix it or move it aside first.") from exc
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


_YAML_PLAIN_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")


def _yaml_lines(key: str, value: Any, indent: str) -> list[str]:
    """`key: value` as YAML lines at `indent`; mappings and lists in block style."""
    if isinstance(value, (dict, list)) and value:
        dumped = yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1 << 20)
        return [indent + line for line in dumped.splitlines()]
    name = key if _YAML_PLAIN_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)
    return [f"{indent}{name}: {_yaml_scalar(value)}"]


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _yaml_key_span(lines: list[str], key: str, start: int = 0, end: int | None = None, indent: str = "") -> tuple[int, int] | None:
    """Line range [first, last) of `key:` at `indent` and everything nested under it.

    Blank and comment lines inside the block belong to it; trailing ones
    belong to whatever follows.
    """
    end = len(lines) if end is None else end
    pat = re.compile(rf"^{re.escape(indent)}(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}')\s*:(\s|$)")
    for i in range(start, end):
        if not pat.match(lines[i]):
            continue
        last, j = i, i + 1
        while j < end:
            line = lines[j]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                j += 1
                continue
            own = _indent_of(line)
            # Deeper lines nest under the key; so does a block list at the key's own indent.
            if len(own) > len(indent) or (own == indent and stripped.startswith("- ")):
                last = j
                j += 1
                continue
            break
        return i, last + 1
    return None


class _YamlLayout(Exception):
    """The line editor can't place a change; re-dump instead."""


def _yaml_set_child(lines: list[str], parent: str, child: str, value: Any) -> None:
    span = _yaml_key_span(lines, parent)
    if span is None:
        if value is not _MISSING:
            lines.extend([f"{parent}:"] + _yaml_lines(child, value, "  "))
        return
    first, last = span
    inline = lines[first].split(":", 1)[1].strip()
    if inline and not inline.startswith("#"):
        raise _YamlLayout  # `parent: {a: b}` or a scalar; let the re-dump handle it
    indent = next(
        (_indent_of(lines[i]) for i in range(first + 1, last)
         if lines[i].strip() and not lines[i].strip().startswith("#")),
        "  ",
    )
    if not indent or "\t" in indent:
        raise _YamlLayout
    new = [] if value is _MISSING else _yaml_lines(child, value, indent)
    sub = _yaml_key_span(lines, child, first + 1, last, indent)
    if sub:
        lines[sub[0] : sub[1]] = new
        return
    if not new:
        return
    # After the block's last content line, so trailing blank lines stay put.
    lines[last:last] = new


def _yaml_matches(parsed: dict[str, Any], changes: dict[str, Any]) -> bool:
    return all((_get(parsed, k) is _MISSING) if v is _MISSING else _get(parsed, k) == v for k, v in changes.items())


def _edit_yaml(raw: bytes, changes: dict[str, Any], path: Path) -> bytes:
    """Set (or, for _MISSING, remove) keys one or two levels deep, line by line.

    Keeps every comment and every other line as it was. Falls back to a full
    re-dump only if the line edit can't place a change or wouldn't parse back
    to the intended values.
    """
    text = raw.decode("utf-8") if raw else ""
    lines = text.splitlines()
    try:
        for key, value in changes.items():
            parts = key.split(".")
            if len(parts) == 2:
                _yaml_set_child(lines, parts[0], parts[1], value)
                parent = _yaml_key_span(lines, parts[0])
                if parent and parent[1] - parent[0] == 1 and not lines[parent[0]].split(":", 1)[1].strip():
                    del lines[parent[0]]  # we removed its last child
                continue
            if len(parts) > 2:
                raise _YamlLayout
            span = _yaml_key_span(lines, key)
            new = [] if value is _MISSING else _yaml_lines(key, value, "")
            if span:
                lines[span[0] : span[1]] = new
            else:
                lines.extend(new)
        out = "\n".join(lines) + ("\n" if lines else "")
        if _yaml_matches(_parse(out.encode(), "yaml", path), changes):
            return out.encode("utf-8")
    except (_YamlLayout, AgentConfigError):
        pass
    data = _parse(raw or b"", "yaml", path)
    for key, value in changes.items():
        if value is _MISSING:
            _delete(data, key)
        else:
            _set(data, key, value)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode("utf-8")


# TOML (Codex): top-level keys and whole [tables], edited line by line.

_TOML_HEADER = re.compile(r"^\s*\[")


_TOML_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _toml_key(key: str) -> str:
    return key if _TOML_BARE_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    """Render a value tomllib produced (ours, or the user's on a restore)."""
    import datetime as _dt

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        # JSON's string escapes are a subset of TOML basic-string escapes.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()) + " }"
    raise AgentConfigError(f"Can't write {value!r} to a TOML file.")


def _toml_table_span(lines: list[str], table: str) -> tuple[int, int] | None:
    header = re.compile(rf"^\s*\[\s*{re.escape(table)}\s*\]\s*(#.*)?$")
    for i, line in enumerate(lines):
        if header.match(line):
            j = i + 1
            while j < len(lines) and not _TOML_HEADER.match(lines[j]):
                j += 1
            return i, j
    return None


def _edit_toml(raw: bytes, changes: dict[str, Any], path: Path) -> bytes:
    lines = (raw.decode("utf-8") if raw else "").splitlines()
    for key, value in changes.items():
        if "." in key:  # a whole table, e.g. model_providers.orca
            span = _toml_table_span(lines, key)
            new = [] if value is _MISSING else [f"[{key}]"] + [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()]
            if span:
                lines[span[0] : span[1]] = new + ([""] if new and span[1] < len(lines) else [])
            elif new:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend(new)
            continue
        top_end = next((i for i, line in enumerate(lines) if _TOML_HEADER.match(line)), len(lines))
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
        found = next((i for i in range(top_end) if pat.match(lines[i])), None)
        if value is _MISSING:
            if found is not None:
                del lines[found]
        elif found is not None:
            lines[found] = f"{key} = {_toml_value(value)}"
        else:
            last = max((i for i in range(top_end) if lines[i].strip()), default=-1)
            lines.insert(last + 1, f"{key} = {_toml_value(value)}")
            if last + 2 < len(lines) and _TOML_HEADER.match(lines[last + 2]):
                lines.insert(last + 2, "")
    while lines and not lines[-1].strip():
        lines.pop()
    out = "\n".join(lines) + ("\n" if lines else "")
    try:
        parsed = _parse(out.encode(), "toml", path)
    except AgentConfigError:
        raise AgentConfigError(f"Couldn't safely edit {path}; its layout is unusual. Add the settings by hand.") from None
    if not all((_get(parsed, k) is _MISSING) if v is _MISSING else _get(parsed, k) == v for k, v in changes.items()):
        raise AgentConfigError(f"Couldn't safely edit {path}; its layout is unusual. Add the settings by hand.")
    return out.encode("utf-8")


# .env (Gemini CLI): KEY=value lines.

_DOTENV_SAFE = re.compile(r"[A-Za-z0-9_./:@+\-=,]*")


def _parse_dotenv(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[len("export ") :].lstrip()
        if "=" not in s:
            continue
        key, value = (part.strip() for part in s.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]  # single quotes: literal
        elif len(value) >= 2 and value[0] == value[-1] == '"':
            value = re.sub(r'\\(["\\n])', lambda m: "\n" if m.group(1) == "n" else m.group(1), value[1:-1])
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        data[key] = value
    return data


def _dotenv_value(value: str) -> str:
    """Quote a value so _parse_dotenv (and dotenv libraries) read it back unchanged."""
    if _DOTENV_SAFE.fullmatch(value):
        return value
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _edit_dotenv(raw: bytes, changes: dict[str, Any], path: Path) -> bytes:
    lines = (raw.decode("utf-8") if raw else "").splitlines()
    for key, value in changes.items():
        pat = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
        hits = [i for i, line in enumerate(lines) if pat.match(line)]
        for i in reversed(hits[1:] if value is not _MISSING else hits):
            del lines[i]
        if value is _MISSING:
            continue
        new = f"{key}={_dotenv_value(str(value))}"
        if hits:
            lines[hits[0]] = new
        else:
            lines.append(new)
    out = "\n".join(lines) + ("\n" if lines else "")
    parsed = _parse_dotenv(out)
    if not all((k not in parsed) if v is _MISSING else parsed.get(k) == v for k, v in changes.items()):
        raise AgentConfigError(f"Couldn't safely edit {path}; add the settings by hand.")
    return out.encode("utf-8")


def _apply(raw: bytes | None, fmt: str, changes: dict[str, Any], path: Path) -> bytes:
    if fmt == "yaml":
        return _edit_yaml(raw or b"", changes, path)
    if fmt == "toml":
        return _edit_toml(raw or b"", changes, path)
    if fmt == "dotenv":
        return _edit_dotenv(raw or b"", changes, path)
    data = _parse(raw or b"", "json", path)
    for key, value in changes.items():
        if value is _MISSING:
            _delete(data, key)
        else:
            _set(data, key, value)
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _key_command(path: Path, *, windows: bool | None = None) -> str:
    """A Command Code `!command` apiKey that prints the key file."""
    if windows if windows is not None else os.name == "nt":
        return f'!type "{path}"'
    return f"!cat {shlex.quote(str(path))}"


def _goose_auth(path: Path, *, windows: bool | None = None) -> dict[str, Any]:
    """A Goose `auth` block whose command prints the key file (run without a shell)."""
    if windows if windows is not None else os.name == "nt":
        return {"command": "cmd", "args": ["/d", "/c", "type", str(path)]}
    return {"command": "cat", "args": [str(path)]}


def _opencode_provider(base: str, key_file: Path) -> dict[str, Any]:
    """An OpenCode-style provider (OpenCode and its fork Kilo) reading the key from a file."""
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "OrcaRouter Lite",
        "options": {"baseURL": f"{base}/v1", "apiKey": f"{{file:{key_file}}}"},
        "models": {"auto": {"name": "Orca auto-routing"}},
    }


# What we tell agents that ask for limits about the `auto` model.
_CONTEXT_WINDOW = 200_000
_MAX_OUTPUT = 32_000


def _desired_values(
    agent_id: str,
    base_url: str,
    api_key: str,
    *,
    key_file: Path | None,
    current: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """The settings to write, per config file (relative path → dotted key → value)."""
    base = base_url.rstrip("/")
    if agent_id == "claude-code":
        # Claude Code appends /v1/messages itself, so no /v1 suffix here.
        return {".claude/settings.json": {"env.ANTHROPIC_BASE_URL": base, "env.ANTHROPIC_AUTH_TOKEN": api_key}}
    if agent_id == "aider":
        return {".aider.conf.yml": {"openai-api-base": f"{base}/v1", "openai-api-key": api_key, "model": "openai/auto"}}
    if agent_id == "codex":
        # Codex speaks only the Responses API and appends /responses itself.
        provider = {
            "name": "OrcaRouter Lite",
            "base_url": f"{base}/v1",
            "wire_api": "responses",
            "experimental_bearer_token": api_key,
        }
        return {".codex/config.toml": {
            "model_provider": PROVIDER_ID,
            "model": "auto",
            f"model_providers.{PROVIDER_ID}": provider,
        }}
    if agent_id == "gemini-cli":
        # GOOGLE_GEMINI_BASE_URL selects Gemini CLI's "gateway" auth; a saved
        # selectedType would override it, so set that too. The google-genai
        # SDK appends /v1beta itself.
        return {
            ".gemini/.env": {"GOOGLE_GEMINI_BASE_URL": base, "GEMINI_API_KEY": api_key},
            ".gemini/settings.json": {"security.auth.selectedType": "gateway"},
        }
    if agent_id == "opencode":
        assert key_file is not None
        provider = _opencode_provider(base, key_file)
        return {".config/opencode/opencode.json": {f"provider.{PROVIDER_ID}": provider, "model": f"{PROVIDER_ID}/auto"}}
    if agent_id == "command-code":
        assert key_file is not None
        existing = current.get(".commandcode/providers.json", {})
        # Command Code reads either map; add to the one the user already has.
        section = "providers" if isinstance(existing.get("providers"), dict) and "provider" not in existing else "provider"
        provider = {
            "name": "OrcaRouter Lite",
            "baseURL": f"{base}/v1",
            "api": "openai-completions",
            "apiKey": _key_command(key_file),
            "models": {"auto": {"name": "Orca auto-routing"}},
        }
        return {".commandcode/providers.json": {f"{section}.{PROVIDER_ID}": provider}}
    if agent_id == "hermes":
        provider = {"api": f"{base}/v1", "api_key": api_key, "transport": "chat_completions", "default_model": "auto"}
        return {f"{_HERMES_DIR}/config.yaml": {
            f"providers.{PROVIDER_ID}": provider,
            "model.provider": f"custom:{PROVIDER_ID}",
            "model.default": "auto",
            # A base_url left by another provider would win over the entry's.
            "model.base_url": f"{base}/v1",
        }}
    if agent_id in ("pi", "omp"):
        provider = {
            "baseUrl": f"{base}/v1",
            "api": "openai-completions",
            "apiKey": api_key,
            "models": [{"id": "auto", "name": "Orca auto-routing", "input": ["text", "image"],
                        "contextWindow": _CONTEXT_WINDOW, "maxTokens": _MAX_OUTPUT}],
        }
        if agent_id == "pi":
            return {
                ".pi/agent/models.json": {f"providers.{PROVIDER_ID}": provider},
                ".pi/agent/settings.json": {"defaultProvider": PROVIDER_ID, "defaultModel": "auto"},
            }
        return {
            ".omp/agent/models.yml": {f"providers.{PROVIDER_ID}": provider},
            ".omp/agent/config.yml": {"modelRoles.default": f"{PROVIDER_ID}/auto"},
        }
    if agent_id == "kilo":
        assert key_file is not None
        return {".config/kilo/kilo.json": {f"provider.{PROVIDER_ID}": _opencode_provider(base, key_file),
                                           "model": f"{PROVIDER_ID}/auto"}}
    if agent_id == "openclaw":
        provider = {
            "baseUrl": f"{base}/v1",
            "apiKey": api_key,
            "api": "openai-completions",
            "models": [{"id": "auto", "name": "Orca auto-routing", "input": ["text", "image"],
                        "contextWindow": _CONTEXT_WINDOW, "maxTokens": _MAX_OUTPUT,
                        # Lite picks the served model per request; that's expected, not a reroute.
                        "responseModelEquivalent": True}],
        }
        model = _get(current.get(".openclaw/openclaw.json", {}), "agents.defaults.model")
        primary = "agents.defaults.model" if isinstance(model, str) else "agents.defaults.model.primary"
        return {".openclaw/openclaw.json": {f"models.providers.{PROVIDER_ID}": provider, primary: f"{PROVIDER_ID}/auto"}}
    if agent_id == "kimi-code":
        alias = f"{PROVIDER_ID}-auto"
        return {".kimi-code/config.toml": {
            "default_model": alias,
            f"providers.{PROVIDER_ID}": {"type": "openai", "base_url": f"{base}/v1", "api_key": api_key},
            f"models.{alias}": {
                "provider": PROVIDER_ID,
                "model": "auto",
                "max_context_size": _CONTEXT_WINDOW,
                "capabilities": ["tool_use", "image_in"],
                "display_name": "Orca auto-routing",
            },
        }}
    if agent_id == "goose":
        assert key_file is not None
        provider = {
            "name": PROVIDER_ID,
            "engine": "openai",
            "display_name": "OrcaRouter Lite",
            "description": "Routes each request through OrcaRouter Lite on this computer.",
            "base_url": f"{base}/v1",
            "models": [{"name": "auto", "context_limit": _CONTEXT_WINDOW}],
            "supports_streaming": True,
            "requires_auth": True,
            # Goose reads keys only from the keychain or the environment; a
            # command that prints our key file needs neither.
            "auth": _goose_auth(key_file),
            "dynamic_models": False,
        }
        return {
            f"{_GOOSE_DIR}/custom_providers/{PROVIDER_ID}.json": provider,
            f"{_GOOSE_DIR}/config.yaml": {"GOOSE_PROVIDER": PROVIDER_ID, "GOOSE_MODEL": "auto"},
        }
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
    try:
        state = _load_state(state_dir)
    except AgentConfigError:
        # Read-only callers (the panel's poll, diagnostics, the statusline)
        # show nothing connected rather than fail; connect and disconnect
        # still refuse a damaged file, so the backups in it aren't lost.
        state = {}
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
                warn=spec.warn,
                changed=spec.id in state and _entry_changed(spec, state[spec.id]),
            )
        )
    return out


# ── D5: has the agent undone Orca's settings? ───────────────────────────

# A setting that decides where the agent's requests go: a base URL, a key
# (or the reference to Orca's key file) or the provider the agent selects.
# Model choices aren't among them: picking another model inside the agent
# (Codex's /model, say) still goes through Orca.
_ANCHOR_MARKS = ("key", "token", "provider", "selectedtype")


# Model strings that also pick the provider (OpenCode's "orca/auto", Kimi
# Code's "orca-auto"): any other orca model keeps going through Orca, so
# only the prefix has to survive.
_PROVIDER_MODEL_PREFIXES = (f"{PROVIDER_ID}/", f"{PROVIDER_ID}-")


def _provider_model_prefix(value: Any) -> str | None:
    if isinstance(value, str):
        return next((p for p in _PROVIDER_MODEL_PREFIXES if value.startswith(p)), None)
    return None


def _anchors(prefix: str, value: Any) -> list[tuple[str, Any]]:
    """The (dotted key, value) leaves of what Orca wrote that route the agent."""
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in _anchors(f"{prefix}.{k}", v)]
    name = prefix.rsplit(".", 1)[-1].lower()
    is_url = isinstance(value, str) and value.startswith(("http://", "https://"))
    routes = is_url or any(m in name for m in _ANCHOR_MARKS) or _provider_model_prefix(value) is not None
    return [(prefix, value)] if routes else []


def _still_routes(current: Any, written: Any) -> bool:
    prefix = _provider_model_prefix(written)
    if prefix is not None and current != written:
        return isinstance(current, str) and current.startswith(prefix)
    return current == written


def _file_replaced(fentry: dict, data: dict[str, Any] | None) -> bool:
    """True when the file no longer holds every routing value Orca wrote
    (`data` None: the file is gone or can't be read)."""
    if data is None:
        return True
    for key, written in (fentry.get("values") or {}).items():
        for dotted, value in _anchors(key, written):
            if not _still_routes(_get(data, dotted), value):
                return True
    return False


def _read_parsed(path: Path, fmt: str) -> dict[str, Any] | None:
    try:
        raw = _read(path)
        return None if raw is None else _parse(raw, fmt, path)
    except AgentConfigError:
        return None


def _entry_changed(spec: AgentSpec, entry: Any) -> bool:
    if not isinstance(entry, dict) or entry.get("manual"):
        return False
    default_fmt = spec.files[0][1] if spec.files else "json"
    for fentry in _file_entries(entry):
        if not isinstance(fentry, dict) or "path" not in fentry:
            continue
        fmt = fentry.get("fmt") or default_fmt
        if _file_replaced(fentry, _read_parsed(Path(fentry["path"]), fmt)):
            return True
    return False


def _file_entry(path: Path, raw: bytes | None, fmt: str, desired: dict[str, Any], data: dict[str, Any]) -> dict:
    previous = {k: _get(data, k) for k in desired}
    return {
        "path": str(path),
        "fmt": fmt,
        "original": base64.b64encode(raw).decode() if raw is not None else None,
        "mode": (os.stat(_target(path)).st_mode & 0o777) if raw is not None else None,
        "previous": {k: v for k, v in previous.items() if v is not _MISSING},
        "absent": [k for k, v in previous.items() if v is _MISSING],
    }


def _reconnect_entry(old: dict, raw: bytes | None, values: dict[str, Any], data: dict[str, Any]) -> dict:
    """Carry a file's first-connect backup into a reconnect.

    The original bytes stay restorable only while the file is exactly what
    we last wrote; once the user has edited it, disconnect reverts our
    settings one by one instead, so their edits survive. Settings this
    connect adds for the first time record their current values.

    A file whose Orca settings were replaced wholesale (D5: an update or the
    agent's own setup rewrote it) keeps the very first original as its
    backup only if it is that original again (or gone). Otherwise the update
    brought settings of its own, so disconnect takes out Orca's values one by
    one rather than roll the file back to before the update.
    """
    entry = dict(old)
    current_sha = _sha(raw) if raw is not None else None
    replaced = _file_replaced(old, data if raw is not None else None)
    original = old.get("original")
    original_sha = _sha(base64.b64decode(original)) if original else None
    back_to_original = raw is None or current_sha == original_sha
    if current_sha != old.get("written_sha256") and not (replaced and back_to_original):
        entry["restorable"] = False
    previous = dict(old.get("previous") or {})
    absent = list(old.get("absent") or [])
    known = set(old.get("values") or {})
    for key in values:
        if key in known or key in previous or key in absent:
            continue
        value = _get(data, key)
        if value is _MISSING:
            absent.append(key)
        else:
            previous[key] = value
    entry["previous"], entry["absent"] = previous, absent
    return entry


def _file_entries(entry: dict) -> list[dict]:
    # Entries written before multi-file support held one file at the top level.
    return entry["files"] if "files" in entry else [entry]


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

        home = Path(home)
        key_file = (Path(state_dir) / "keys" / f"{agent_id}.key").resolve() if agent_id in KEY_FILE_AGENTS else None

        # Read and check every file before writing any, so a problem in one
        # leaves all of them untouched.
        loaded: dict[str, tuple[Path, str, bytes | None, dict[str, Any]]] = {}
        for rel, fmt in spec.files:
            path = home / rel
            raw = _read(path)
            loaded[rel] = (path, fmt, raw, _parse(raw or b"", fmt, path))
        desired = _desired_values(
            agent_id, base_url, api_key, key_file=key_file,
            current={rel: data for rel, (_p, _f, _r, data) in loaded.items()},
        )
        old = state.get(agent_id)
        old_files = {f.get("path"): f for f in _file_entries(old)} if isinstance(old, dict) and not old.get("manual") else {}
        plan: list[tuple[Path, bytes | None, bytes, dict]] = []
        for rel, (path, fmt, raw, data) in loaded.items():
            values = desired[rel]
            for key in values:
                _check_containers(data, key, path)
            old_file = old_files.get(str(path))
            if old_file is None:
                fentry = _file_entry(path, raw, fmt, values, data)
            else:
                fentry = _reconnect_entry(old_file, raw, values, data)
            all_values = {**(fentry.get("values") or {}), **values}
            plan.append((path, raw, _apply(raw, fmt, values, path), {**fentry, "fmt": fmt, "values": all_values}))

        old_key: bytes | None = None
        done: list[tuple[Path, bytes | None]] = []
        previous_entry = state.get(agent_id)
        # Record the backup (each file's original bytes and the hash of what
        # we're about to write) before touching any agent file. If the process
        # dies part way, disconnect can still restore every file: one we wrote
        # matches its hash and gets its original bytes back; one we didn't
        # write doesn't hold our settings and is left as it is.
        state[agent_id] = {
            "files": [{**fentry, "written_sha256": _sha(written)} for _p, _r, written, fentry in plan],
            "key_file": str(key_file) if key_file else None,
        }
        writing: Path = Path(state_dir) / STATE_FILE
        try:
            _save_state(state_dir, state)
            if key_file is not None:
                writing = key_file
                key_file.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(key_file.parent, 0o700)
                old_key = _read(key_file)
                _write_atomic(key_file, api_key.encode(), 0o600)
                done.append((key_file, old_key))
            for path, raw, written, _fentry in plan:
                writing = path
                _write_atomic(path, written)
                done.append((path, raw))
        except OSError as exc:
            for path, raw in reversed(done):  # put back what we already changed
                with contextlib.suppress(OSError):
                    if raw is None:
                        _target(path).unlink()
                    else:
                        _write_atomic(path, raw)
            if previous_entry is None:
                state.pop(agent_id, None)
            else:
                state[agent_id] = previous_entry
            with contextlib.suppress(OSError):
                _save_state(state_dir, state)
            raise AgentConfigError(f"Can't write {writing}: {exc.strerror or exc}") from exc

        primary = plan[0][0]
        return ConnectResult(agent_id, False, str(primary), base_url, api_key)


def _restore_file(fentry: dict, fmt: str) -> None:
    path = Path(fentry["path"])
    current = _read(path)
    try:
        if current is not None and fentry.get("restorable", True) and _sha(current) == fentry.get("written_sha256"):
            original = fentry.get("original")
            if original is None:
                _target(path).unlink()
            else:
                _write_atomic(path, base64.b64decode(original), fentry.get("mode"))
        elif current is not None:
            data = _parse(current, fmt, path)
            changes: dict[str, Any] = {}
            for key, ours in (fentry.get("values") or {}).items():
                if _get(data, key) != ours:
                    continue  # the user changed it after we connected; leave it
                if key in (fentry.get("absent") or []):
                    changes[key] = _MISSING
                elif key in (fentry.get("previous") or {}):
                    changes[key] = fentry["previous"][key]
            if changes:
                _write_atomic(path, _apply(current, fmt, changes, path))
    except OSError as exc:
        raise AgentConfigError(f"Can't restore {path}: {exc.strerror or exc}") from exc


def disconnect_agent(agent_id: str, *, home: Path, state_dir: Path) -> None:
    spec = _spec(agent_id)
    with _locked(state_dir):
        state = _load_state(state_dir)
        entry = state.get(agent_id)
        if entry is None:
            return
        if not isinstance(entry, dict) or not (entry.get("manual") or "path" in entry or "files" in entry):
            raise AgentConfigError(f"The saved connection for {spec.name} is damaged; reconnect it to repair.")

        if not entry.get("manual"):
            default_fmt = spec.files[0][1] if spec.files else "json"
            files = _file_entries(entry)
            if not all(isinstance(f, dict) and "path" in f for f in files):
                raise AgentConfigError(f"The saved connection for {spec.name} is damaged; reconnect it to repair.")
            # Restore every file even if one fails, so an agent is never left
            # half pointed at Orca; keep only the failures for another try.
            failed: list[dict] = []
            errors: list[str] = []
            for fentry in files:
                try:
                    _restore_file(fentry, fentry.get("fmt") or default_fmt)
                except AgentConfigError as exc:
                    failed.append(fentry)
                    errors.append(str(exc))
            if failed:
                state[agent_id] = {**entry, "files": failed}
                state[agent_id].pop("path", None)
                _save_state(state_dir, state)
                raise AgentConfigError("; ".join(errors))
            if entry.get("key_file"):
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(entry["key_file"])

        del state[agent_id]
        _save_state(state_dir, state)
