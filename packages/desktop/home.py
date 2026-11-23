"""The desktop engine's home folder (default ~/.orcarouter-lite).

Holds everything a desktop install needs so the user never touches a `.env`:

  (keychain)     encryption key + key pepper, generated once, kept in the OS
                 keychain (macOS Keychain, Windows Credential Manager, Linux
                 Secret Service)
  secrets.json   the same secrets where no keychain works (0600)
  orca.db        the SQLite database
  app.key        the key the desktop app and `orca` CLI use (0600)
  engine.json    where the running engine listens (0600)
  agents/        agent config backups (see packages.desktop.agents)
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets as _secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

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


KEYCHAIN_SERVICE = "OrcaRouter Lite"
_DEFAULT = object()
_HOME_LOCK = threading.Lock()


def keychain_name(home: Path) -> str:
    return f"secrets:{Path(home).expanduser().resolve()}"


class _SystemKeychain:
    def __init__(self, backend):
        self._backend = backend

    def get(self, name: str) -> str | None:
        return self._backend.get_password(KEYCHAIN_SERVICE, name)

    def set(self, name: str, value: str) -> None:
        self._backend.set_password(KEYCHAIN_SERVICE, name, value)


def system_keychain():
    """The OS keychain, or None where there isn't a usable one.

    ORCA_KEYCHAIN=0 switches it off. On Linux it needs a desktop session bus
    (Secret Service); headless machines keep the private file.
    """
    if os.environ.get("ORCA_KEYCHAIN", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    if sys.platform.startswith("linux") and not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:  # pragma: no cover - keyring is a dependency
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 1) <= 0:
        return None
    return _SystemKeychain(backend)


def _complete(data) -> bool:
    return isinstance(data, dict) and bool(data.get("credential_encryption_key")) and bool(data.get("api_key_pepper"))


@contextlib.contextmanager
def _home_lock(home: Path):
    """Serialise first runs across threads and processes."""
    with _HOME_LOCK:
        fd = os.open(home / ".secrets.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":  # pragma: no cover - Windows
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def _read_secrets_file(path: Path) -> dict[str, str] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if _complete(data) else None


def _keychain_get(keychain, name: str) -> tuple[bool, dict[str, str] | None]:
    """(keychain works, secrets stored there)."""
    try:
        raw = keychain.get(name)
    except Exception as exc:
        log.warning("keychain_unavailable", error=str(exc))
        return False, None
    if raw is None:
        return True, None
    try:
        data = json.loads(raw)
    except ValueError:
        return True, None
    return True, data if _complete(data) else None


def _keychain_put(keychain, name: str, data: dict[str, str]) -> bool:
    """Store and read back; True only if the keychain returns the same values."""
    try:
        keychain.set(name, json.dumps(data))
    except Exception as exc:
        log.warning("keychain_write_failed", error=str(exc))
        return False
    return _keychain_get(keychain, name) == (True, data)


def prepare_home(home: Path, *, keychain=_DEFAULT) -> dict[str, str]:
    """Create the folder (0700) and its secrets on first run; return the secrets.

    The secrets go to the OS keychain when one works; a secrets.json written by
    an earlier version moves there and is deleted once the keychain returns
    the same values. Otherwise they stay in secrets.json (0600). First runs are
    serialised by a lock, so racing launches share one set of secrets.
    """
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    if keychain is _DEFAULT:
        keychain = system_keychain()
    path = home / "secrets.json"
    name = keychain_name(home)
    with _home_lock(home):
        on_disk = _read_secrets_file(path)
        works, stored = _keychain_get(keychain, name) if keychain is not None else (False, None)
        if on_disk is not None:
            if stored is not None and stored != on_disk:
                # A restored backup or a manual edit: the file is what the
                # database was last used with, so keep it and leave both.
                log.warning("keychain_secrets_differ_from_file", file=str(path))
                return on_disk
            if works and (stored == on_disk or _keychain_put(keychain, name, on_disk)):
                path.unlink()
            return on_disk
        if stored is not None:
            return stored
        data = {
            "credential_encryption_key": _secrets.token_hex(32),
            "api_key_pepper": _secrets.token_urlsafe(32),
        }
        if works and _keychain_put(keychain, name, data):
            return data
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
