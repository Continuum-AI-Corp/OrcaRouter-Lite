"""A provider's own 402 (DeepSeek with no balance left, say) is reported by
the engine as `payment_required`. Like OrcaRouter's out_of_credit it never
succeeds on retry, so every native surface must render it as a billing
error, not a retryable 5xx."""

from app.protocols import anthropic, gemini, responses


def test_anthropic_renders_payment_required_as_a_billing_error():
    assert anthropic._ENGINE_ERROR_STATUS["payment_required"] == 402


def test_responses_renders_payment_required_as_insufficient_quota():
    assert responses._ENGINE_ERROR_STATUS["payment_required"] == 402


def test_gemini_renders_payment_required_as_permission_denied():
    assert gemini._STREAM_ERROR_TYPE_TO_CODE["payment_required"] == 403


def test_gemini_never_calls_a_402_internal():
    assert gemini._STATUS_TO_GOOGLE_STATUS[402] == "PERMISSION_DENIED"
