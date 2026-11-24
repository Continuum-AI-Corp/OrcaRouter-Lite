"""D4: test a connected agent the way it will run.

Reads the agent's config the way the agent itself does (the readers the
end-to-end suite started with), then sends one tiny request (max_tokens 1)
in the agent's own protocol (Anthropic Messages, Responses, Gemini or Chat
Completions) to the URL and key from that config. The engine sends it to its
own port, so the request is attributed to the agent like any other.

Keys that agents read from Orca's key folder (OpenCode, Kilo, Command Code,
Goose) are read from that folder, and only from it: a config that names
another file or another command is reported, never followed, so a test can't
be made to read or run anything else.

Errors come back in plain words ("OpenAI rejected the key (401). Replace it
in Providers, then test again."). Kept free of FastAPI and the database.
"""

from __future__ import annotations

import json
import shlex
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from packages.desktop import agents as ag

TIMEOUT_SECONDS = 20.0
PROMPT = "Reply with one word."


class ConfigError(Exception):
    """The agent's config doesn't hold settings Orca can test (in plain words)."""


@dataclass(frozen=True)
class Endpoint:
    protocol: str  # "anthropic" | "responses" | "gemini" | "chat"
    base_url: str
    key: str
    model: str
    config_path: Path


@dataclass(frozen=True)
class TestResult:
    ok: bool
    status: int | None = None   # HTTP status; None when nothing answered
    model: str | None = None
    seconds: float | None = None
    detail: str | None = None   # the engine's error message
    timed_out: bool = False


@dataclass(frozen=True)
class FailedRow:
    """What the engine logged for the failed test request."""

    provider: str | None
    error_type: str | None
    status: int | None


# ── reading configs ─────────────────────────────────────────────────────


def display_path(path: Path, home: Path) -> str:
    try:
        return "~/" + Path(path).relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _load(path: Path, fmt: str, home: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"{display_path(path, home)} is missing.") from None
    except OSError as exc:
        raise ConfigError(f"Can't read {display_path(path, home)}: {exc.strerror or exc}") from exc
    try:
        if fmt == "json":
            data = json.loads(text or "{}")
        elif fmt == "toml":
            data = tomllib.loads(text)
        elif fmt == "yaml":
            data = yaml.safe_load(text) or {}
        else:  # dotenv
            data = {}
            for line in text.splitlines():
                k, sep, v = line.partition("=")
                if sep and not k.strip().startswith("#"):
                    data[k.strip()] = v.strip().strip('"').strip("'")
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigError(f"{display_path(path, home)} isn't valid {fmt.upper()}.") from exc
    return data if isinstance(data, dict) else {}


def _need(data: Any, *keys: str, path: Path, home: Path) -> Any:
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            raise ConfigError(f"Orca's settings are missing from {display_path(path, home)}.")
        cur = cur[k]
    return cur


def _key_dir(state_dir: Path) -> Path:
    return (Path(state_dir) / "keys").resolve()


def _read_key_file(path_text: str, state_dir: Path, cfg: Path, home: Path) -> str:
    """The key from a file the config names, only if it's in Orca's key folder."""
    path = Path(path_text).expanduser().resolve()
    if path.parent != _key_dir(state_dir):
        raise ConfigError(f"The key setting in {display_path(cfg, home)} isn't Orca's any more.")
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise ConfigError("Orca's key file for this agent is missing. Connect the agent again.") from exc


def _file_ref(ref: Any, state_dir: Path, cfg: Path, home: Path) -> str:
    if not (isinstance(ref, str) and ref.startswith("{file:") and ref.endswith("}")):
        raise ConfigError(f"The key setting in {display_path(cfg, home)} isn't Orca's any more.")
    return _read_key_file(ref[len("{file:"):-1], state_dir, cfg, home)


def _command_ref(cmd: Any, state_dir: Path, cfg: Path, home: Path) -> str:
    """Command Code runs `!cat <file>` (or `!type "<file>"` on Windows)."""
    if not (isinstance(cmd, str) and cmd.startswith("!")):
        raise ConfigError(f"The key setting in {display_path(cfg, home)} isn't Orca's any more.")
    try:
        parts = shlex.split(cmd[1:], posix=not cmd[1:].lower().startswith("type "))
    except ValueError:
        parts = []
    if len(parts) != 2 or parts[0].lower() not in ("cat", "type"):
        raise ConfigError(f"The key setting in {display_path(cfg, home)} isn't Orca's any more.")
    return _read_key_file(parts[1].strip('"'), state_dir, cfg, home)


def _goose_ref(auth: Any, state_dir: Path, cfg: Path, home: Path) -> str:
    """Goose runs auth.command with auth.args (no shell) and reads its output."""
    args = auth.get("args") if isinstance(auth, dict) else None
    if not (isinstance(args, list) and args and auth.get("command") in ("cat", "cmd")):
        raise ConfigError(f"The key setting in {display_path(cfg, home)} isn't Orca's any more.")
    return _read_key_file(str(args[-1]), state_dir, cfg, home)


