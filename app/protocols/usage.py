"""Cache components of LiteLLM's inclusive prompt_tokens.

Only observed nonnegative integer counters are projected. None/missing is
unknown, not zero. Aliases describe the same tokens, so they must agree.
An invalid or out-of-bounds breakdown is omitted as a whole; callers keep
the inclusive input count rather than emit a fabricated negative remainder.
"""


def cache_components(usage: dict) -> dict[str, int]:
    prompt = usage.get("prompt_tokens")
    if type(prompt) is not int or prompt < 0:
        return {}
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        details = {}
    components = {}
    for target, aliases in (
        ("cache_read_input_tokens", ("cached_tokens",)),
        ("cache_creation_input_tokens", ("cache_write_tokens", "cache_creation_tokens", "cache_creation_input_tokens")),
    ):
        values = [source[key] for source, keys in ((usage, (target,)), (details, aliases))
                  for key in keys if source.get(key) is not None]
        if any(type(value) is not int or value < 0 for value in values):
            return {}
        if values:
            if any(value != values[0] for value in values):
                return {}
            components[target] = values[0]
    return components if sum(components.values()) <= prompt else {}
