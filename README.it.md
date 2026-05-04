# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | [日本語](./README.ja.md) | [한국어](./README.ko.md) | [Deutsch](./README.de.md) | **Italiano** | [Français](./README.fr.md) | [Español](./README.es.md) | [العربية](./README.ar.md)

**Router LLM auto-ospitato con rete di sicurezza gestita.**
Compatibile con OpenAI. BYOK. Workspace singolo. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#test)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#catalogo-modelli)
[![license](https://img.shields.io/badge/license-MIT-blue)](#licenza)

OrcaRouter Lite è l'edizione open-source single-workspace di [OrcaRouter](https://www.orcarouter.ai). Eseguilo sul tuo laptop, integralo nel tuo prodotto o usa direttamente l'`api.orcarouter.ai` ospitato per la coda lunga di modelli per cui non vuoi gestire le chiavi.

> **Perché noi?** LiteLLM è una libreria; OpenRouter è ospitato closed-source; Ollama è solo locale. Noi siamo il **server auto-ospitato con fallback gestito** — una frase che nessuno di loro può dire.

## Avvio rapido in 60 secondi

Due modi per usare OrcaRouter:

### Percorso A — Auto-ospitato (BYOK)

Esegui Lite sulla tua macchina; porta le tue chiavi provider.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# aggiungi almeno una: OPENAI_API_KEY=sk-...  (o ORCAROUTER_API_KEY=...)

docker compose up
# log: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Usa la chiave `sk-orca-*` stampata all'avvio.

### Percorso B — Ospitato (account richiesto)

Niente clone, niente docker. Registrati, ottieni una chiave, punta qualsiasi SDK OpenAI a ospitato.

```bash
# 1. Registrati su https://www.orcarouter.ai e copia la tua chiave sk-orca-*
# 2. Usa https://api.orcarouter.ai/v1 come URL base
```

**Account richiesto.** Ospitato gestisce routing, fatturazione e la coda lunga di provider — fatturato per token sul tuo account OrcaRouter. Vedi [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Poi chiamalo da qualsiasi SDK OpenAI

Gli esempi sotto usano l'URL base localhost del Percorso A — sostituisci con `https://api.orcarouter.ai/v1` se sei sul Percorso B.

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
    messages=[{"role": "user", "content": "Ciao!"}],
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
  messages: [{ role: "user", content: "Ciao!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"Ciao!"}]}'
```
</details>

Apri `http://localhost:8000/` per la dashboard — provider, routing, analisi, chiavi (solo Percorso A).

## Perché?

| | Lite | Libreria LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Server auto-ospitato | ✓ | come libreria | ✗ | ✓ |
| Compatibile con OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Dashboard integrata | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (più economico capace) | ✓ | ✗ | ✗ | n/d |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/d |
| Ospitato come fallback | ✓ | ✗ | n/d | ✗ |
| Niente Postgres / niente Redis richiesti | ✓ | n/d | n/d | ✓ |

## `model="auto"` — la funzione di punta

Invia `model="auto"` e OrcaRouter sceglie il modello **più economico** tra i provider configurati che soddisfa i requisiti di capacità della richiesta (strumenti, visione, modalità JSON). Nessuna regola di routing manuale; nessuna ginnastica di rate-limit; nessuna ottimizzazione dei costi `if x: ...` nel tuo codice.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "Cosa c'è in questa immagine?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → instrada al modello VISION-capable più economico coperto dalle tue chiavi
```

Il modello risolto viene esposto ai chiamanti tramite l'header di risposta `x-orca-resolved-model` così puoi loggare/visualizzare cosa è stato effettivamente usato.

## Ospitato come upstream (Lite + ospitato)

Stai già eseguendo Lite? Imposta `ORCAROUTER_API_KEY` sulla tua `sk-orca-*` da [www.orcarouter.ai](https://www.orcarouter.ai), e ospitato diventa un altro provider nella catena di routing — coprendo modelli che le tue chiavi locali non coprono:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casi d'uso:
- **Try-before-you-buy** — nessuna chiave provider locale necessaria
- **Logging locale** — ospitato gestisce il routing, Lite memorizza righe RequestLog per la dashboard
- **Failover** — i provider locali falliscono, ospitato è la rete di sicurezza

## Streaming

Formato SSE compatibile con OpenAI con il framing standard `data: ... \n\n` e un sentinel terminale `[DONE]` — drop-in per qualsiasi SDK che già fa streaming da OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Raccontami una storia"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catalogo modelli

100+ modelli di chat sono caricati all'avvio dal [database di prezzi mantenuto dalla community di LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — nessuna lista di modelli da mantenere manualmente. Ogni voce espone:

- `id` (es. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mappato alle tue chiavi configurate)
- Flag di capacità: `supports_tools`, `supports_vision`, `supports_json_mode`
- Costo input/output per token (alimenta il widget di risparmio + `model="auto"`)

`GET /v1/models` restituisce il catalogo nel formato OpenAI.

## Distribuisci altrove

| Piattaforma | Un clic |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Connetti repository, dir radice = `.` |
| Docker nudo | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (immagine in arrivo) |

## Cosa c'è nella scatola

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache prompt cross-provider
- `GET  /v1/models` — catalogo modelli scopribile (100+ modelli da `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — imposta / elenca / revoca chiavi provider crittografate
- `GET/PUT /v1/routing` — cambia strategia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analisi locali, nessuna telemetria lascia la scatola
- `GET  /v1/hosted` — stato fallback ospitato (alimenta la card "Ottieni $5 di credito gratuito" della dashboard)
- `GET/POST/DELETE /v1/keys/...` — elenca / ruota / revoca chiavi API
- Dashboard single-page su `/`
- SQLite per default; Postgres opt-in tramite `DATABASE_URL`; Redis opzionale

### Cache prompt cross-provider

Le richieste deterministiche (`temperature=0` o `seed` fissato) vengono servite dalla cache alla ripetizione — funziona su **ogni** provider, non solo Anthropic. Il backend è Redis quando `REDIS_URL` è impostato, altrimenti LRU in-process. Gli hit cache restituiscono immediatamente con `x-orca-cache: HIT` e costano $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # stesso payload di nuovo
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servito dalla cache, nessuna chiamata upstream
```

### Widget di risparmio

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` riporta quanto sarebbe costato il tuo traffico su sempre-GPT-4 vs quanto è effettivamente costato. La dashboard lo mostra come una piastrella.

### Integrazioni

Configurazioni drop-in per [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts), e qualsiasi strumento che parla il protocollo OpenAI Chat Completions. Vedi [`integrations/`](./integrations/).

## Cosa deliberatamente non c'è

Questa è l'edizione **single-workspace**. Per design, niente:
- multi-tenancy, RBAC, SSO
- fatturazione, wallet, punti, programma partner
- console admin, audit log, trust & safety
- deployment multi-pod / Kubernetes
- email / Slack / webhook per gli avvisi

Per quelli, vedi il prodotto ospitato o l'edizione Teams (in arrivo).

## Test

Costruito test-first. Ogni comportamento spedito qui aveva prima un test che falliva.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Slice | Test | Cosa |
|---|---|---|
| 1. Configurazione | 5 | caricamento env, default, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + chiave API + RoutingConfig, idempotente |
| 3. Middleware Auth | 4 | validazione bearer-token, 401 su mancante/non valido |
| 4. App factory | 3 | /health, busta errore, gating /v1/* |
| 5. CRUD chiavi provider | 5 | crittografato a riposo, plaintext non fa mai round-trip |
| 6. Cache router | 13 | assemblaggio deployment env+DB+ospitato con precedenza |
| 7. Chat completion | 5 | formato OpenAI, RequestLog, validazione |
| 8. Analisi | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | elenca/crea/revoca + aggiornamento strategia |
| 10. Streaming | 4 | formato SSE, sentinel `[DONE]`, riscrittura log |
| 11. Catalogo | 7 | 100+ modelli, flag di capacità, prezzi |
| 12. `model="auto"` | 21 | rilevamento capacità, più economico-che-soddisfa-bisogni (unit + integrazione) |
| 13. Risparmi sui costi | 9 | risparmi vs baseline sempre-GPT-4 + confronto ospitato-auto |
| 14. Cache prompt | 15 | cache cross-provider exact-match + integrazione chat |
| 15. Benchmark | 4 | aggregazione summarize() + render_markdown() |
| 16. Stato ospitato | 7 | `/v1/hosted` config-source + superficie URL signup |
| 17. Risparmi auto ospitato | 3 | edge case `_hosted_auto_savings` su cataloghi sintetici |
| 18. Modelli irraggiungibili | 7 | la piastrella "modelli che non puoi raggiungere" si svuota quando ospitato è attivo |
| **Totale** | **127** | |

## Architettura

```
app/
├── main.py             Factory FastAPI + lifespan + mount SPA
├── config.py           Impostazioni (~15 campi)
├── deps.py             Helper DI
├── seed.py             Bootstrap primo avvio
├── auto_routing.py     Capacità model="auto" + scoring costi
├── router_cache.py     Router single-workspace
├── prompt_cache.py     Cache cross-provider exact-match (Redis o LRU in-memory)
├── schemas.py          Schema richiesta compatibile OpenAI
├── middleware/auth.py  Validazione sk-orca-*
└── routes/
    ├── chat.py         /v1/chat/completions  (blocking + streaming)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      Configurazione strategia
    ├── analytics.py    Recent / spend / latency / savings / unreachable
    ├── keys.py         Elenca / ruota / revoca chiavi API
    ├── hosted.py       /v1/hosted — stato fallback ospitato per la dashboard
    └── health.py

packages/
├── litellm_adapter/    Wrapper router + catalogo 100+ modelli
├── auth/               Hashing + AES-256-GCM
└── db/                 Modelli + engine + sessione
```

## Roadmap

- [x] Chat completions compatibili OpenAI
- [x] Streaming (SSE)
- [x] Routing `model="auto"` più-economico-capace
- [x] Ospitato come upstream
- [x] BYOK crittografato a riposo
- [x] Dashboard analisi locale
- [x] CI (GitHub Actions)
- [x] Caching prompt cross-provider
- [x] Integrazioni Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark pubblico + claim sui risparmi
- [ ] Embedding + proxy generazione immagini

Vedi [DEMO.md](./DEMO.md) per la demo failover.

## Licenza

MIT. Vedi [LICENSE](./LICENSE).
