# OrcaRouter Lite

**Metti un budget a ogni agente di coding.**
Vedi e limita quanto spendono Claude Code, Aider, Cursor e le tue app, su tutti i provider di
modelli, senza che i tuoi prompt lascino la tua macchina. Un'app nella barra dei menu per il singolo
sviluppatore e un router self-hosted per un intero team. Licenza MIT.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="Il pannello di OrcaRouter Lite nella barra dei menu: spesa di oggi rispetto a un budget giornaliero, agenti di coding connessi e stato dei provider" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Configurazione iniziale: agenti di coding rilevati, dove vanno le richieste e un budget giornaliero" width="420">
</p>

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

**Dove trovarci:** [Tutte le API dei modelli](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite è l'edizione open source di [OrcaRouter](https://www.orcarouter.ai). Gira sul tuo computer o sul tuo server, parla le API di OpenAI, Anthropic e Gemini, e può usare l'`api.orcarouter.ai` ospitato come rete di sicurezza in caso di guasti e per i modelli di cui non hai le chiavi.

## L'app desktop

L'app Orca vive nella tua barra dei menu. Esegue il router su `127.0.0.1`, vi collega i tuoi agenti
di coding e mostra quanto spendono.

- **Spesa di oggi, per agente.** Il totale di oggi compare accanto all'orologio; il pannello lo suddivide per agente, e ogni lunedì una notifica riassume la settimana.
- **Un budget giornaliero.** Notifiche all'80% e al 100% dell'importo che imposti. Per impostazione predefinita solo avvisi; spunta una casella e Orca mette in pausa i tuoi agenti di coding una volta raggiunto l'importo.
- **Connessione con un clic.** Orca modifica le impostazioni dell'agente stesso, ne conserva un backup e lo ripristina quando lo disconnetti.
- **Mai giù.** Quando un provider va in errore o ti applica un rate-limit, le richieste ripiegano su un altro provider o su OrcaRouter hosted, e l'app conta quante ne ha salvate. Collega il tuo account con `orca link --key sk-orca-…` o dalla configurazione iniziale.
- **Privata per impostazione predefinita.** I prompt vanno direttamente dai tuoi agenti al provider che scegli. Nessuna telemetria.
- **Funziona con il gateway del tuo team.** `orca login https://ai-gw.example.com --key …` (o "Join my company's gateway" nella configurazione iniziale) indirizza i tuoi agenti al gateway gestito dal tuo team di piattaforma; `orca logout` li ripristina.

**Installazione.** Gli installer (`.dmg`, `.deb`, `.AppImage`, `.msi`) vengono generati da
[`desktop.yml`](./.github/workflows/desktop.yml) e allegati a ogni release, a partire dalla
prossima versione taggata. Fino ad allora, lo stesso motore e la stessa CLI sono a un comando di distanza:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` serve il pannello su `http://127.0.0.1:8765/desktop/panel.html`; per compilare l'app
per la barra dei menu, vedi [`desktop/`](./desktop/README.md). Dopo l'uscita della prima release,
gli utenti di Mac con Apple silicon potranno anche usare `brew install --cask continuum-ai-corp/tap/orcarouter-lite`.

La spesa di oggi nella barra di stato di Claude Code: aggiungi questo a `~/.claude/settings.json`.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` stampa la settimana in Markdown (o `--format csv`) da incollare in una chat o in un foglio di calcolo.

| Agente | Come si connette |
|---|---|
| Claude Code | Automatico: imposta `ANTHROPIC_BASE_URL` e una chiave dedicata in `~/.claude/settings.json` |
| Aider | Automatico: imposta `openai-api-base`, una chiave dedicata e `model: openai/auto` in `~/.aider.conf.yml` |
| Cursor | Un passaggio di copia e incolla: l'app mostra un URL base e una chiave per le impostazioni dei modelli di Cursor |
| Codex | In arrivo: richiede la Responses API di OpenAI (`/v1/responses`), che Lite non serve ancora |
| Gemini CLI | In arrivo |

Ogni agente connesso riceve la propria chiave: è così che la spesa viene suddivisa per agente, ed è
per questo che disconnetterlo revoca subito l'accesso. Cosa può toccare l'app sul tuo computer è
spiegato in dettaglio in [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

<a id="free-and-open-for-good"></a>

## Libero e aperto, per sempre

- **MIT, in modo permanente.** Tutto ciò che serve a uno sviluppatore o a un team resta in questo repository sotto MIT: routing, `model="auto"`, budget, la dashboard, l'app desktop. Non sposteremo nessuna feature da Lite a un piano a pagamento.
- **Il piano a pagamento è per le organizzazioni.** La governance di molti team (SSO/SCIM, accesso basato sui ruoli, budget e policy per l'intera flotta, conservazione degli audit log, alert su Slack e via email) si trova in [OrcaRouter hosted](https://www.orcarouter.ai).
- **Verificabile.** Le release sono firmate e distribuite con provenance e un SBOM. Vedi [SECURITY.md](./SECURITY.md).

## Come si confronta

| | Ideale per | Come gira |
|---|---|---|
| **OrcaRouter Lite** | Dal singolo sviluppatore a un team che vuole spesa per agente, budget e failover senza nuova infrastruttura | App desktop, `uvx`/`pip` o Docker; SQLite di default |
| Proxy LiteLLM | Team che vogliono un'ampia superficie di configurazione e un SDK Python | Server self-hosted; Postgres per il tracciamento della spesa |
| OpenRouter | Una sola chiave API per molti modelli, fatturati da OpenRouter | Solo hosted; i prompt passano dal loro servizio |
| Il supporto gateway nativo di Claude Code | Aziende che usano solo Claude | Punta Claude Code a un gateway gestito da te; solo modelli Claude |

## Eseguilo come server (60 secondi)

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

## `model="auto"`

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

| Piattaforma | Come |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (pubblicata a partire dalla prossima release taggata; verificala con i comandi in [SECURITY.md](./SECURITY.md)) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Collega il repo, root dir = `.` |
| Railway | Template in arrivo (tracciato in #181) |

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
- `/v1/app/*` — agenti, riepilogo della spesa e budget per l'app desktop (solo se avviato con `orca up`; vedi [SECURITY.md](./SECURITY.md))
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

Sono funzionalità per le organizzazioni e si trovano in [OrcaRouter hosted](https://www.orcarouter.ai); vedi [Libero e aperto, per sempre](#free-and-open-for-good).

## Testing

Costruito test-first: ogni comportamento spedito qui ha avuto prima un test che falliva.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

- [x] Chat completions compatibili OpenAI, streaming, `model="auto"`
- [x] Endpoint nativi Anthropic e Gemini
- [x] Fallback hosted-come-upstream, BYOK cifrato, dashboard locale
- [x] Cache prompt cross-provider
- [x] App desktop: spesa nella barra dei menu, alert sul budget giornaliero, connessione degli agenti con un clic
- [x] Release firmate con provenance e SBOM; dipendenze bloccate tramite hash
- [x] Budget giornaliero che avvisa, o mette in pausa gli agenti di coding al limite
- [x] `orca login` / "Join my company's gateway": usare il gateway di un team dall'app
- [ ] `/v1/responses` così Codex può connettersi
- [ ] Budget per sviluppatore applicati su un gateway di team condiviso
- [ ] Embeddings, provider Ollama/vLLM, catene di fallback personalizzate

Vedi [DEMO.md](./DEMO.md) per la demo di failover.

<a id="license"></a>

## Licenza

MIT. Vedi [LICENSE](./LICENSE).
