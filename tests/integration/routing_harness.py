"""A desktop-mode engine with a scripted router, for routing tests.

The router stands in for LiteLLM: it serves the first model of the
`[model] + fallbacks` chain that isn't scripted to fail, attributes it to
the deployment that serves that name (own key before OrcaRouter, as a
real cascade would reach them) and can stream. Tests set the deployments,
the desktop settings and which models fail, then read what was called and
what was logged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select

from packages.litellm_adapter.types import ProviderDeployment, UpstreamProviderError

HOSTED = "orcarouter"
USAGE = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}


def own(provider: str, *models: str) -> list[ProviderDeployment]:
    return [ProviderDeployment(model_name=m, litellm_model=f"{provider}/{m}", api_key="k", provider=provider)
            for m in models]


def hosted(*models: str) -> list[ProviderDeployment]:
    return [ProviderDeployment(model_name=m, litellm_model=m if "/" in m else f"x/{m}", api_key="sk-orca-x",
                               api_base="http://orca.test/v1", provider=HOSTED, custom_llm_provider="openai",
                               deployment_id=f"hosted::{m}")
            for m in models]


def local(*models: str) -> list[ProviderDeployment]:
    return [ProviderDeployment(model_name=m, litellm_model=f"ollama_chat/{m.split('/', 1)[1]}", api_key="local",
                               api_base="http://127.0.0.1:11434", provider="local", deployment_id=f"local::{m}")
            for m in models]


@dataclass
class FakeRouter:
    _deployments: list[ProviderDeployment]
    strategy: str = "cheapest"
    preferred_models: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    # model name or provider -> the error it raises
    failing: dict[str, Exception] = field(default_factory=dict)
    # provider -> cost the hosted API reported (X-OrcaRouter-beta-usd)
    cost_usd: dict[str, float] = field(default_factory=dict)

    def _serving(self, model: str) -> ProviderDeployment | None:
        hits = [d for d in self._deployments if d.model_name == model]
        hits.sort(key=lambda d: d.provider == HOSTED)
        return hits[0] if hits else None

    async def acompletion(self, *, fallbacks=None, **kw):
        self.calls.append({**kw, "fallbacks": fallbacks})
        chain = [kw["model"], *((fallbacks or [{}])[0].get(kw["model"], []))]
        error: Exception | None = None
        for model in chain:
            dep = self._serving(model)
            if dep is None:
                error = UpstreamProviderError(f"no deployment for {model}", http_status=503,
                                              error_type="upstream_error")
                continue
            err = self.failing.get(model) or self.failing.get(dep.provider)
            if err is not None:
                error = err
                continue
            return self._respond(model, dep, kw)
        raise error

    def _respond(self, model, dep, kw):
        meta = {"provider": dep.provider, "latency_ms": 5}
        if dep.provider in self.cost_usd:
            meta["cost_usd"] = self.cost_usd[dep.provider]
        base = {"id": "chatcmpl-r", "created": int(time.time()), "model": model}
        if not kw.get("stream"):
            return {**base, "object": "chat.completion", "usage": USAGE, "_orca_meta": meta,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                 "finish_reason": "stop"}]}
        return _Stream(base, dep)


class _Stream:
    """Async-iterable stand-in for LiteLLM's stream wrapper."""

    def __init__(self, base, dep):
        self._base = base
        self._hidden_params = {"model_id": dep.deployment_id, "api_base": dep.api_base}
        if dep.provider == HOSTED:
            self._hidden_params["additional_headers"] = {"llm_provider-x-orcarouter-beta-usd": "0.0123"}

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        chunk = {**self._base, "object": "chat.completion.chunk"}
        yield {**chunk, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"},
                                     "finish_reason": None}]}
        yield {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": USAGE}


@dataclass
class Engine:
    app: object
    factory: object
    root_key: str
    router: FakeRouter | None = None

    def client(self, key: str):
        from httpx import ASGITransport, AsyncClient

        return AsyncClient(transport=ASGITransport(app=self.app), base_url="http://t",
                           headers={"Authorization": f"Bearer {key}"})

    async def agent_key(self, agent_id: str) -> str:
        from packages.auth.hashing import generate_api_key
        from packages.db.models.api_key import ApiKey

        full, h, prefix = generate_api_key()
        async with self.factory() as s:
            s.add(ApiKey(workspace_id="default", name=f"agent:{agent_id}", key_hash=h, key_prefix=prefix))
            await s.commit()
        return full

    async def settings(self, **desktop) -> None:
        from packages.db.models.workspace import Workspace
        from packages.desktop import budget

        async with self.factory() as s:
            ws = await s.get(Workspace, "default")
            ws.settings_json = {**(ws.settings_json or {}), "desktop": desktop}
            await s.commit()
        budget.note_settings_changed()

    async def logs(self) -> list:
        from packages.db.models.request_log import RequestLog

        async with self.factory() as s:
            return list((await s.execute(select(RequestLog).order_by(RequestLog.created_at))).scalars())

    async def last_log(self):
        rows = await self.logs()
        return rows[-1]

    async def chat(self, key: str, body: dict, *, stream: bool = False):
        """POST /v1/chat/completions; for streams, read the whole body."""
        body = {**body, "stream": stream}
        async with self.client(key) as c:
            if not stream:
                return await c.post("/v1/chat/completions", json=body)
            async with c.stream("POST", "/v1/chat/completions", json=body) as r:
                await r.aread()
                return r


@pytest.fixture
async def engine(tmp_sqlite_url, monkeypatch, isolated_env):
    """A desktop-mode engine whose router is whatever `engine.router` is."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("ORCA_DESKTOP_MODE", "1")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("ORCA_NO_LOCAL_MODELS", "1")
    from app import config, router_cache
    from packages.desktop import budget, hosted_state

    config.get_settings.cache_clear()
    budget.note_settings_changed()
    hosted_state.reset()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    db_engine = build_engine(tmp_sqlite_url)
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "_session_factory", factory)

    from app.seed import seed_initial_state

    async with factory() as s:
        seed = await seed_initial_state(s)

    from app.main import create_app

    eng = Engine(app=create_app(), factory=factory, root_key=seed.api_key)

    async def _get_router(_session):
        return eng.router

    monkeypatch.setattr(router_cache, "get_router", _get_router)
    yield eng
    await db_engine.dispose()
    config.get_settings.cache_clear()
    budget.note_settings_changed()
    hosted_state.reset()
