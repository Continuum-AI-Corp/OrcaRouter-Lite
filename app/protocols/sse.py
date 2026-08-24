"""Parse the chat engine's OpenAI-format SSE frames back into dicts.

The engine (`app.routes.chat.execute_chat`, streaming path) emits
`data: {json}\n\n` frames with a terminal `data: [DONE]\n\n` sentinel.
Protocol adapters consume those frames in-process and re-emit
native-format frames. The producer is our own code, so the framing is
fully controlled — buffering on `\n\n` boundaries here is defensive,
not load-bearing.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterable


async def aclose_quietly(obj) -> None:
    """Close an async generator if it supports it, swallowing errors.

    Used to forward a client-side close (GeneratorExit on the outer
    generator) down the generator chain, so the engine's own disconnect
    handling (upstream aclose + request-log writeback) actually runs
    instead of waiting for GC finalization.
    """
    aclose = getattr(obj, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        pass


async def finish_quietly(source) -> None:
    """Hand end-of-stream cleanup back to the frame source.

    `OpenAIFrameStream.finish()` when it is one (drain-or-close, see that
    class), a plain close for any other async iterable — which keeps the
    protocol transformers usable with a bare async generator of frame
    dicts, the property that lets them be unit-tested without an app.
    """
    finish = getattr(source, "finish", None)
    if finish is not None:
        await finish()
        return
    await aclose_quietly(source)


class OpenAIFrameStream:
    """The engine's SSE body, parsed into frames, with the post-[DONE]
    handoff under the adapter's control.

    Iteration yields each parsed frame and stops at the `[DONE]` sentinel
    WITHOUT resuming the engine past it. That ordering is the whole point.
    The engine's `sse()` generator is suspended at its `yield "[DONE]"`
    with its `finally` — the RequestLog writeback, a DB commit — still
    pending, so whoever resumes it awaits that commit. The adapter
    therefore emits its terminal protocol events first (Anthropic's
    message_stop, Gemini's final chunk) and calls `finish()` last, from
    its own `finally`, so a slow or wedged DB can never sit between the
    last content the client sees and the event that ends the stream.

    `finish()` is required, and does one of two things:
      - [DONE] was reached → DRAIN the engine to natural completion, so
        its `finally` runs on the normal path and the request is logged
        as the 200/503 it actually was.
      - it was not (client disconnect, cancellation) → forward the close
        down the chain, so the engine's disconnect handling (upstream
        aclose + 499 writeback) runs now instead of at GC finalization.
    """

    def __init__(self, body_iterator: AsyncIterable):
        self._source = body_iterator
        self._gen: AsyncGenerator[dict, None] | None = None
        self._done = False
        self._finished = False

    def __aiter__(self) -> AsyncGenerator[dict, None]:
        # One generator instance for the life of the stream: the error
        # paths re-enter iteration to consume the frames after an engine
        # error frame, and a fresh generator would drop whatever partial
        # frame is sitting in the parse buffer.
        if self._gen is None:
            self._gen = self._iter()
        return self._gen

    async def _iter(self) -> AsyncGenerator[dict, None]:
        buffer = ""
        async for piece in self._source:
            if isinstance(piece, bytes):
                piece = piece.decode("utf-8")
            buffer += piece
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                for line in frame.splitlines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):]
                    if payload.strip() == "[DONE]":
                        self._done = True
                        return
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield parsed
        # Source ended without a sentinel: the engine already ran to
        # completion, so there is nothing left to drain or close.
        self._done = True

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if not self._done:
            await aclose_quietly(self._source)
            return
        try:
            async for _ in self._source:
                pass
        except BaseException:
            # Closed or cancelled mid-drain: the engine is still suspended
            # at its [DONE] yield with the writeback pending, so forward
            # the close rather than leaving it to the GC finalizer (which
            # would record a delivered stream as a 499 disconnect, or drop
            # the row entirely if the process exits first).
            await aclose_quietly(self._source)
            raise
