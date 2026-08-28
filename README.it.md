# OrcaRouter Lite

**Router LLM self-hosted con rete di sicurezza gestita.**
Compatibile con OpenAI. BYOK. Workspace singolo. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

![Demo di failover di OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"` assorbe un guasto del provider in tempo reale — senza modifiche al codice. Come registrarlo: [DEMO.md](./DEMO.md).*

## Lingue

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

OrcaRouter Lite è l'edizione open source single-workspace di [OrcaRouter](https://www.orcarouter.ai). Eseguilo sul tuo laptop, integralo nel tuo prodotto, oppure usa direttamente l'`api.orcarouter.ai` ospitato per la long tail di modelli di cui non vuoi gestire le chiavi.

> **Perché noi?** LiteLLM è una libreria; OpenRouter è closed-source e ospitato; Ollama è solo locale. Noi siamo il **server self-hosted con fallback gestito** — una frase che nessuno di loro può dire.

## Quickstart in 60 secondi

Due modi per usare OrcaRouter:

### Strada A — Self-hosted (BYOK)

Esegui Lite sulla tua macchina; porta le tue chiavi provider.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# aggiungi almeno una: OPENAI_API_KEY=sk-...  (o ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Usa la chiave `sk-orca-*` stampata all'avvio.

### Strada B — Hosted (account richiesto)

Niente clone, niente docker. Registrati, ottieni una chiave, punta qualsiasi SDK OpenAI all'hosted.

```bash
# 1. Registrati su https://www.orcarouter.ai e copia la tua chiave sk-orca-*
# 2. Usa https://api.orcarouter.ai/v1 come URL base
```

**Account richiesto.** L'hosted gestisce routing, fatturazione e la long tail di provider — fatturato per token sul tuo account OrcaRouter. Vedi [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Poi chiamalo da qualsiasi SDK OpenAI

Gli esempi qui sotto usano l'URL base localhost della Strada A — sostituisci con `https://api.orcarouter.ai/v1` se sei sulla Strada B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # o "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

Apri `http://localhost:8000/` per la dashboard — provider, routing, analytics, chiavi (solo Strada A).

## Perché?

| | OrcaRouter Lite | Libreria LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Server self-hosted | ✓ | come libreria | ✗ | ✓ |
| Compatibile con OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Dashboard integrata | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (più economico capace) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hosted come fallback | ✓ | ✗ | n/a | ✗ |
| Nessun Postgres / nessun Redis richiesto | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la feature di punta

Invia `model="auto"` e OrcaRouter sceglie il modello **più economico** tra i provider configurati che soddisfa i requisiti di capacità della richiesta (tools, vision, modalità JSON). Niente regole di routing manuali; niente acrobazie con i rate-limit; niente ottimizzazione costo `if x: ...` nel tuo codice.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → instrada al modello più economico VISION-capable coperto dalle tue chiavi
```

Il modello risolto viene esposto a chi chiama tramite l'header di risposta `x-orca-resolved-model`, così puoi loggare/mostrare cosa è stato effettivamente usato.

## Hosted come upstream (Lite + hosted)

Hai già Lite in esecuzione? Imposta `ORCAROUTER_API_KEY` con il tuo `sk-orca-*` di [www.orcarouter.ai](https://www.orcarouter.ai), e l'hosted diventa un provider in più nella catena di routing — coprendo i modelli che le tue chiavi locali non hanno:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casi d'uso:
- **Prova-prima-di-comprare** — nessuna chiave provider locale necessaria
- **Logging locale** — l'hosted gestisce il routing, Lite memorizza le righe RequestLog per la dashboard
- **Failover** — i provider locali falliscono, l'hosted è la rete di sicurezza

## Streaming

Formato SSE compatibile OpenAI con il framing standard `data: ... \n\n` e un sentinel terminale `[DONE]` — drop-in per qualsiasi SDK che già fa streaming da OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Endpoint di protocollo nativi (Anthropic + Gemini)

Lite parla tre protocolli in ingresso su un'unica pipeline di routing. I client che parlano solo i formati wire di Anthropic o Gemini si connettono direttamente — nessun SDK OpenAI richiesto:

```bash
# Claude Code, puntato su Lite (nessun suffisso /v1 nell'URL base)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# SDK google-genai, puntato su Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Le richieste vengono tradotte all'ingresso nella stessa pipeline interna, quindi `model="auto"`, la cache prompt cross-provider (condivisa tra i protocolli), le strategie di routing e la dashboard analytics funzionano tutti in modo identico. Guide: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Catalogo modelli

Oltre 100 modelli di chat vengono caricati all'avvio dal [database di prezzi mantenuto dalla community di LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — nessuna lista di modelli da mantenere a mano. Ogni voce espone:

- `id` (es. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mappato sulle tue chiavi configurate)
- Flag di capacità: `supports_tools`, `supports_vision`, `supports_json_mode`
- Costo per token input/output (alimenta il widget risparmi + `model="auto"`)

`GET /v1/models` restituisce il catalogo nel formato OpenAI.

## Deploy altrove

| Piattaforma | One-click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Collega il repo, root dir = `.` |
| Docker nudo | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (immagine in arrivo) |

## Cosa c'è nella scatola

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache prompt cross-provider
- `POST /v1/messages` — **ingress dell'API Messages di Anthropic** (Claude Code / gli SDK Anthropic si connettono direttamente; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **ingress dell'API Gemini** (l'SDK google-genai si connette direttamente; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — catalogo modelli scopribile (100+ modelli da `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — imposta / lista / revoca chiavi provider cifrate
- `GET/PUT /v1/routing` — cambia strategia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics locali, nessuna telemetria esce dalla scatola
- `GET  /v1/hosted` — stato del fallback hosted (alimenta la card "Get $5 free credit" della dashboard)
- `GET/POST/DELETE /v1/keys/...` — lista / ruota / revoca chiavi API
- Dashboard single-page su `/`
- SQLite di default; Postgres opt-in via `DATABASE_URL`; Redis opzionale

### Cache prompt cross-provider

Le richieste deterministiche (`temperature=0` o `seed` fissato) vengono servite dalla cache alle ripetizioni — funziona su **ogni** provider, non solo Anthropic. Il backend è Redis se `REDIS_URL` è impostato, altrimenti un LRU in-process. Gli hit della cache tornano istantaneamente con `x-orca-cache: HIT` e costano $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # stesso payload di nuovo
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servito dalla cache, nessuna chiamata upstream
```

### Widget risparmi

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` riporta quanto sarebbe costato il tuo traffico con sempre-GPT-4 rispetto a quanto è effettivamente costato. La dashboard lo mostra come tile.

### Integrazioni

Configurazioni drop-in per [Claude Code](./integrations/claude-code.md), [SDK Gemini](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) e qualsiasi tool che parli il protocollo OpenAI Chat Completions — più i formati wire nativi di Anthropic e Gemini. Vedi [`integrations/`](./integrations/).

## Cosa volutamente non c'è

Questa è l'edizione **single-workspace**. Per design, niente:
- multi-tenancy, RBAC, SSO
- fatturazione, wallet, punti, programma partner
- console di amministrazione, log di audit, trust & safety
- deploy multi-pod / Kubernetes
- email / Slack / webhook per gli alert

Per quelli, vedi il prodotto hosted o la (futura) edizione Teams.

## Testing

Costruito test-first. Ogni comportamento spedito qui ha avuto prima un test che falliva.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| Slice | Test | Cosa |
|---|---|---|
| 1. Config | 5 | caricamento env, default, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + chiave API + RoutingConfig, idempotente |
| 3. Middleware di auth | 4 | validazione bearer-token, 401 su mancante/invalido |
| 4. App factory | 3 | /health, error envelope, gating /v1/* |
| 5. CRUD chiavi provider | 5 | cifrato a riposo, il plaintext non fa mai andata-ritorno |
| 6. Cache router | 13 | assemblaggio deployment env+DB+hosted con precedenza |
| 7. Chat completion | 5 | formato OpenAI, RequestLog, validazione |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + aggiornamento strategia |
| 10. Streaming | 4 | formato SSE, sentinel `[DONE]`, log writeback |
| 11. Catalogo | 7 | 100+ modelli, flag di capacità, pricing |
| 12. `model="auto"` | 21 | rilevamento capacità, più-economico-che-soddisfa-i-bisogni (unit + integrazione) |
| 13. Risparmio costi | 9 | risparmi vs baseline sempre-GPT-4 + confronto hosted-auto |
| 14. Cache prompt | 15 | cache exact-match cross-provider + integrazione chat |
| 15. Benchmark | 4 | aggregazione summarize() + render_markdown() |
| 16. Stato hosted | 7 | `/v1/hosted` config-source + superficie URL di signup |
| 17. Risparmi hosted-auto | 3 | edge case di `_hosted_auto_savings` su cataloghi sintetici |
| 18. Modelli irraggiungibili | 7 | la tile "modelli che non puoi raggiungere" si svuota quando hosted è attivo |
| 19. Auth multi-protocollo | 6 | scoping x-api-key / x-goog-api-key / ?key=, guard /v1beta, envelope 401 per protocollo |
| 20. Anthropic `/v1/messages` | 53 | traduzione richiesta/risposta/stream + integrazione ingress |
| 21. Gemini `/v1beta` | 40 | traduzione incl. normalizzazione schema-enum + ingress generateContent/stream |
| **Totale** | **403** | |

Le righe degli slice mostrano i test aggiunti quando ogni slice è stato spedito; il totale è la suite completa attuale.

## Architettura

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

- [x] Chat completions compatibili OpenAI
- [x] Streaming (SSE)
- [x] Routing `model="auto"` più-economico-capace
- [x] Hosted-come-upstream
- [x] BYOK cifrato a riposo
- [x] Dashboard analytics locale
- [x] CI (GitHub Actions)
- [x] Caching prompt cross-provider
- [x] Integrazioni Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark pubblico + claim sui risparmi
- [ ] Proxy embeddings + image-gen

Vedi [DEMO.md](./DEMO.md) per la demo di failover.

## Licenza

MIT. Vedi [LICENSE](./LICENSE).
