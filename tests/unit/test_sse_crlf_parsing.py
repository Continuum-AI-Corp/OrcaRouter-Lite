"""Regression: SSE frame parser must handle \\r\\n line endings.

The W3C SSE spec allows \\r\\n, \\r, or \\n as line separators. Some upstream
providers (notably Azure-hosted OpenAI models) send \\r\\n\\r\\n as the frame
delimiter. Without normalization the parser never finds the \\n\\n boundary
and buffers the entire response in memory until the connection closes,
at which point it yields nothing."""

from __future__ import annotations

import pytest

from app.protocols.sse import OpenAIFrameStream


async def _collect(stream: OpenAIFrameStream) -> list[dict]:
    frames = []
    async for frame in stream:
        frames.append(frame)
    return frames


@pytest.mark.asyncio
async def test_sse_parses_crlf_frame_boundaries():
    """Frames separated by \\r\\n\\r\\n must parse identically to \\n\\n."""
    async def source():
        yield b"data: {\"id\":\"1\",\"content\":\"hello\"}\r\n\r\n"
        yield b"data: [DONE]\r\n\r\n"

    stream = OpenAIFrameStream(source())
    frames = await _collect(stream)
    assert len(frames) == 1
    assert frames[0]["id"] == "1"
    assert frames[0]["content"] == "hello"
    assert stream._done is True


@pytest.mark.asyncio
async def test_sse_parses_mixed_line_endings():
    """A stream mixing \\r\\n and \\n must still parse correctly."""
    async def source():
        yield "data: {\"id\":\"a\"}\r\n\r\n"
        yield "data: {\"id\":\"b\"}\n\n"
        yield "data: [DONE]\r\n\r\n"

    stream = OpenAIFrameStream(source())
    frames = await _collect(stream)
    assert len(frames) == 2
    assert frames[0]["id"] == "a"
    assert frames[1]["id"] == "b"
    assert stream._done is True


@pytest.mark.asyncio
async def test_sse_parses_cr_only_line_endings():
    """Bare \\r (classic Mac-style) is a valid SSE line ending."""
    async def source():
        yield "data: {\"id\":\"x\"}\r\r"
        yield "data: [DONE]\r\r"

    stream = OpenAIFrameStream(source())
    frames = await _collect(stream)
    assert len(frames) == 1
    assert frames[0]["id"] == "x"
    assert stream._done is True
