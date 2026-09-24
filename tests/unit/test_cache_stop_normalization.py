"""Regression: prompt cache key must normalize stop to a list.

OpenAI wire format accepts stop as either a string or a list of strings.
stop="foo" and stop=["foo"] produce identical upstream behavior, so
they must map to the same cache key. Without normalization, the two forms
produce different SHA-256 digests and the cache is fragmented."""

from app.prompt_cache import cache_key


def _base_kwargs(**overrides):
    kw = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0,
        "tools": None,
        "response_format": None,
        "seed": 42,
    }
    kw.update(overrides)
    return kw


def test_stop_string_vs_list_same_key():
    k1 = cache_key(**_base_kwargs(stop="END"))
    k2 = cache_key(**_base_kwargs(stop=["END"]))
    assert k1 == k2


def test_stop_list_order_matters():
    k1 = cache_key(**_base_kwargs(stop=["a", "b"]))
    k2 = cache_key(**_base_kwargs(stop=["b", "a"]))
    assert k1 != k2


def test_stop_multi_element_list_stable():
    kw = _base_kwargs(stop=["a", "b", "c"])
    k1 = cache_key(**kw)
    k2 = cache_key(**kw)
    assert k1 == k2
