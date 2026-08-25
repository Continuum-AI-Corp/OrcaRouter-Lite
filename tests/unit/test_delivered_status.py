"""`delivered_status` on both native surfaces (PR #64 round 12).

It is what `execute_chat(log_status=...)` persists, so it must equal the
status `error_response` actually renders — native_status alone leaves a
generic upstream 5xx at 503 while the Anthropic envelope delivers 500.
"""

from __future__ import annotations

import pytest

from app.protocols import anthropic as anthropic_proto
from app.protocols import gemini as gemini_proto


@pytest.mark.parametrize("engine_status,error_type,expected", [
    (422, "model_not_found", 404),
    (503, "upstream_auth_error", 403),
    (503, "no_providers_configured", 403),
    (422, "no_capable_provider", 403),
    (429, "rate_limit_error", 429),
    (422, "context_length_exceeded", 400),
    # unmapped generic failures: the envelope collapses them to 500
    (503, "upstream_error", 500),
    (503, "upstream_timeout", 500),
    (503, "something_unknown", 500),
    (422, None, 400),
    # not an error the envelope rewrites
    (499, "client_disconnect", 499),
])
def test_anthropic_delivered_status_matches_the_rendered_envelope(
    engine_status, error_type, expected,
):
    assert anthropic_proto.delivered_status(engine_status, error_type) == expected
    rendered = anthropic_proto.error_response(
        anthropic_proto.native_status(engine_status, error_type), "boom",
    )
    assert rendered.status_code == expected


@pytest.mark.parametrize("engine_status,error_type,expected", [
    (422, "model_not_found", 404),
    (503, "upstream_auth_error", 403),
    (503, "no_providers_configured", 403),
    (422, "no_capable_provider", 403),
    (429, "rate_limit_error", 429),
    (422, "context_length_exceeded", 400),
    (503, "upstream_error", 503),
    (503, "upstream_timeout", 503),
    (503, "something_unknown", 503),
    (422, None, 400),
    (499, "client_disconnect", 499),
])
def test_gemini_delivered_status_matches_the_rendered_envelope(
    engine_status, error_type, expected,
):
    assert gemini_proto.delivered_status(engine_status, error_type) == expected
    rendered = gemini_proto.error_response(
        gemini_proto.native_status(engine_status, error_type), "boom",
    )
    assert rendered.status_code == expected
