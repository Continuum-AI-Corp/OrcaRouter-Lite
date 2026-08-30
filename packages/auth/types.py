"""Auth types — KeyContext shape returned by the validator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KeyContext:
    """The validated identity attached to scope.state.key_context."""

    key_id: str
    workspace_id: str
    name: str
    key_type: str = "standard"
    role_label: str | None = None
    budget_limit_cents: int | None = None
    model_allowlist: list[str] | None = None
