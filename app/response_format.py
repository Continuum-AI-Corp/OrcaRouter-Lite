"""Normalize OpenAI `response_format` for the chat-completions path.

LangChain `with_structured_output(method="json_schema")` (and the
OpenAI SDK `beta.chat.completions.parse` helper it uses) send
`response_format` as:

    {"type": "json_schema", "json_schema": {"name", "strict", "schema"}}

`ChatCompletionRequest` already declares `response_format: dict | None`,
so the block is not dropped — but several on-the-wire variants are
rejected by OpenAI / LiteLLM as ``Invalid schema for response_format``:

* `strict` placed next to `type` (copy-pasted from LiteLLM/OpenAI docs)
* function-calling alias `parameters` instead of `schema`
* `strict: true` without `additionalProperties: false` on every object
  (OpenAI structured-outputs requirement)

`json_object` / `text` are left untouched.
"""

from __future__ import annotations

import copy

_INNER_KEYS = ("name", "description", "schema", "parameters", "strict")


def normalize_response_format(rf: dict | None) -> dict | None:
    """Return an OpenAI-shaped `response_format`, or the input if unknown."""
    if not isinstance(rf, dict):
        return rf

    rf_type = rf.get("type")
    looks_like_schema = (
        rf_type == "json_schema"
        or "json_schema" in rf
        or "schema" in rf
        or "parameters" in rf
    )
    if rf_type in ("text", "json_object") or not looks_like_schema:
        return rf

    out = {k: v for k, v in rf.items() if k != "strict"}
    misplaced_strict = rf.get("strict") if "strict" in rf else None

    inner = out.get("json_schema")
    if not isinstance(inner, dict):
        pulled = {k: out.pop(k) for k in _INNER_KEYS if k in out}
        if not pulled:
            return rf
        inner = pulled

    inner = dict(inner)
    if misplaced_strict is not None and "strict" not in inner:
        inner["strict"] = misplaced_strict
    if "schema" not in inner and "parameters" in inner:
        inner["schema"] = inner.pop("parameters")
    if not inner.get("name"):
        inner["name"] = "response"

    schema = inner.get("schema")
    if inner.get("strict") is True and isinstance(schema, dict):
        inner["schema"] = _ensure_openai_strict_schema(schema)

    out["type"] = "json_schema"
    out["json_schema"] = inner
    return out


def _ensure_openai_strict_schema(schema: dict) -> dict:
    """Recursively satisfy OpenAI structured-outputs `strict` constraints."""
    fixed = copy.deepcopy(schema)
    _apply_strict_constraints(fixed)
    return fixed


def _apply_strict_constraints(node: object) -> None:
    if not isinstance(node, dict):
        return
    is_object = node.get("type") == "object" or "properties" in node
    if is_object:
        node.setdefault("additionalProperties", False)
        props = node.get("properties")
        if isinstance(props, dict):
            node["required"] = list(props.keys())
            for child in props.values():
                _apply_strict_constraints(child)
    items = node.get("items")
    if isinstance(items, dict):
        _apply_strict_constraints(items)
    elif isinstance(items, list):
        for child in items:
            _apply_strict_constraints(child)
    for defs_key in ("$defs", "definitions"):
        defs = node.get(defs_key)
        if isinstance(defs, dict):
            for child in defs.values():
                _apply_strict_constraints(child)
    for combo in ("anyOf", "oneOf", "allOf"):
        alts = node.get(combo)
        if isinstance(alts, list):
            for child in alts:
                _apply_strict_constraints(child)
