"""The reserve has to be an upper bound on what actually gets billed.

Come in under and the request walks past a cap the operator set in real
money, and by the time the real cost is logged the hold is already gone.
"""

from app.routes.chat import _estimate_reserve_microcents
from app.schemas import ChatCompletionRequest

_VISION = [{"type": "image_url", "image_url": {"url": "https://x/y.jpg"}}]
_URL = "https://x/y.jpg"


def _reserve(content="hi", models=("gpt-4o-mini",), **kw) -> int:
    body = ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": content}], **kw
    )
    return _estimate_reserve_microcents(body, list(models))


def test_an_image_is_not_counted_as_its_own_url():
    """content is a list of parts once vision is involved.

    str() of that part is a fifteen character URL while the image itself
    bills around a thousand tokens, so counting characters reserved next
    to nothing against a real cost.
    """
    assert _reserve(content=_VISION, max_tokens=16) > 10 * _reserve(
        content=_URL, max_tokens=16
    )


def test_n_multiplies_the_output_side():
    """Each of the n completions is billed in full."""
    assert _reserve(n=4) > 3 * _reserve(n=1)


def test_a_cascade_reserves_the_dearest_candidate():
    """Auto-routing can land on a fallback, so price them all."""
    assert _reserve(models=("gpt-4o-mini", "gpt-4o")) == _reserve(models=("gpt-4o",))


def test_an_unpriceable_model_reserves_nothing():
    """Its logged cost is 0 too, so there's nothing to protect against."""
    assert _reserve(models=("not-a-real-model",)) == 0
