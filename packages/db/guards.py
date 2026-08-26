"""Startup safety guards that need DB access.

`assert_credential_encryption_ready` fail-closes boot when provider
credentials would be (or are) protected by the publicly-known dev
encryption key. Kept separate from `packages.auth.encryption` so the
crypto module stays free of SQLAlchemy imports.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.auth.encryption import is_using_insecure_dev_key

_ALLOW_FLAG_ENV = "ORCA_ALLOW_INSECURE_DEV_KEY"


def _allow_flag_enabled(settings_value: bool, os_environ) -> bool:
    if settings_value:
        return True
    return str(os_environ.get(_ALLOW_FLAG_ENV, "")).lower() in ("1", "true", "yes")


async def _count_provider_keys(session: AsyncSession) -> int:
    from packages.db.models.provider_key import ProviderKey

    return int(
        (await session.execute(select(func.count()).select_from(ProviderKey))).scalar_one()
    )


async def assert_credential_encryption_ready(
    *,
    make_session,
    database_url: str,
    allow_insecure_dev_key: bool = False,
    os_environ=None,
) -> None:
    """Refuse to start when the dev encryption key would guard real secrets.

    - SQLite + zero stored provider keys  -> allowed (fresh dev install),
      `encryption.py` warns loudly at first use.
    - Anything else without a configured key -> RuntimeError with remediation.
    """
    import os as _os

    environ = os_environ if os_environ is not None else _os.environ
    if not is_using_insecure_dev_key():
        return
    if _allow_flag_enabled(allow_insecure_dev_key, environ):
        return

    is_sqlite = database_url.startswith("sqlite")
    try:
        async with make_session() as session:
            key_rows = await _count_provider_keys(session)
    except Exception as exc:
        # Only a genuinely missing table counts as zero rows (fresh DB
        # pre-migration). Any other failure — connection loss, "database
        # is locked", I/O error — must fail closed, not silently boot
        # with the dev key and expose stored credentials.
        #
        # `create_all` ran moments earlier on the same engine on the
        # main.py path, so a missing table is already unexpected there;
        # we still handle it for out-of-band callers that invoke the
        # guard without prior migration.
        msg = str(exc).lower()
        if "no such table" in msg or "no such relation" in msg or "does not exist" in msg:
            key_rows = 0
        else:
            raise

    if is_sqlite and key_rows == 0:
        return

    raise RuntimeError(
        "CREDENTIAL_ENCRYPTION_KEY is not set, so provider API keys would be "
        "sealed with a publicly-known development key. "
        + (
            f"{key_rows} provider key(s) already exist in this database."
            if key_rows
            else "A non-SQLite database requires an explicit encryption key."
        )
        + " Generate one with `openssl rand -hex 32`, set it as "
        "CREDENTIAL_ENCRYPTION_KEY, and re-save your provider keys. "
        "(If you knowingly want to keep using the insecure dev key, set "
        "ORCA_ALLOW_INSECURE_DEV_KEY=1.)"
    )
