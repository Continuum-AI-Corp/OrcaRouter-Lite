"""Authorization guards for privileged key-management operations.

A *restricted* key is one that carries any limitation — a ``model_allowlist``
or a ``budget_limit_cents`` cap. Restricted keys are issued as child keys with
reduced privilege; letting them mint/rotate provider credentials, rewrite
routing, or override quality scores would let them escalate to the full
privilege of an unrestricted key. Only unrestricted keys may perform those
operations, so the escalation path is closed everywhere, not just on
``/v1/keys``.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

from app.deps import get_key_context
from packages.auth.types import KeyContext


def is_restricted(kc: KeyContext) -> bool:
    """True if the key carries any usage restriction."""
    return kc.model_allowlist is not None or kc.budget_limit_cents is not None


def require_unrestricted(kc: KeyContext = Depends(get_key_context)) -> None:
    """FastAPI dependency: reject restricted keys from management endpoints.

    Usable both as ``Depends(require_unrestricted)`` on a route and as a direct
    ``require_unrestricted(kc)`` call. Synchronous on purpose — it performs no
    I/O, only a privilege check and a raise — so it works identically whether
    FastAPI awaits it as a dependency or a route calls it inline.
    """
    if is_restricted(kc):
        raise HTTPException(
            status_code=403,
            detail=(
                "Restricted API keys cannot perform management operations. "
                "Use an unrestricted key."
            ),
        )
