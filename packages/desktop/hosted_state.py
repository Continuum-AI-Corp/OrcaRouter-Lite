"""Whether OrcaRouter is out of credit, as this engine last saw it (H4).

There's no balance API, but the hosted gateway answers 402 / payment
required when credit runs out. The engine then treats OrcaRouter as out of
credit for ten minutes: auto and agent fallback stop picking hosted models
so own keys serve what they can, and requests only OrcaRouter can serve get
a plain message saying where to add credit. Any later successful answer
from OrcaRouter clears it at once.

In-process only: it's a short-lived observation, not a setting, and a
restart simply finds out again.
"""

from __future__ import annotations

import time

OUT_OF_CREDIT_SECONDS = 600.0

_until: float = 0.0


def mark_out_of_credit(*, now: float | None = None) -> None:
    global _until
    _until = (time.monotonic() if now is None else now) + OUT_OF_CREDIT_SECONDS


def note_success() -> None:
    """OrcaRouter answered a request: it has credit again."""
    reset()


def out_of_credit(*, now: float | None = None) -> bool:
    return (time.monotonic() if now is None else now) < _until


def reset() -> None:
    global _until
    _until = 0.0
