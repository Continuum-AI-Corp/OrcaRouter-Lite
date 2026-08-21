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

    Used in adapter `finally` blocks to forward a client-side close
    (GeneratorExit on the outer generator) down the generator chain, so
    the engine's own disconnect handling (upstream aclose + request-log
    writeback) actually runs instead of waiting for GC finalization.
    """
    aclose = getattr(obj, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        pass


async def iter_openai_frames(body_iterator: AsyncIterable) -> AsyncGenerator[dict, None]:
    """Yield each OpenAI SSE frame as a dict; stop at the [DONE] sentinel.

    Completion semantics matter here: after [DONE] the source is DRAINED
    to natural completion, not aclose()d. The engine's SSE generator is
    suspended at the [DONE] yield with its `finally` (request-log
    writeback) still pending — draining lets that run on the normal path,
    while aclose() would raise GeneratorExit into it and the engine would
    misclassify a completed stream as a 499 client disconnect. The
    close-forwarding in `finally` therefore only fires on abnormal exit
    (downstream cancelled/closed us before [DONE]).
    """
    buffer = ""
    done = False
    try:
        async for piece in body_iterator:
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
                        done = True
                        break
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield parsed
                if done:
                    break
            if done:
                break
        if done:
            # Drain to completion so the source's finally block runs
            # naturally (the engine emits nothing after [DONE]).
            async for _ in body_iterator:
                pass
    finally:
        if not done:
            await aclose_quietly(body_iterator)
