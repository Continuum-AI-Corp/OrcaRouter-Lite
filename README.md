# OrcaRouter Lite

**Self-hosted LLM router with a managed safety net.**
OpenAI-compatible. BYOK. Single-workspace. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

## Languages

- [English](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Deutsch](./README.de.md)
- [Français](./README.fr.md)
- [Español](./README.es.md)
- [Italiano](./README.it.md)
- [Русский](./README.ru.md)
- [Português](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite is the open-source single-workspace edition of [OrcaRouter](https://www.orcarouter.ai). Run it on your laptop, ship it in your product, or use hosted `api.orcarouter.ai` directly for the long tail of models you don't want to manage keys for.

> **Why us?** LiteLLM is a library; OpenRouter is closed-source hosted; Ollama is local-only. We're the **self-hosted server with a managed fallback** — a sentence none of those can say.

## 60-second quickstart

Two ways to use OrcaRouter:

### Path A — Self-hosted (BYOK)

Run Lite on your own machine; bring your own provider keys.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Base URL: `http://localhost:8000/v1`. Use the `sk-orca-*` key printed at startup.

### Path B — Hosted (account required)

No clone, no docker. Register, get a key, point any OpenAI SDK at hosted.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Account required.** Hosted handles routing, billing, and the long tail of providers — billed per-token on your OrcaRouter account. See [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Then call it from any OpenAI SDK

Examples below use Path A's localhost base URL — swap for `https://api.orcarouter.ai/v1` if you're on Path B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # or "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "Hello!"}],
)
print(r.choices[0].message.content)
```
</details>

<details>
<summary><b>Node.js</b></summary>

```js
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8000/v1",
  apiKey: "sk-orca-abc123...",
});

