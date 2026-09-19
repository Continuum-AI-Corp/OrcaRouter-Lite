"""Startup safety guards that need DB access.

`assert_credential_encryption_ready` fail-closes boot when provider
credentials would be (or are) protected by the publicly-known dev
encryption key. Kept separate from `packages.auth.encryption` so the
crypto module stays free of SQLAlchemy imports.

`audit_stored_provider_credentials` is the companion check for key
rotation: it re-encrypts rows that still open with
`CREDENTIAL_ENCRYPTION_PREVIOUS_KEY`, and logs remaining failures
instead of letting `build_deployments` drop them silently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.auth.encryption import is_using_insecure_dev_key

logger = logging.getLogger("orca.credentials")

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
    engine=None,
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

    # Prefer an explicit engine for table-existence checks; fall back to
    # extracting it from the session factory so we don't rely on fragile
    # string-matching of exception messages.
    if engine is None:
        try:
            engine = getattr(make_session, "kw", {}).get("bind")  # async_sessionmaker
        except Exception:
            engine = None
        if engine is None:
            engine = getattr(make_session, "bind", None)

    if engine is not None:
        # Use async-safe inspector: for AsyncEngine we must run through
        # run_sync inside an async connection, otherwise MissingGreenlet.
        has_table = False
        try:
            if hasattr(engine, "connect") and hasattr(engine, "sync_engine"):
                # AsyncEngine path — use run_sync
                async with engine.connect() as conn:
                    def _check(sync_conn):
                        from sqlalchemy import inspect as _inspect

                        return _inspect(sync_conn).has_table("provider_keys")

                    has_table = await conn.run_sync(_check)
            else:
                from sqlalchemy import inspect

                sync_engine = engine.sync_engine if hasattr(engine, "sync_engine") else engine
                has_table = inspect(sync_engine).has_table("provider_keys")
        except RuntimeError:
            raise
        except Exception:
            # Inspector itself failed — fail closed, don't silently allow boot.
            raise
        if not has_table:
            key_rows = 0
            if is_sqlite and key_rows == 0:
                return
            raise RuntimeError(
                "CREDENTIAL_ENCRYPTION_KEY is not set, so provider API keys would be "
                "sealed with a publicly-known development key. "
                + "A non-SQLite database requires an explicit encryption key. "
                + "Generate one with `openssl rand -hex 32`, set it as "
                "CREDENTIAL_ENCRYPTION_KEY, and re-save your provider keys. "
                "(If you knowingly want to keep using the insecure dev key, set "
                "ORCA_ALLOW_INSECURE_DEV_KEY=1.)"
            )
        # Table exists — count rows; any failure here is not "missing table"
        # and must fail closed.
        async with make_session() as session:
            key_rows = await _count_provider_keys(session)
    else:
        # No engine available (test helper without bind) — fall back to
        # counting and narrowly treat only a missing-table error as zero.
        try:
            async with make_session() as session:
                key_rows = await _count_provider_keys(session)
        except Exception as exc:
            msg = str(exc).lower()
            if "no such table" in msg or "no such relation" in msg:
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


@dataclass(frozen=True)
class CredentialAudit:
    """Outcome of the startup scan over `provider_keys`."""

    reencrypted: tuple[str, ...]
    undecryptable: tuple[str, ...]


async def audit_stored_provider_credentials(
    *,
    make_session,
    previous_key: str = "",
) -> CredentialAudit:
    """Re-encrypt rows sealed with `previous_key`; report the rest.

    Does not refuse boot: the dashboard must stay up so an operator can
    re-save keys. Failures are logged at ERROR with the provider names.
    """
    from packages.auth.encryption import (
        credential_is_decryptable,
        decrypt_credential,
        encrypt_credential,
        materialize_encryption_key,
    )
    from packages.db.models.provider_key import ProviderKey

    previous_bytes = (
        materialize_encryption_key(previous_key) if previous_key.strip() else None
    )

    async with make_session() as session:
        rows = (
            await session.execute(
                select(ProviderKey).where(ProviderKey.is_deleted == 0)
            )
        ).scalars().all()

        reencrypted: list[str] = []
        undecryptable: list[str] = []
        for row in rows:
            if credential_is_decryptable(row.encrypted_key):
                continue
            if previous_bytes is not None:
                try:
                    plaintext = decrypt_credential(
                        row.encrypted_key, key=previous_bytes
                    )
                except Exception:
                    plaintext = None
                if plaintext is not None:
                    row.encrypted_key = encrypt_credential(plaintext)
                    reencrypted.append(row.provider)
                    continue
            undecryptable.append(row.provider)
            logger.error(
                "undecryptable_provider_key: stored key for %s cannot be "
                "decrypted with the current CREDENTIAL_ENCRYPTION_KEY. "
                "Chat will skip this provider (503 if nothing else is "
                "configured). Re-save the key in the dashboard, or set "
                "CREDENTIAL_ENCRYPTION_PREVIOUS_KEY to the prior value "
                "and restart to re-encrypt.",
                row.provider,
            )

        if reencrypted:
            await session.commit()
            logger.warning(
                "reencrypted_provider_keys: re-sealed %s with the current "
                "CREDENTIAL_ENCRYPTION_KEY. Remove "
                "CREDENTIAL_ENCRYPTION_PREVIOUS_KEY from .env after "
                "confirming the dashboard shows those providers as enabled.",
                ", ".join(reencrypted),
            )

    return CredentialAudit(
        reencrypted=tuple(reencrypted),
        undecryptable=tuple(undecryptable),
    )
