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
import time
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
    """Create the folder (0700) and its secrets on first run; return the secrets.

    Creation is exclusive (O_EXCL), so two first runs racing each other end up
    with the same secrets instead of one overwriting the other's.
    """
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    path = home / "secrets.json"
    data = {
        "credential_encryption_key": _secrets.token_hex(32),
        "api_key_pepper": _secrets.token_urlsafe(32),
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(50):  # the winner may still be writing
            try:
                existing = json.loads(path.read_text())
                if existing.get("credential_encryption_key") and existing.get("api_key_pepper"):
                    return existing
            except (OSError, ValueError):
                pass
            time.sleep(0.02)
        raise
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2))
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


def write_engine_info(home: Path, *, base_url: str, pid: int, secret: str) -> None:
    """Where the engine listens, plus the per-launch secret that proves it's ours."""
    _write_private(Path(home) / "engine.json", json.dumps({"base_url": base_url, "pid": pid, "secret": secret}))


def remove_engine_info(home: Path, *, pid: int) -> None:
    """Remove engine.json if it still describes this process."""
    path = Path(home) / "engine.json"
    try:
        if json.loads(path.read_text()).get("pid") == pid:
            path.unlink()
    except (OSError, ValueError):
        pass


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