const r = await client.chat.completions.create({
  model: "auto",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(r.choices[0].message.content);
```
</details>

<details>
<summary><b>curl</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

Open `http://localhost:8000/` for the dashboard — providers, routing, analytics, keys (Path A only).

## Why?

| | OrcaRouter Lite | LiteLLM library | OpenRouter | Ollama |
|---|---|---|---|---|
| Self-hosted server | ✓ | as a library | ✗ | ✓ |
| OpenAI-compatible | ✓ | ✓ | ✓ | ✓ |
| Multi-provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Built-in dashboard | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (cheapest capable) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hosted-as-fallback | ✓ | ✗ | n/a | ✗ |
| No Postgres / no Redis required | ✓ | n/a | n/a | ✓ |

## `model="auto"` — the headline feature

Send `model="auto"` and OrcaRouter picks the **cheapest** model in your configured providers that meets the request's capability requirements (tools, vision, JSON mode). No manual routing rules; no rate-limit gymnastics; no `if x: ...` cost optimization in your code.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → routes to the cheapest VISION-capable model your keys cover
```

The resolved model is exposed back to callers via the `x-orca-resolved-model` response header so you can log/display what was actually used.

## Hosted as upstream (Lite + hosted)

Already running Lite? Set `ORCAROUTER_API_KEY` to your `sk-orca-*` from [www.orcarouter.ai](https://www.orcarouter.ai), and hosted becomes one more provider in the routing chain — covering models your local keys don't:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Use cases:
- **Try-before-you-buy** — no local provider keys needed
- **Local logging** — hosted handles routing, Lite stores RequestLog rows for the dashboard
- **Failover** — local providers fail, hosted is the safety net

## Streaming

OpenAI-compatible SSE format with the standard `data: ... \n\n` framing and a terminal `[DONE]` sentinel — drop-in for any SDK that already streams from OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Model catalog

100+ chat models are loaded at startup from [LiteLLM's community-maintained pricing database](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — no model list to maintain manually. Each entry exposes:

- `id` (e.g. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapped to your configured keys)
- Capability flags: `supports_tools`, `supports_vision`, `supports_json_mode`
- Per-token input/output cost (drives the savings widget + `model="auto"`)

`GET /v1/models` returns the OpenAI-format catalogue.

## Deploy somewhere else

### Required secrets (all platforms)

Generate two secrets before deploying. Without them the app falls back to a
hardcoded dev key (`packages/auth/encryption.py:47`) — every operator's stored
provider keys would be decryptable from public source code.

```bash
# CREDENTIAL_ENCRYPTION_KEY — encrypts provider keys at rest in SQLite.
openssl rand -hex 32

# API_KEY_PEPPER — strengthens API-key hashing from SHA-256 to HMAC-SHA256.
openssl rand -hex 32
```

Plus at least one provider key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`,
`TOGETHER_API_KEY`, `FIREWORKS_API_KEY`) **or** `ORCAROUTER_API_KEY` for the
hosted fallback.

### Fly.io

Repo includes `fly.toml` with volume + healthcheck + auto-stop pre-configured.

```bash
fly auth login
fly apps create my-orca-lite                                    # pick a name
fly volumes create lite_data --size 1 --region iad              # match fly.toml region
fly secrets set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32)
fly secrets set API_KEY_PEPPER=$(openssl rand -hex 32)
fly secrets set OPENAI_API_KEY=sk-...                           # at least one provider
fly deploy
```

`fly.toml` configures a minimum-spec VM (`shared-cpu-1x` / 512MB / 1GB volume).
`auto_stop_machines = "stop"` + `min_machines_running = 0` stops the machine
when idle and auto-starts on the next request, controlling cost.

### Railway

Repo includes `railway.json` with Dockerfile build + healthcheck pre-configured.

1. **Connect repo**: New Project → Deploy from GitHub repo → pick this repo
2. **Create a volume**: open the Command Palette (`⌘K`) and select "Create Volume"
   (or right-click the project canvas → New → Volume). When prompted, attach it
   to the service and set the **mount path** to `/data`. Default size depends on
   plan (Hobby: 5 GB) — 1 GB is plenty for SQLite.
3. **Set env vars** in Service → Variables:
   - `DATABASE_URL=sqlite+aiosqlite:////data/orca.db` (note the four slashes)
   - `CREDENTIAL_ENCRYPTION_KEY=` (paste output of `openssl rand -hex 32`)
   - `API_KEY_PEPPER=` (paste another `openssl rand -hex 32`)
   - `OPENAI_API_KEY=sk-...` (or another provider key)
4. **Generate a public domain**: Service → Settings → Networking →
   Public Networking → Generate Domain.
5. Railway auto-deploys on every push to `main`.

### Render / Bare Docker

```bash
# Render: connect repo, root = ., let it auto-detect the Dockerfile.
# Add a Disk mounted at /data, set the same env vars as Railway above.

# Bare Docker (single-host VM):
docker volume create lite_data
docker run -d -p 8000:8000 \
  -v lite_data:/data \
  -e DATABASE_URL=sqlite+aiosqlite:////data/orca.db \
  -e CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) \
  -e API_KEY_PEPPER=$(openssl rand -hex 32) \
  -e OPENAI_API_KEY=sk-... \
  ghcr.io/continuum-ai-corp/orcarouter-lite:latest    # image not yet published
```

## What's in the box

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cross-provider prompt cache
- `GET  /v1/models` — discoverable model catalog (100+ models from `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — set / list / revoke encrypted provider keys
- `GET/PUT /v1/routing` — change strategy (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — local analytics, no telemetry leaves the box
- `GET  /v1/hosted` — hosted-fallback status (drives the dashboard's "Get $5 free credit" card)
- `GET/POST/DELETE /v1/keys/...` — list / rotate / revoke API keys
- Single-page dashboard at `/`
- SQLite by default; Postgres opt-in via `DATABASE_URL`; Redis optional

### Cross-provider prompt cache

Deterministic requests (`temperature=0` or pinned `seed`) are served from cache on repeat — works across **every** provider, not just Anthropic. Backend is Redis when `REDIS_URL` is set, in-process LRU otherwise. Cache hits return instantly with `x-orca-cache: HIT` and cost $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Savings widget

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` reports what your traffic would have cost on always-GPT-4 vs what it actually cost. The dashboard shows it as a tile.

### Integrations

Drop-in configs for [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts), and any tool that speaks the OpenAI Chat Completions protocol. See [`integrations/`](./integrations/).

## What's deliberately not

This is the **single-workspace** edition. By design, no:
- multi-tenancy, RBAC, SSO
- billing, wallets, points, partner program
- admin console, audit logs, trust & safety
- multi-pod deployment / Kubernetes
- email / Slack / webhooks for alerts

For those, see the hosted product or the (forthcoming) Teams edition.

## Testing

Built test-first. Every behaviour shipped here had a failing test first.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Slice | Tests | What |
|---|---|---|
| 1. Config | 5 | env loading, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + API key + RoutingConfig, idempotent |
| 3. Auth middleware | 4 | bearer-token validation, 401 on missing/invalid |
| 4. App factory | 3 | /health, error envelope, /v1/* gating |
| 5. Provider keys CRUD | 5 | encrypted at rest, plaintext never round-trips |
| 6. Router cache | 13 | env+DB+hosted deployment assembly with precedence |
| 7. Chat completion | 5 | OpenAI format, RequestLog, validation |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + strategy update |
| 10. Streaming | 4 | SSE format, `[DONE]` sentinel, log writeback |
| 11. Catalog | 7 | 100+ models, capability flags, pricing |
| 12. `model="auto"` | 21 | capability detection, cheapest-meeting-needs (unit + integration) |
| 13. Cost savings | 9 | savings vs always-GPT-4 baseline + hosted-auto comparison |
| 14. Prompt cache | 15 | cross-provider exact-match cache + chat integration |
| 15. Benchmark | 4 | summarize() + render_markdown() aggregation |
| 16. Hosted status | 7 | `/v1/hosted` config-source + signup-URL surface |
| 17. Hosted-auto savings | 3 | `_hosted_auto_savings` edge cases on synthetic catalogs |
| 18. Unreachable models | 7 | "models you can't reach" tile clears when hosted is on |
| **Total** | **127** | |

## Architecture

```
app/
├── main.py             FastAPI factory + lifespan + SPA mount
├── config.py           Settings (~15 fields)
├── deps.py             DI helpers
├── seed.py             First-run bootstrap
├── auto_routing.py     model="auto" capability + cost scoring
├── router_cache.py     Single-workspace router
├── prompt_cache.py     Cross-provider exact-match cache (Redis or in-memory LRU)
├── schemas.py          OpenAI-compatible request schema
├── middleware/auth.py  sk-orca-* validation
└── routes/
    ├── chat.py         /v1/chat/completions  (blocking + streaming)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      strategy config
    ├── analytics.py    recent / spend / latency / savings / unreachable
    ├── keys.py         list / rotate / revoke API keys
    ├── hosted.py       /v1/hosted — hosted-fallback status for the dashboard
    └── health.py

packages/
├── litellm_adapter/    Router wrapper + 100+ model catalog
├── auth/               hashing + AES-256-GCM
└── db/                 models + engine + session
```

## Roadmap

- [x] OpenAI-compatible chat completions
- [x] Streaming (SSE)
- [x] `model="auto"` cheapest-capable routing
- [x] Hosted-as-upstream
- [x] Encrypted BYOK at rest
- [x] Local analytics dashboard
- [x] CI (GitHub Actions)
- [x] Cross-provider prompt caching
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK integrations
- [x] Public benchmark + savings claim
- [ ] Embeddings + image-gen proxy

See [DEMO.md](./DEMO.md) for the failover demo.

## License

MIT. See [LICENSE](./LICENSE).
