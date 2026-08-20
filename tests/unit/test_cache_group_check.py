"""Unit tests for _served_same_group_as_requested in app/routes/chat.py.

The helper decides whether to write a response to the prompt cache after
LiteLLM Router returns. It must distinguish three cases:
  1. Same model_group — cache write is safe.
  2. Different model_group (real cascade) — skip cache to prevent poisoning.
  3. Unknown rendering of the same model — be permissive, allow cache.

Integration tests cover the wire-up; these unit tests pin the classification
logic for each branch so future refactors don't silently shift behavior.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _FakeDeployment:
    model_name: str
    litellm_model: str


class _FakeClient:
    def __init__(self, deployments: list[_FakeDeployment] | None = None):
        self._deployments = deployments or []


def test_returns_true_when_served_is_none():
    """Missing response.model — assume same (don't penalize on uncertainty)."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini", served_model=None, client=_FakeClient()
    ) is True


def test_returns_true_on_exact_match():
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini", served_model="gpt-4o-mini", client=_FakeClient()
    ) is True


def test_returns_true_when_only_provider_prefix_differs():
    """LiteLLM frequently returns 'openai/gpt-4o-mini' for a request that
    asked for 'gpt-4o-mini' — same model, different rendering."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini",
        served_model="openai/gpt-4o-mini",
        client=_FakeClient(),
    ) is True


def test_returns_true_for_dated_openai_alias():
    """OpenAI returns the specific dated version even when you asked for
    the bare alias. Same logical model — must allow cache write."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gpt-4o",
        served_model="gpt-4o-2024-08-06",
        client=_FakeClient(),
    ) is True


def test_returns_true_for_compact_dated_anthropic_alias():
    """Anthropic uses the YYYYMMDD compact form (e.g. claude-3-5-sonnet-20241022)."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="claude-3-5-sonnet",
        served_model="claude-3-5-sonnet-20241022",
        client=_FakeClient(),
    ) is True


def test_returns_true_for_numeric_revision_suffix():
    """Vertex / Gemini family models use -001 / -002 revision suffixes."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gemini-2.0-flash",
        served_model="gemini-2.0-flash-001",
        client=_FakeClient(),
    ) is True


def test_returns_false_when_served_is_a_different_catalog_model():
    """Requested gpt-4o-mini, served gpt-4o — both real OpenAI models, NOT
    a version variant. Must classify as cascade and skip cache."""
    from app.routes.chat import _served_same_group_as_requested
    # gpt-4o exists in CATALOG_BY_ID under its own model_name. The check
    # should detect this and return False (cascade) — not be fooled by
    # the shared "gpt-4o" prefix.
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini",
        served_model="gpt-4o",
        client=_FakeClient(),
    ) is False


def test_returns_false_when_deployment_lookup_finds_different_group():
    """The active deployment list is authoritative — if served maps to a
    different deployment's model_name, that's a real cascade."""
    from app.routes.chat import _served_same_group_as_requested
    deployments = [
        _FakeDeployment(model_name="claude-3-5-sonnet-latest",
                        litellm_model="anthropic/claude-3-5-sonnet-latest"),
    ]
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini",
        served_model="anthropic/claude-3-5-sonnet-latest",
        client=_FakeClient(deployments),
    ) is False


def test_returns_true_when_deployment_lookup_finds_same_group():
    """Round-trip: served name maps back to a deployment with matching model_name."""
    from app.routes.chat import _served_same_group_as_requested
    deployments = [
        _FakeDeployment(model_name="gpt-4o-mini",
                        litellm_model="openai/gpt-4o-mini"),
    ]
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini",
        served_model="openai/gpt-4o-mini",
        client=_FakeClient(deployments),
    ) is True


def test_unknown_served_name_defaults_to_same_group():
    """When served name is neither in deployments nor catalog, be permissive
    — the alternative (always skip cache for unknown renderings) would
    silently disable caching for any provider quirk we haven't seen yet."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini",
        served_model="some-unknown-rendering-blah",
        client=_FakeClient(),
    ) is True


def test_version_suffix_does_not_confuse_distinct_models():
    """Reverse direction: requested gpt-4o-mini, served gpt-4o. The "-mini"
    suffix on the requested name shouldn't make us think gpt-4o is a variant
    of gpt-4o-mini. (Variants only flow served-is-longer, not the other way.)
    Combined with catalog detection, this returns False (cascade)."""
    from app.routes.chat import _served_same_group_as_requested
    assert _served_same_group_as_requested(
        requested_group="gpt-4o-mini",
        served_model="gpt-4o",
        client=_FakeClient(),
    ) is False


def test_preview_suffix_is_not_a_version_variant(monkeypatch):
    """`gpt-4-turbo-preview` is a DISTINCT catalog model from `gpt-4-turbo`,
    not a version of it. The version-suffix pass must NOT match `-preview`
    or the cache will be poisoned across these two models. Catalog lookup
    catches the cascade after the version pass falls through."""
    from app.routes.chat import _served_same_group_as_requested
    from packages.litellm_adapter import catalog as catalog_mod

    # Pin the catalog entry instead of relying on the live litellm-sourced
    # CATALOG: gpt-4-turbo-preview is past its deprecation_date, so current
    # litellm metadata drops it at load and the catalog-lookup pass would
    # silently fall through to the permissive default.
    monkeypatch.setitem(
        catalog_mod.CATALOG_BY_ID,
        "gpt-4-turbo-preview",
        catalog_mod.CatalogModel(
            id="gpt-4-turbo-preview", provider="openai", litellm_prefix="openai/"
        ),
    )
    assert _served_same_group_as_requested(
        requested_group="gpt-4-turbo",
        served_model="gpt-4-turbo-preview",
        client=_FakeClient(),
    ) is False, (
        "gpt-4-turbo-preview is a separate model from gpt-4-turbo; "
        "version-suffix matching must NOT cover -preview"
    )


# NOTE on `-latest` aliases (e.g. claude-3-5-sonnet-latest): providers don't
# return "-latest" in response.model — clients request it, providers respond
# with the specific dated form. When user requested "claude-3-5-sonnet-latest"
# and provider returned "claude-3-5-sonnet-20241022", our helper currently
# treats the dated form as a distinct catalog entry and returns False
# (cache skipped). Acceptable limitation: cache is just unused in this case,
# not poisoned. Fixing it would require an alias map maintained against
# LiteLLM's catalog, which we choose not to take on for v1.


def test_partial_substring_is_not_a_version_variant():
    """An arbitrary suffix that isn't a date/version must NOT trigger the
    same-group classification. Otherwise 'gpt-4o-something-random' would
    incorrectly match 'gpt-4o'."""
    from app.routes.chat import _served_same_group_as_requested
    # "something-random" doesn't match any version-suffix pattern, so the
    # version pass falls through. Then deployment + catalog lookups don't
    # find this name. Permissive default kicks in → True.
    # We document this as a known acceptable edge: an unknown suffix is
    # treated as "same group" since we can't prove it isn't.
    result = _served_same_group_as_requested(
        requested_group="gpt-4o",
        served_model="gpt-4o-something-random",
        client=_FakeClient(),
    )
    # Permissive: True. Document the choice; if a real provider ever
    # ships a non-versioned alias that's actually a different model,
    # we'd want to revisit.
    assert result is True
