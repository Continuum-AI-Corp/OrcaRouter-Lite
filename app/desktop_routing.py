"""Routing decisions the desktop app adds on top of plain `auto`.

Kept apart from the chat handler so each rule is a small function with its
own tests:

- H0 free first: in "free" hosted mode OrcaRouter's free models lead auto,
  and a request only a paid hosted model could serve is refused with a
  message saying how to allow paid models, instead of being sent to one.
- H4 out of credit: while OrcaRouter is out of credit, auto and agent
  fallback prefer own keys.
- Twins: OrcaRouter names some models with dots where the vendor uses
  hyphens (claude-sonnet-4.6 / claude-sonnet-4-6). They're the same model.

Servers (desktop mode off) get none of this: `RoutingContext.desktop` is
False and every rule is a no-op.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packages.desktop import hosted_state
from packages.desktop.prefs import DEFAULTS, DesktopPrefs
from packages.litellm_adapter.hosted_catalog import (
    FREE_HOSTED_CONTEXT_TOKENS,
    HOSTED_MODEL_ALIASES,
    HOSTED_MODELS,
    is_free_hosted,
)

HOSTED_PROVIDER = "orcarouter"

NEEDS_PAID_TYPE = "needs_paid_model"
OUT_OF_CREDIT_TYPE = "out_of_credit"

# Every name a hosted model is deployed under: its bare id, plus the wire id
# for the aliased (free) ones. Paid = all of them but the free ones.
_HOSTED_NAMES = frozenset({b for _p, b in HOSTED_MODELS} | set(HOSTED_MODEL_ALIASES))
PAID_HOSTED_NAMES = frozenset(n for n in _HOSTED_NAMES if not is_free_hosted(n))


@dataclass(frozen=True)
class RoutingContext:
    desktop: bool
    prefs: DesktopPrefs = DEFAULTS
    deployments: tuple = ()
    deployable: frozenset[str] = frozenset()
    # Names only OrcaRouter serves (no own key or local model has them).
    hosted_only: frozenset[str] = frozenset()
    hosted_configured: bool = False

    @property
    def free_mode(self) -> bool:
        return self.desktop and self.prefs.hosted_models == "free"


def build_context(*, desktop: bool, prefs: DesktopPrefs, deployments: Iterable) -> RoutingContext:
    deps = tuple(deployments or ())
    by_name: dict[str, set[str]] = {}
    for d in deps:
        by_name.setdefault(d.model_name, set()).add(d.provider)
    return RoutingContext(
        desktop=desktop,
        prefs=prefs,
        deployments=deps,
        deployable=frozenset(by_name),
        hosted_only=frozenset(n for n, provs in by_name.items() if provs == {HOSTED_PROVIDER}),
        hosted_configured=any(d.provider == HOSTED_PROVIDER for d in deps),
    )


def auto_deployable(ctx: RoutingContext) -> set[str]:
    """What auto (and agent fallback) may pick from.

    While OrcaRouter is out of credit, models only it serves are left out
    so own keys answer — unless nothing else is left, in which case it's
    tried anyway: it either answers (credit was added, and that clears the
    state) or says it's still out of credit.
    """
    deployable = set(ctx.deployable)
    if ctx.desktop and hosted_state.out_of_credit():
        own = deployable - ctx.hosted_only
        if own:
            return own
    return deployable


def context_limits(ctx: RoutingContext) -> dict[str, int]:
    """Usable context per model, for models whose limit routing must respect."""
    if not ctx.desktop:
        return {}
    return {name: FREE_HOSTED_CONTEXT_TOKENS for name in ctx.deployable if is_free_hosted(name)}


def twin(model: str, deployable: Iterable[str]) -> str | None:
    """The deployable spelling of `model` when it's deployed only under the
    other spelling (dots vs hyphens in the version: claude-sonnet-4-6 and
    claude-sonnet-4.6). None when there's no single such twin."""
    key = model.replace(".", "-")
    hits = [d for d in deployable if d != model and d.replace(".", "-") == key]
    return hits[0] if len(hits) == 1 else None


def is_paid_hosted(model: str) -> bool:
    return model in PAID_HOSTED_NAMES or (twin(model, PAID_HOSTED_NAMES) is not None)


MAPPED_UNAVAILABLE_TYPE = "mapped_model_unavailable"

# Model-name marks of an agent's background requests (Claude Code's titles
# and summaries go to haiku; others use their vendor's mini/nano/lite).
_BACKGROUND_MARKS = ("haiku", "-mini", "-nano", "flash-lite", "-lite")


def is_background_model(model: str) -> bool:
    name = model.rsplit("/", 1)[-1].lower()
    return any(mark in name for mark in _BACKGROUND_MARKS)


def mapped_model(ctx: RoutingContext, agent_id: str | None, requested: str) -> str | None:
    """D2: the model the user chose for this agent's request, or None to
    serve what it asked for. Background-looking requests use the agent's
    background model when one is set; everything else its main model."""
    if not (ctx.desktop and agent_id):
        return None
    m = ctx.prefs.agent_models.get(agent_id)
    if m is None:
        return None
    if is_background_model(requested):
        return m.background
    return m.main


def mapped_unavailable_detail(agent_name: str, model: str) -> str:
    return (
        f"{model}, the model chosen for {agent_name}, isn't available. Add a key that serves it, "
        "or turn on \"If a model isn't available, use auto\" in Orca."
    )


def needs_paid_reason(needs: set[str], prompt_tokens: int) -> str:
    """Why free models can't take a request, in words for the user."""
    if "vision" in needs:
        return "images"
    if prompt_tokens > FREE_HOSTED_CONTEXT_TOKENS:
        return "very long context"
    return "features free models don't have"


def needs_paid_detail(reason: str) -> str:
    return (
        f"This request needs a paid model ({reason}). Open Orca and choose \"Use paid models\" "
        "to allow OrcaRouter's paid models."
    )


def out_of_credit_detail(billing_url: str) -> str:
    return (
        f"OrcaRouter is out of credit. Add credit at {billing_url}, "
        "or add your own provider key in Orca."
    )