def _model(value: Any) -> str:
    return value if isinstance(value, str) and value else "auto"


def read_endpoint(agent_id: str, *, home: Path, state_dir: Path) -> Endpoint:
    """Where the agent sends its requests, with which key and model."""
    home = Path(home)
    H, G = ag._HERMES_DIR, ag._GOOSE_DIR

    def load(rel: str, fmt: str) -> tuple[Path, dict]:
        path = home / rel
        return path, _load(path, fmt, home)

    if agent_id == "claude-code":
        p, cfg = load(".claude/settings.json", "json")
        env = _need(cfg, "env", path=p, home=home)
        return Endpoint("anthropic", _need(env, "ANTHROPIC_BASE_URL", path=p, home=home),
                        _need(env, "ANTHROPIC_AUTH_TOKEN", path=p, home=home), _model(env.get("ANTHROPIC_MODEL")), p)
    if agent_id == "codex":
        p, cfg = load(".codex/config.toml", "toml")
        prov = _need(cfg, "model_providers", _need(cfg, "model_provider", path=p, home=home), path=p, home=home)
        return Endpoint("responses", _need(prov, "base_url", path=p, home=home),
                        _need(prov, "experimental_bearer_token", path=p, home=home), _model(cfg.get("model")), p)
    if agent_id == "gemini-cli":
        p, env = load(".gemini/.env", "dotenv")
        return Endpoint("gemini", _need(env, "GOOGLE_GEMINI_BASE_URL", path=p, home=home),
                        _need(env, "GEMINI_API_KEY", path=p, home=home), "auto", p)
    if agent_id in ("opencode", "kilo"):
        rel = ".config/opencode/opencode.json" if agent_id == "opencode" else ".config/kilo/kilo.json"
        p, cfg = load(rel, "json")
        provider_id, _, model = str(_need(cfg, "model", path=p, home=home)).partition("/")
        opts = _need(cfg, "provider", provider_id, "options", path=p, home=home)
        key = _file_ref(_need(opts, "apiKey", path=p, home=home), state_dir, p, home)
        return Endpoint("chat", _need(opts, "baseURL", path=p, home=home), key, _model(model), p)
    if agent_id == "command-code":
        p, cfg = load(".commandcode/providers.json", "json")
        section = cfg.get("provider") if isinstance(cfg.get("provider"), dict) else cfg.get("providers")
        prov = _need({"s": section}, "s", ag.PROVIDER_ID, path=p, home=home)
        key = _command_ref(prov.get("apiKey"), state_dir, p, home)
        models = prov.get("models") if isinstance(prov.get("models"), dict) else {}
        return Endpoint("chat", _need(prov, "baseURL", path=p, home=home), key, _model(next(iter(models), None)), p)
    if agent_id == "aider":
        p, cfg = load(".aider.conf.yml", "yaml")
        model = str(cfg.get("model") or "auto").removeprefix("openai/")
        return Endpoint("chat", _need(cfg, "openai-api-base", path=p, home=home),
                        _need(cfg, "openai-api-key", path=p, home=home), _model(model), p)
    if agent_id == "hermes":
        p, cfg = load(f"{H}/config.yaml", "yaml")
        kind, _, name = str(_need(cfg, "model", "provider", path=p, home=home)).partition(":")
        if kind != "custom":
            raise ConfigError(f"Hermes isn't set to Orca's provider in {display_path(p, home)}.")
        prov = _need(cfg, "providers", name, path=p, home=home)
        return Endpoint("chat", _need(prov, "api", path=p, home=home), _need(prov, "api_key", path=p, home=home),
                        _model((cfg.get("model") or {}).get("default")), p)
    if agent_id == "pi":
        sp, settings = load(".pi/agent/settings.json", "json")
        p, models = load(".pi/agent/models.json", "json")
        prov = _need(models, "providers", _need(settings, "defaultProvider", path=sp, home=home), path=p, home=home)
        return Endpoint("chat", _need(prov, "baseUrl", path=p, home=home), _need(prov, "apiKey", path=p, home=home),
                        _model(settings.get("defaultModel")), p)
    if agent_id == "omp":
        cp, cfg = load(".omp/agent/config.yml", "yaml")
        provider_id, _, model = str(_need(cfg, "modelRoles", "default", path=cp, home=home)).partition("/")
        p, models = load(".omp/agent/models.yml", "yaml")
        prov = _need(models, "providers", provider_id, path=p, home=home)
        return Endpoint("chat", _need(prov, "baseUrl", path=p, home=home), _need(prov, "apiKey", path=p, home=home),
                        _model(model), p)
    if agent_id == "openclaw":
        p, cfg = load(".openclaw/openclaw.json", "json")
        primary = _need(cfg, "agents", "defaults", "model", path=p, home=home)
        primary = primary.get("primary") if isinstance(primary, dict) else primary
        provider_id, _, model = str(primary or "").partition("/")
        prov = _need(cfg, "models", "providers", provider_id, path=p, home=home)
        return Endpoint("chat", _need(prov, "baseUrl", path=p, home=home), _need(prov, "apiKey", path=p, home=home),
                        _model(model), p)
    if agent_id == "kimi-code":
        p, cfg = load(".kimi-code/config.toml", "toml")
        m = _need(cfg, "models", _need(cfg, "default_model", path=p, home=home), path=p, home=home)
        prov = _need(cfg, "providers", _need(m, "provider", path=p, home=home), path=p, home=home)
        if prov.get("type") != "openai":
            raise ConfigError(f"Kimi Code isn't set to Orca's provider in {display_path(p, home)}.")
        return Endpoint("chat", _need(prov, "base_url", path=p, home=home), _need(prov, "api_key", path=p, home=home),
                        _model(m.get("model")), p)
    if agent_id == "goose":
        cp, cfg = load(f"{G}/config.yaml", "yaml")
        provider_id = _need(cfg, "GOOSE_PROVIDER", path=cp, home=home)
        p, prov = load(f"{G}/custom_providers/{provider_id}.json", "json")
        key = _goose_ref(prov.get("auth"), state_dir, p, home)
        return Endpoint("chat", _need(prov, "base_url", path=p, home=home), key, _model(cfg.get("GOOSE_MODEL")), p)
    raise ConfigError("Orca can't test this agent.")


