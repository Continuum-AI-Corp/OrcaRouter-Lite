#OrcaRouter Lite

**Router LLM self-hosted con rete di sicurezza gestita.**
Compatibile con OpenAI. CIAO OK. Spazio di lavoro singolo. Streaming. `modello="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![test](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![modelli](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![licenza](https://img.shields.io/badge/license-MIT-blue)](#license)

## Lingue

- [Inglese](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Tedesco](./README.de.md)
- [Francese](./README.fr.md)
- [Spagnolo](./README.es.md)
- [Italiano](./README.it.md)
- [Русский](./README.ru.md)
- [Portoghese](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite è l'edizione open source con area di lavoro singola di [OrcaRouter](https://www.orcarouter.ai). Eseguilo sul tuo laptop, inseriscilo nel tuo prodotto o utilizza direttamente `api.orcarouter.ai` ospitato per la lunga coda di modelli per i quali non desideri gestire le chiavi.

> **Perché noi?** LiteLLM è una biblioteca; OpenRouter è ospitato a codice chiuso; Ollama è solo locale. Siamo il **server self-hosted con fallback gestito**: una frase che nessuno di questi può dire.

## Avvio rapido di 60 secondi

Due modi per utilizzare OrcaRouter:

### Percorso A: self-hosted (BYOK)

Esegui Lite sul tuo computer; porta le chiavi del tuo provider.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL di base: "http://localhost:8000/v1". Utilizzare la chiave `sk-orca-*` stampata all'avvio.

### Percorso B: ospitato (account richiesto)

Nessun clone, nessuna finestra mobile. Registrati, ottieni una chiave, punta qualsiasi SDK OpenAI su hosting.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Account richiesto.** Hosted gestisce il routing, la fatturazione e la lunga coda dei fornitori, fatturati per token sul tuo account OrcaRouter. Vedi [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Quindi chiamalo da qualsiasi SDK OpenAI

Gli esempi seguenti utilizzano l'URL di base dell'host locale del percorso A: sostituisci con "https://api.orcarouter.ai/v1" se ti trovi sul percorso B.

<dettagli>
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
</dettagli>

<dettagli>
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
</dettagli>

<dettagli>
<summary><b>arricciatura</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</dettagli>

Apri `http://localhost:8000/` per il dashboard: provider, routing, analisi, chiavi (solo percorso A).

## Perché?

| | Leggero | Libreria LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Server ospitato autonomamente | ✓ | come biblioteca | ✗| ✓ |
| Compatibile con OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-provider (OpenAI/Anthropic/Google/...) | ✓ | ✓ | ✓ | ✗|
| Cruscotto integrato | ✓ | ✗| ✓ | ✗|
| `model="auto"` (capacità più economica) | ✓ | ✗| ✗| n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| Ciaook | ✓ | ✓ | ✗| n/a |
| Ospitato come fallback | ✓ | ✗| n/a | ✗|
| Nessun Postgres/nessun Redis richiesto | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la caratteristica principale

Invia `model="auto"` e OrcaRouter sceglie il modello **più economico** tra i provider configurati che soddisfa i requisiti di capacità della richiesta (strumenti, visione, modalità JSON). Nessuna regola di routing manuale; nessuna ginnastica a ritmo limitato; nessuna ottimizzazione dei costi `if x: ...` nel codice.

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

Il modello risolto viene restituito ai chiamanti tramite l'intestazione di risposta `x-orca-resolved-model` in modo da poter registrare/visualizzare ciò che è stato effettivamente utilizzato.

## Ospitato come upstream (Lite + ospitato)

