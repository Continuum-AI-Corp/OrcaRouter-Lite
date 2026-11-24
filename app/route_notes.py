"""`requests_log.route_note`: why a request went where it did.

The desktop panel turns these into plain sentences ("41 requests answered
by gpt-4.1 instead of Claude", "3 requests failed with no backup"), so each
names one user-visible event. NULL means nothing worth saying.

A request gets at most one note. Failures say why they failed; a served
request says the most specific thing about how: an agent's model map
chose the model, it ran on this computer, it ran on a free model, or the
agent's model was swapped for another (H3). "free" and "local" outrank
"substituted" because they are what the panel counts as $0 requests; the
substitution itself is still visible as model_requested != model_resolved
on an agent's row.
"""

from __future__ import annotations

from packages.litellm_adapter.hosted_catalog import is_free_hosted

SUBSTITUTED = "substituted"
MAPPED = "mapped"
FREE = "free"
LOCAL = "local"
NEEDS_PAID = "needs_paid"
NO_FALLBACK = "no_fallback"
OUT_OF_CREDIT = "out_of_credit"

HOSTED_PROVIDER = "orcarouter"
LOCAL_PROVIDER = "local"

# Upstream failures that a backup provider would have rescued: overloaded,
# rate limited, down or too slow. Not a bad key, a missing model or a prompt
# that's too long, which fail the same way everywhere.
TRANSIENT_ERRORS = frozenset({"rate_limit_error", "overloaded_error", "upstream_error", "upstream_timeout"})


def served_at_no_cost(provider: str | None, served_model: str | None) -> bool:
    """Served on this computer or by one of OrcaRouter's free models."""
    if provider == LOCAL_PROVIDER:
        return True
    return provider == HOSTED_PROVIDER and is_free_hosted(served_model)


def for_success(*, intent: str | None, provider: str | None, served_model: str | None) -> str | None:
    """The note for a served request. `intent` is what routing decided
    before the call (MAPPED, SUBSTITUTED or None)."""
    if intent == MAPPED:
        return MAPPED
    if provider == LOCAL_PROVIDER:
        return LOCAL
    if provider == HOSTED_PROVIDER and is_free_hosted(served_model):
        return FREE
    return intent


def for_failure(error_type: str | None) -> str | None:
    if error_type == OUT_OF_CREDIT:
        return OUT_OF_CREDIT
    if error_type in TRANSIENT_ERRORS:
        return NO_FALLBACK
    return None
