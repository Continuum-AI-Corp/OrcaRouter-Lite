"""Codex picks its tools (apply_patch among them) from the model's metadata,
and gets none of that for an unknown name like "auto". So Orca connects
Codex with a name Codex recognises (CODEX_AUTO_MODEL, prefixed with a model
in its catalog) and the engine routes that name exactly like model="auto"."""

from __future__ import annotations

from packages.desktop.agents import CODEX_AUTO_MODEL
from tests.integration.routing_harness import FakeRouter, own

PING = {"messages": [{"role": "user", "content": "ping"}]}


def test_the_alias_starts_with_a_model_codex_knows():
    assert CODEX_AUTO_MODEL.startswith("gpt-5.5")
    assert CODEX_AUTO_MODEL != "gpt-5.5"


async def test_codex_alias_is_routed_like_auto(engine):
    engine.router = FakeRouter([*own("openai", "gpt-4o-mini", "gpt-4.1")])
    key = await engine.agent_key("codex")
    r = await engine.chat(key, {**PING, "model": CODEX_AUTO_MODEL})
    assert r.status_code == 200, r.text
    assert r.headers["x-orca-requested-model"] == "auto"
    assert engine.router.calls[-1]["model"] in {"gpt-4o-mini", "gpt-4.1"}
    log = await engine.last_log()
    assert log.model_requested == "auto"