Utilizzi già Lite? Imposta `ORCAROUTER_API_KEY` sul tuo `sk-orca-*` da [www.orcarouter.ai](https://www.orcarouter.ai) e l'hosted diventa un ulteriore provider nella catena di routing, coprendo modelli che le tue chiavi locali non includono:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casi d'uso:
- **Prova prima dell'acquisto**: non sono necessarie chiavi del fornitore locale
- **Logging locale**: l'hosting gestisce il routing, Lite memorizza le righe RequestLog per il dashboard
- **Failover**: i provider locali falliscono, l'hosting è la rete di sicurezza

## Streaming

Formato SSE compatibile con OpenAI con il framing standard `data: ... \n\n` e un terminale sentinella `[DONE]`: drop-in per qualsiasi SDK che già esegue lo streaming da OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catalogo dei modelli

Oltre 100 modelli di chat vengono caricati all'avvio dal [database dei prezzi gestito dalla community di LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — nessun elenco di modelli da gestire manualmente. Ogni voce espone:

- `id` (ad esempio `gpt-4o`, `claude-3-5-sonnet-latest`)
- "provider" (associato alle chiavi configurate)
- Flag di funzionalità: `supports_tools`, `supports_vision`, `supports_json_mode`
- Costo di input/output per token (guida il widget di risparmio + `model="auto"`)

"GET /v1/models" restituisce il catalogo in formato OpenAI.

## Distribuisci altrove

| Piattaforma | Un clic |
|---|---|
| Ferrovia | [![Distribuisci sulla ferrovia](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Rendering | Connetti repository, root dir = `.` |
| Docker nudo | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (immagine in arrivo) |

## Cosa c'è nella scatola

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache dei prompt tra provider
- `GET /v1/models`: catalogo di modelli rilevabili (oltre 100 modelli da `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}`: imposta/elenca/revoca le chiavi del provider crittografate
- `GET/PUT /v1/routing` — cambia strategia (`bilanciato` / `più economico` / `più veloce` / `qualità`)
- `GET /v1/analytics/{recent,spend,latency, saving,unreachable}`: analisi locale, nessuna telemetria esce dalla scatola
- `GET /v1/hosted`: stato di fallback ospitato (gestisce la carta "Ottieni credito gratuito di $ 5" del dashboard)
- `GET/POST/DELETE /v1/keys/...`: elenca/ruota/revoca le chiavi API
- Dashboard a pagina singola in "/".
- SQLite per impostazione predefinita; Attivazione Postgres tramite `DATABASE_URL`; Redis facoltativo

### Cache dei prompt tra provider

Le richieste deterministiche ("temperatura=0" o "seed" bloccato) vengono servite ripetutamente dalla cache: funziona con **tutti** i provider, non solo con Anthropic. Il backend è Redis quando è impostato "REDIS_URL", altrimenti LRU in-process. I risultati della cache ritornano immediatamente con "x-orca-cache: HIT" e costano $ 0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Widget di risparmio

"GET /v1/analytics/ savings?baseline=gpt-4o&days=7" riporta il costo del tuo traffico su Always-GPT-4 rispetto al costo effettivo. La dashboard lo mostra come un riquadro.

### Integrazioni

Configurazioni drop-in per [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) e qualsiasi strumento che supporti il protocollo OpenAI Chat Completions. Vedi [`integrations/`](./integrations/).

## Cosa deliberatamente no

Questa è l'edizione **con area di lavoro singola**. In base alla progettazione, no:
- multi-tenant, RBAC, SSO
- fatturazione, portafogli, punti, programma partner
- Console di amministrazione, registri di controllo, affidabilità e sicurezza
- Distribuzione multi-pod/Kubernetes
- email/Slack/webhook per avvisi

Per questi, vedere il prodotto ospitato o la (prossima) edizione di Teams.

## Test

Costruito prima di prova. Ogni comportamento spedito qui ha avuto prima un test fallito.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Fetta | Prove | Cosa |
|---|---|---|
| 1. Configurazione | 5| caricamento env, impostazioni predefinite, `env_provider_keys()` |
| 2. Seme | 3| area di lavoro bootstrap + chiave API + RoutingConfig, idempotente |
| 3. Middleware di autenticazione | 4| convalida token al portatore, 401 su mancante/non valido |
| 4. Fabbrica di app | 3| /health, busta di errore, /v1/* gating |
| 5. Chiavi del provider CRUD | 5| crittografato a riposo, il testo in chiaro non fa mai andata e ritorno |
| 6. Cache del router | 13| env+DB+assembly di distribuzione ospitato con precedenza |
| 7. Completamento della chat | 5| Formato OpenAI, RequestLog, convalida |
| 8. Analisi | 4| recente / spesa / latenza p50/p99 |
| 9. /v1/{modelli,chiavi,instradamento} | 8| elenca/crea/revoca + aggiornamento strategia |
| 10. Trasmissione in streaming | 4| Formato SSE, sentinella `[DONE]`, writeback del log |
| 11. Catalogo | 7| Oltre 100 modelli, flag di capacità, prezzi |
| 12. `modello="auto"` | 21| rilevamento delle capacità, soddisfazione delle esigenze più economiche (unità + integrazione) |
| 13. Risparmio sui costi | 9| risparmio rispetto al riferimento sempre GPT-4 + confronto con hosting automatico |
| 14. Cache richiesta | 15| cache di corrispondenza esatta tra provider + integrazione chat |
| 15. Riferimento | 4| summary() + render_markdown() aggregazione |
| 16. Stato ospitato | 7| `/v1/hosted` sorgente-config + superficie URL di registrazione |
| 17. Risparmio Hosted-auto | 3| Casi limite `_hosted_auto_ Savings` su cataloghi sintetici |
| 18. Modelli irraggiungibili | 7| Il riquadro "modelli che non puoi raggiungere" viene cancellato quando l'hosting è attivo |
| **Totale** | **127** | |

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

## Tabella di marcia

- [x] Completamenti chat compatibili con OpenAI
- [x] Streaming (SSE)
- [x] `model="auto"` routing con le capacità più economiche
- [x] Ospitato come upstream
- [x] BYOK crittografato a riposo
- [x] Dashboard di analisi locale
- [x] CI (azioni GitHub)
- [x] Memorizzazione nella cache dei prompt tra provider
- [x] Integrazioni Continue.dev/Aider/LangChain/Cursor/Vercel AI SDK
- [x] Benchmark pubblico + credito di risparmio
- [] Incorporamenti + proxy di generazione di immagini

Vedere [DEMO.md](./DEMO.md) per la demo del failover.

## Licenza

MIT. Vedere [LICENZA](./LICENZA).
