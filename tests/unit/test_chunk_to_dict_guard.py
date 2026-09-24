"""Regression: _chunk_to_dict must handle None chunks gracefully.

Some LiteLLM stream wrappers yield None as a heartbeat/keepalive signal.
Without a guard, dict(None) raises TypeError and kills the stream for a
non-event. The function must return an empty dict for None so the stream
continues uninterrupted."""

from app.routes.chat import _chunk_to_dict


def test_chunk_to_dict_none_returns_empty():
    assert _chunk_to_dict(None) == {}


def test_chunk_to_dict_dict_passthrough():
    d = {"id": "1", "model": "gpt-4o"}
    assert _chunk_to_dict(d) is d


def test_chunk_to_dict_pydantic_model():
    class FakeModel:
        def model_dump(self, exclude_none=False):
            return {"id": "1", "model": "gpt-4o"}

    result = _chunk_to_dict(FakeModel())
    assert result == {"id": "1", "model": "gpt-4o"}


def test_chunk_to_dict_iterable_fallback():
    # A tuple of pairs is iterable and dict()-able
    result = _chunk_to_dict((("key", "value"),))
    assert result == {"key": "value"}
