# OrcaRouter Lite

**Put a budget on every coding agent.**
See and cap what Claude Code, Codex, Gemini CLI, OpenCode and your own apps spend, across every
model provider, without your prompts leaving your machine. A menu-bar app for one
developer, and a self-hosted router for a whole team. MIT licensed.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="The OrcaRouter Lite menu-bar panel: today's spend against a daily budget, connected coding agents and provider health" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="First-run setup: detected coding agents, where requests go, and a daily budget" width="420">
</p>

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

**Find us:** [All model APIs](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite is the open-source edition of [OrcaRouter](https://www.orcarouter.ai). It runs on your computer or your server, speaks the OpenAI, Anthropic and Gemini APIs, and can use hosted `api.orcarouter.ai` as a safety net for outages and for models you don't hold keys for.

**OrcaRouter** is the hosted gateway behind Lite's safety net: one key for every model, failover between providers, free models to start, and pay per request for paid models. The desktop app suggests it first and starts agents on its free models; your own provider keys remain a full alternative, with or without it.

## The desktop app

The Orca app lives in your menu bar. It runs the router on `127.0.0.1`, connects your
coding agents to it, and shows what they spend.

- **Spend today, per agent.** Today's total sits next to the clock; the panel splits it by agent, and a Monday notification sums up the week.
- **A daily budget.** Notifications at 80% and 100% of the amount you set. Alerts only by default; tick one box and Orca pauses your coding agents once it's reached.
- **One-click connect.** Orca edits the agent's own settings, keeps a backup, and restores it when you disconnect.
- **Never down.** When a provider fails or rate-limits you, requests fall back to another provider or to hosted OrcaRouter, and the app counts how many it rescued. Link your account with `orca link --key sk-orca-…` or in setup.
- **Private by default.** Prompts go straight from your agents to the provider you choose. No telemetry.
- **Works with your team's gateway.** `orca login https://ai-gw.example.com --key …` (or "Join my company's gateway" in setup) points your agents at the gateway your platform team runs; `orca logout` restores them.

**Install.** Just the app: it carries its own engine and a local SQLite file, so there's no
server or database to set up. Installers (`.dmg`, `.deb`, `.AppImage`, `.msi`) are built by
[`desktop.yml`](./.github/workflows/desktop.yml) and attached to each release, starting with
the next tagged version. **[INSTALL.md](./INSTALL.md)** covers downloading a build today, opening
it before it's code-signed, first run, start at login and uninstalling. Without the app, the
same engine and CLI are one command away:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` serves the panel at `http://127.0.0.1:8765/desktop/panel.html`; to build the
menu-bar app itself, see [`desktop/`](./desktop/README.md). Once the first release is out,
macOS users can also `brew install --cask continuum-ai-corp/tap/orcarouter-lite`.

Today's spend in Claude Code's status bar: add this to `~/.claude/settings.json`.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` prints the week as Markdown (or `--format csv`) to paste into a chat or a sheet.

| Agent | How it connects |
|---|---|
| Claude Code | Automatic: sets `ANTHROPIC_BASE_URL` and a dedicated key in `~/.claude/settings.json` |
| Codex | Automatic: adds an `orca` provider (Responses API) to `~/.codex/config.toml` and selects it with `model = "auto"` |
| Gemini CLI | Automatic: sets `GOOGLE_GEMINI_BASE_URL` and a dedicated key in `~/.gemini/.env`, and Gemini CLI's gateway sign-in in `~/.gemini/settings.json` |
| OpenCode | Automatic: adds an `orca` provider to `~/.config/opencode/opencode.json` and selects `orca/auto`; the key stays in a private file OpenCode reads |
| Command Code | Automatic: adds an `orca` provider to `~/.commandcode/providers.json` whose key comes from a private file (Command Code refuses raw keys there) |
| Cline | One paste step: choose API Provider → OpenAI Compatible in Cline and paste the base URL and key the app shows |
| Aider | Automatic: sets `openai-api-base`, a dedicated key and `model: openai/auto` in `~/.aider.conf.yml` |
| Cursor | One paste step: the app shows a base URL and key for Cursor's model settings |
| Hermes Agent | Automatic: `~/.hermes/config.yaml` (Windows: `%LOCALAPPDATA%\hermes`) → `providers.orca`, `model.provider: custom:orca` |
| Pi | Automatic: `~/.pi/agent/models.json` → `providers.orca`; `settings.json` → `defaultProvider: orca`, `defaultModel: auto` |
| OMP | Automatic: `~/.omp/agent/models.yml` → `providers.orca`; `config.yml` → `modelRoles.default: orca/auto` |
| Kilo Code | Automatic: `~/.config/kilo/kilo.json` → `provider.orca`, `model: orca/auto` (`{file:…}` key) |
| OpenClaw | Automatic: `~/.openclaw/openclaw.json` → `models.providers.orca`, `agents.defaults.model.primary: orca/auto` |
| Kimi Code | Automatic: `~/.kimi-code/config.toml` → `[providers.orca]`, `[models.orca-auto]`, `default_model` |
| Goose | Automatic: `~/.config/goose/custom_providers/orca.json` (`auth.command` key) + `config.yaml` → `GOOSE_PROVIDER: orca` |
| Zed | One paste step: `settings.json` → `language_models.openai_compatible.Orca` (`api_url`, model `auto`) + key in Zed / `ORCA_API_KEY` |
| OpenHands | One paste step: `/settings` → Advanced: model `openai/auto`, base URL, key |
| DeepSeek Harness | One paste step: Settings → Models → custom OpenAI-compatible provider, model `auto` |
| ZCode | One paste step: Add provider → Create custom provider → OpenAI chat completions, model `auto` |

Each connected agent gets its own key: that is how spend is split per agent, and why
disconnecting revokes access at once. What the app may touch on your computer is spelled
out in [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

## Free and open, for good

- **MIT, permanently.** Everything one developer or one team needs stays in this repository under MIT: routing, `model="auto"`, budgets, the dashboard, the desktop app. We won't move a feature from Lite to a paid plan.
- **Paid is for organisations.** Governing many teams (SSO/SCIM, role-based access, fleet-wide budgets and policy, audit retention, alerts to Slack and email) lives in [hosted OrcaRouter](https://www.orcarouter.ai).
- **Verifiable.** Releases are signed and ship with provenance and an SBOM. See [SECURITY.md](./SECURITY.md).

## How it compares

| | Best for | How it runs |
|---|---|---|
| **OrcaRouter Lite** | One developer up to a team that wants spend per agent, budgets and failover without new infrastructure | Desktop app, `uvx`/`pip`, or Docker; SQLite by default |
| LiteLLM proxy | Teams that want a large configuration surface and a Python SDK | Self-hosted server; Postgres for spend tracking |
| OpenRouter | One API key for many models, billed by them | Hosted only; prompts pass through their service |
| Claude Code's own gateway support | Companies that only use Claude | Points Claude Code at a gateway you run; Claude models only |

## Run it as a server (60 seconds)

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

**Account required.** Free models to start; paid models are billed per request on your OrcaRouter account. Hosted handles routing, failover between providers and the long tail of models. See [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

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

## `model="auto"`

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
- **Free models to start** — no provider keys needed; paid models only when you choose them
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

## Native protocol endpoints (Anthropic + Gemini)

Lite speaks three inbound protocols against one routing pipeline. Clients that
only talk Anthropic or Gemini wire formats connect directly — no OpenAI SDK
required:

```bash
# Claude Code, pointed at Lite (no /v1 suffix in the base URL)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK, pointed at Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Requests are translated at the edge into the same internal pipeline, so
`model="auto"`, the cross-provider prompt cache (shared across protocols),
routing strategies, and the analytics dashboard all work identically. Guides:
[integrations/claude-code.md](./integrations/claude-code.md),
[integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Model catalog

100+ chat models are loaded at startup from [LiteLLM's community-maintained pricing database](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — no model list to maintain manually. Each entry exposes:

- `id` (e.g. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapped to your configured keys)
- Capability flags: `supports_tools`, `supports_vision`, `supports_json_mode`
- Per-token input/output cost (drives the savings widget + `model="auto"`)

`GET /v1/models` returns the OpenAI-format catalogue.

## Deploy somewhere else

| Platform | How |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (published from the next tagged release; verify it with the commands in [SECURITY.md](./SECURITY.md)) |
| Render | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Continuum-AI-Corp/OrcaRouter-Lite): uses [`render.yaml`](./render.yaml), generates the secrets, keeps the database on a disk |
| Fly.io | `fly launch --no-deploy`, then the volume and `fly secrets set` steps at the top of [`fly.toml`](./fly.toml), then `fly deploy` |
| Railway | `railway init`, `railway volume add --mount-path /data`, `railway variables --set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) --set API_KEY_PEPPER=$(openssl rand -hex 32) --set DATABASE_URL=sqlite+aiosqlite:////data/orca.db`, then `railway up` (builds with [`railway.json`](./railway.json)) |

## What's in the box

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cross-provider prompt cache
- `POST /v1/messages` — **Anthropic Messages API ingress** (Claude Code / Anthropic SDKs connect directly; `+ /count_tokens`)
- `POST /v1/responses` — **OpenAI Responses API ingress** (Codex and Responses SDK clients; streaming, function and custom tools)
- `POST /v1beta/models/{model}:generateContent` — **Gemini API ingress** (google-genai SDK connects directly; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — discoverable model catalog (100+ models from `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — set / list / revoke encrypted provider keys (`decryptable` flags rows that no longer open after a `CREDENTIAL_ENCRYPTION_KEY` rotation)
- `GET/PUT /v1/routing` — change strategy (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — local analytics, no telemetry leaves the box
- `GET  /v1/hosted` — hosted-gateway status (drives the dashboard's OrcaRouter card)
- `GET/POST/DELETE /v1/keys/...` — list / rotate / revoke API keys
- `/v1/app/*` — agents, spend summary and budget for the desktop app (only when started with `orca up`; see [SECURITY.md](./SECURITY.md))
- Single-page dashboard at `/`
- SQLite by default; Postgres opt-in via `DATABASE_URL`; Redis optional
- Multi-worker safe: set `REDIS_URL` and config changes (provider keys, routing, quality overrides) are invalidated across all workers/replicas via pub/sub. Single worker (the default) needs no Redis.

### Rotating `CREDENTIAL_ENCRYPTION_KEY`

Dashboard-stored provider keys are sealed with AES-256-GCM using `CREDENTIAL_ENCRYPTION_KEY`. Changing that value without a migrate step leaves the ciphertext intact but unreadable: `build_deployments` skips the row, chat returns 503 if nothing else is configured, and the providers list now reports `decryptable: false` instead of a green "Enabled".

To rotate without re-entering every key:

```bash
# 1. Keep the old key, set the new one
CREDENTIAL_ENCRYPTION_KEY=<new 64-hex>
CREDENTIAL_ENCRYPTION_PREVIOUS_KEY=<old 64-hex>

# 2. Restart. Startup re-encrypts stored keys and logs
#    reencrypted_provider_keys / undecryptable_provider_keys.

# 3. Confirm the dashboard shows Enabled, then unset the previous key
#    and restart once more.
```

If you already rotated without `CREDENTIAL_ENCRYPTION_PREVIOUS_KEY`, re-save each provider key in the dashboard (or fall back to env vars). Do not reuse a previous key as the current key after you have already re-saved — that would reseal new ciphertext with the old material.

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

Drop-in configs for [Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts), and any tool that speaks the OpenAI Chat Completions protocol — plus native Anthropic and Gemini wire formats. See [`integrations/`](./integrations/).

## What's deliberately not

This is the **single-workspace** edition. By design, no:
- multi-tenancy, RBAC, SSO
- billing, wallets, points, partner program
- admin console, audit logs, trust & safety
- multi-pod deployment / Kubernetes
- email / Slack / webhooks for alerts

Those are organisation features and live in [hosted OrcaRouter](https://www.orcarouter.ai); see [Free and open, for good](#free-and-open-for-good).

## Testing

Built test-first: every behaviour shipped here had a failing test first.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

desktop/
├── ui/                 Menu-bar panel + setup pages (served by the engine at /desktop/)
├── src-tauri/          Native shell: tray title, notifications, starts the engine
└── engine/             PyInstaller build of the bundled `orca-engine`

packages/
├── desktop/            Agent connectors (backup/restore) + desktop home folder
├── litellm_adapter/    Router wrapper + 100+ model catalog
├── auth/               hashing + AES-256-GCM
└── db/                 models + engine + session
```

## Roadmap

- [x] OpenAI-compatible chat completions, streaming, `model="auto"`
- [x] Anthropic and Gemini native endpoints
- [x] Hosted-as-upstream fallback, encrypted BYOK, local dashboard
- [x] Cross-provider prompt cache
- [x] Desktop app: menu-bar spend, daily budget alerts, one-click agent connect
- [x] Signed releases with provenance and SBOM; hash-locked dependencies
- [x] Daily budget that alerts, or pauses coding agents at the limit
- [x] `orca login` / "Join my company's gateway": use a team's gateway from the app
- [x] `/v1/responses`, so Codex connects; Gemini CLI, OpenCode, Command Code and Cline too
- [x] Encryption key in the OS keychain; one update check a day
- [ ] Per-developer budgets enforced on a shared team gateway
- [ ] Embeddings, Ollama/vLLM providers, custom fallback chains

See [DEMO.md](./DEMO.md) for the failover demo.

## License

MIT. See [LICENSE](./LICENSE).