# ── the request ─────────────────────────────────────────────────────────


def _request(ep: Endpoint) -> tuple[str, dict, dict]:
    base = ep.base_url.rstrip("/")
    bearer = {"Authorization": f"Bearer {ep.key}"}
    message = [{"role": "user", "content": PROMPT}]
    if ep.protocol == "anthropic":
        return (f"{base}/v1/messages", {**bearer, "anthropic-version": "2023-06-01"},
                {"model": ep.model, "max_tokens": 1, "messages": message})
    if ep.protocol == "responses":
        return f"{base}/responses", bearer, {"model": ep.model, "input": PROMPT, "max_output_tokens": 1,
                                             "store": False}
    if ep.protocol == "gemini":
        return (f"{base}/v1beta/models/{ep.model}:generateContent", {"x-goog-api-key": ep.key},
                {"contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
                 "generationConfig": {"maxOutputTokens": 1}})
    return f"{base}/chat/completions", bearer, {"model": ep.model, "messages": message, "max_tokens": 1}


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        if "detail" in body:
            return str(body["detail"])
    return str(body)[:300]


async def send(ep: Endpoint, *, transport: httpx.AsyncBaseTransport | None = None,
               timeout: float = TIMEOUT_SECONDS) -> TestResult:
    url, headers, body = _request(ep)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return TestResult(ok=False, timed_out=True)
    except httpx.HTTPError:
        return TestResult(ok=False)
    seconds = round(time.monotonic() - started, 2)
    if resp.status_code >= 400:
        return TestResult(ok=False, status=resp.status_code, seconds=seconds, detail=_error_detail(resp))
    model = resp.headers.get("x-orca-resolved-model")
    if not model:
        try:
            data = resp.json()
            model = data.get("model") or data.get("modelVersion") if isinstance(data, dict) else None
        except ValueError:
            model = None
    return TestResult(ok=True, status=resp.status_code, model=model or None, seconds=seconds)


# ── plain words ─────────────────────────────────────────────────────────

_BUSY = {"rate_limit_error"}
_DOWN = {"overloaded_error", "upstream_error", "upstream_timeout"}


def explain(result: TestResult, *, agent_name: str, base_url: str, failed: FailedRow | None = None) -> str | None:
    """What went wrong, for the user. None when the test passed."""
    from packages.litellm_adapter.provider_registry import display_name

    if result.ok:
        return None
    if result.timed_out:
        return f"Orca didn't answer within {int(TIMEOUT_SECONDS)} seconds at {base_url}."
    if result.status is None:
        return f"Orca isn't reachable at {base_url}."
    if failed and failed.provider and failed.error_type:
        who = display_name(failed.provider)
        status = failed.status or result.status
        if failed.error_type == "upstream_auth_error":
            return f"{who} rejected the key (401). Replace it in Providers, then test again."
        if failed.error_type in _BUSY:
            return f"{who} is limiting requests right now (429). Try again in a minute, or add another provider."
        if failed.error_type in _DOWN:
            return f"{who} isn't answering right now ({status}). Try again in a minute, or add another provider."
    if result.status == 401:
        return f"Orca didn't accept {agent_name}'s key. Connect {agent_name} again, then test."
    detail = (result.detail or "").strip()
    return detail or f"The test request failed ({result.status})."


# ── last result per agent (for diagnostics) ─────────────────────────────

LAST: dict[str, dict] = {}


def remember(agent_id: str, ok: bool | None, error: str | None) -> None:
    LAST[agent_id] = {"at": datetime.now(timezone.utc), "ok": ok, "error": error}
