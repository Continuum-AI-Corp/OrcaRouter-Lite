"""Model catalog — lite reads from litellm.model_cost dynamically.

The 16-model hardcoded catalog is too small for serious adoption. Lite
should expose every chat-capable model litellm knows about, which is
~100+, with capability flags (tools, vision, json_mode) read from the
same metadata litellm uses internally.
"""

from __future__ import annotations


def test_catalog_has_at_least_50_models():
    """A real catalog. The 16-model hardcoded list was a placeholder."""
    from packages.litellm_adapter.catalog import all_model_ids

    assert len(all_model_ids()) >= 50


def test_catalog_includes_known_flagship_models():
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    expected_exact = {
        "gpt-4o",
        "gpt-4o-mini",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
    }
    missing = expected_exact - set(CATALOG_BY_ID)
    assert not missing, f"missing flagship models: {missing}"

    # Gemini family — accept any 2.x or 3.x flagship since the lineup churns.
    has_gemini_flagship = any(
        k.startswith(("gemini-2.", "gemini-3."))
        for k in CATALOG_BY_ID
    )
    assert has_gemini_flagship, "expected at least one Gemini 2.x/3.x model"


def test_catalog_capability_flags_set_correctly():
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    gpt4o = CATALOG_BY_ID["gpt-4o"]
    assert gpt4o.supports_tools is True
    assert gpt4o.supports_vision is True
    # litellm tracks json mode under "supports_response_schema" / "supports_json"
    # — we accept whichever the inference picks up.
    assert gpt4o.supports_json_mode is True


def test_catalog_each_entry_has_required_fields():
    from packages.litellm_adapter.catalog import CATALOG

    for m in CATALOG:
        assert m.id and isinstance(m.id, str)
        assert m.provider and isinstance(m.provider, str)
        assert m.litellm_prefix.endswith("/")
        assert isinstance(m.supports_tools, bool)
        assert isinstance(m.supports_vision, bool)
        assert isinstance(m.supports_json_mode, bool)


def test_catalog_models_for_provider_returns_grouped_models():
    from packages.litellm_adapter.catalog import models_for_provider

    openai_models = models_for_provider("openai")
    assert any(m.id == "gpt-4o" for m in openai_models)
    assert all(m.provider == "openai" for m in openai_models)

    anthropic_models = models_for_provider("anthropic")
    assert any(m.id.startswith("claude-") for m in anthropic_models)


def test_catalog_excludes_embeddings_and_image_models():
    """Lite's /v1/models is for chat. Embedding and image models live elsewhere."""
    from packages.litellm_adapter.catalog import all_model_ids

    ids = set(all_model_ids())
    assert "text-embedding-3-small" not in ids
    assert "text-embedding-ada-002" not in ids
    assert "dall-e-3" not in ids
    assert "stable-diffusion-xl-base-1.0" not in ids


def test_catalog_pricing_metadata_available():
    """Each model exposes input/output cost per token for the cost-savings widget."""
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    gpt4o = CATALOG_BY_ID["gpt-4o"]
    assert gpt4o.input_cost_per_token > 0
    assert gpt4o.output_cost_per_token > 0


def test_catalog_lists_hosted_free_models_with_zero_cost():
    """The zero-credit O2 models are discoverable in the catalog (feeding
    GET /v1/models and /v1beta/models) under the provider-qualified wire
    IDs O2's own listing uses — each has a matching hosted deployment via
    HOSTED_MODEL_ALIASES."""
    from packages.litellm_adapter.catalog import CATALOG_BY_ID
    from packages.litellm_adapter.hosted_catalog import HOSTED_MODEL_ALIASES

    for wire_id in HOSTED_MODEL_ALIASES:
        m = CATALOG_BY_ID.get(wire_id)
        assert m is not None, f"{wire_id} missing from catalog"
        assert m.input_cost_per_token == 0.0
        assert m.output_cost_per_token == 0.0


def test_free_models_are_listed_but_not_auto_eligible():
    """Deliberate interaction: choose_auto_model excludes zero-blended-cost
    entries (unpriced ≠ free in litellm's catalog, and zero-cost wins would
    skew the savings math), so the free models are discoverable + pinnable
    but never auto-selected."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    m = CATALOG_BY_ID["orcarouter/free"]
    chosen, _ = choose_auto_model(
        needs=set(), deployable={"orcarouter/free"}, candidates=[m],
    )
    assert chosen == []
