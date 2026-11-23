"""The desktop engine's home folder (default ~/.orcarouter-lite).

Holds everything a desktop install needs so the user never touches a `.env`:

  secrets.json   encryption key + key pepper, generated once (0600)
  orca.db        the SQLite database
  app.key        the key the desktop app and `orca` CLI use (0600)
  engine.json    where the running engine listens (0600)
  agents/        agent config backups (see packages.desktop.agents)
"""

from __future__ import annotations

import json
import os
import secrets as _secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

APP_KEY_NAME = "desktop-app"
DEFAULT_PORT = 8765


class EngineNotRunning(Exception):
    pass


def default_home() -> Path:
    env = os.environ.get("ORCA_HOME")
    return Path(env).expanduser() if env else Path.home() / ".orcarouter-lite"


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def prepare_home(home: Path) -> dict[str, str]:
    """Create the folder (0700) and its secrets on first run; return the secrets."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    path = home / "secrets.json"
    if path.exists():
        return json.loads(path.read_text())
    data = {
        "credential_encryption_key": _secrets.token_hex(32),
        "api_key_pepper": _secrets.token_urlsafe(32),
    }
    _write_private(path, json.dumps(data, indent=2))
    return data


def desktop_env(home: Path, *, port: int = DEFAULT_PORT) -> dict[str, str]:
    home = Path(home)
    s = prepare_home(home)
    return {
        "ORCA_DESKTOP_MODE": "1",
        "ORCA_HOME": str(home),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "DATABASE_URL": f"sqlite+aiosqlite:///{home / 'orca.db'}",
        "CREDENTIAL_ENCRYPTION_KEY": s["credential_encryption_key"],
        "API_KEY_PEPPER": s["api_key_pepper"],
    }


def write_engine_info(home: Path, *, base_url: str, pid: int) -> None:
    _write_private(Path(home) / "engine.json", json.dumps({"base_url": base_url, "pid": pid}))


def read_engine_info(home: Path) -> dict:
    path = Path(home) / "engine.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise EngineNotRunning(str(path)) from exc


def read_app_key(home: Path) -> str:
    try:
        key = (Path(home) / "app.key").read_text().strip()
    except OSError as exc:
        raise EngineNotRunning("no app key") from exc
    if not key:
        raise EngineNotRunning("empty app key")
    return key


async def ensure_app_key(session: AsyncSession, home: Path, workspace_id: str = "default") -> str:
    """Return a working desktop-app key, minting and saving one if needed."""
    from packages.auth.hashing import generate_api_key
    from packages.auth.key_validator import AuthError, validate_api_key
    from packages.db.models.api_key import ApiKey

    home = Path(home)
    try:
        existing = read_app_key(home)
        kc = await validate_api_key(existing, session)
        if kc.name == APP_KEY_NAME:
            return existing
    except (EngineNotRunning, AuthError):
        pass

    await session.execute(
        update(ApiKey)
        .where(ApiKey.name == APP_KEY_NAME, ApiKey.revoked_at.is_(None))
        .values(is_active=False, revoked_at=datetime.now(timezone.utc))
    )
    full, key_hash, prefix = generate_api_key()
    session.add(ApiKey(workspace_id=workspace_id, name=APP_KEY_NAME, key_hash=key_hash, key_prefix=prefix))
    await session.commit()
    # make sure the row is visible before the file points at it
    await session.execute(select(ApiKey.id).where(ApiKey.key_hash == key_hash))
    _write_private(home / "app.key", full + "\n")
    return full
