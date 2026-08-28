# OrcaRouter Lite

**Selbst gehosteter LLM-Router mit verwaltetem Sicherheitsnetz.**
OpenAI-kompatibel. BYOK. Einzelner Workspace. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

![OrcaRouter Lite Failover-Demo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"` fängt einen Provider-Ausfall in Echtzeit ab — ohne Codeänderung. Aufnahme-Anleitung: [DEMO.md](./DEMO.md).*

## Sprachen

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

OrcaRouter Lite ist die Open-Source-Edition für einen einzelnen Workspace von [OrcaRouter](https://www.orcarouter.ai). Führen Sie es auf Ihrem Laptop aus, liefern Sie es in Ihrem Produkt aus oder nutzen Sie das gehostete `api.orcarouter.ai` direkt für die Long-Tail-Modelle, deren Schlüssel Sie nicht selbst verwalten möchten.

> **Warum wir?** LiteLLM ist eine Bibliothek; OpenRouter ist Closed-Source und gehostet; Ollama ist nur lokal. Wir sind der **selbst gehostete Server mit verwaltetem Fallback** — ein Satz, den keiner der anderen sagen kann.

## 60-Sekunden-Schnellstart

Zwei Möglichkeiten, OrcaRouter zu nutzen:

### Pfad A — Selbst gehostet (BYOK)

Führen Sie Lite auf Ihrem eigenen Rechner aus; bringen Sie Ihre eigenen Provider-Schlüssel mit.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# mindestens einen hinzufügen: OPENAI_API_KEY=sk-...  (oder ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Basis-URL: `http://localhost:8000/v1`. Verwenden Sie den beim Start ausgegebenen `sk-orca-*`-Schlüssel.

### Pfad B — Gehostet (Konto erforderlich)

Kein Klonen, kein Docker. Registrieren, Schlüssel holen, jedes OpenAI-SDK auf den Hosted-Endpunkt zeigen.

```bash
# 1. Registrieren auf https://www.orcarouter.ai und sk-orca-* Schlüssel kopieren
# 2. https://api.orcarouter.ai/v1 als Basis-URL verwenden
```

**Konto erforderlich.** Hosted übernimmt Routing, Abrechnung und den Long Tail an Providern — pro Token über Ihr OrcaRouter-Konto abgerechnet. Siehe [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Dann von einem beliebigen OpenAI-SDK aufrufen

Die folgenden Beispiele verwenden die localhost-Basis-URL aus Pfad A — tauschen Sie sie gegen `https://api.orcarouter.ai/v1`, wenn Sie Pfad B nutzen.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # oder "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

Öffnen Sie `http://localhost:8000/` für das Dashboard — Provider, Routing, Analytics, Schlüssel (nur Pfad A).

## Warum?

| | OrcaRouter Lite | LiteLLM-Bibliothek | OpenRouter | Ollama |
|---|---|---|---|---|
| Selbst gehosteter Server | ✓ | als Bibliothek | ✗ | ✓ |
| OpenAI-kompatibel | ✓ | ✓ | ✓ | ✓ |
| Multi-Provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Eingebautes Dashboard | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (günstigstes geeignetes) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hosted als Fallback | ✓ | ✗ | n/a | ✗ |
| Kein Postgres / kein Redis erforderlich | ✓ | n/a | n/a | ✓ |

## `model="auto"` — das Hauptmerkmal

Senden Sie `model="auto"`, und OrcaRouter wählt das **günstigste** Modell aus Ihren konfigurierten Providern, das die Anforderungsfähigkeiten der Anfrage erfüllt (Tools, Vision, JSON-Modus). Keine manuellen Routing-Regeln; keine Rate-Limit-Akrobatik; keine `if x: ...`-Kostenoptimierung in Ihrem Code.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → leitet an das günstigste VISION-fähige Modell, das Ihre Schlüssel abdecken
```

Das aufgelöste Modell wird dem Aufrufer über den Antwort-Header `x-orca-resolved-model` zurückgegeben, sodass Sie protokollieren/anzeigen können, was tatsächlich verwendet wurde.

## Hosted als Upstream (Lite + Hosted)

Lite läuft schon? Setzen Sie `ORCAROUTER_API_KEY` auf Ihren `sk-orca-*` von [www.orcarouter.ai](https://www.orcarouter.ai), und Hosted wird zu einem weiteren Provider in der Routing-Kette — und deckt Modelle ab, die Ihre lokalen Schlüssel nicht haben:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Anwendungsfälle:
- **Vor dem Kauf testen** — keine lokalen Provider-Schlüssel nötig
- **Lokales Logging** — Hosted erledigt Routing, Lite speichert RequestLog-Zeilen für das Dashboard
- **Failover** — lokale Provider fallen aus, Hosted ist das Sicherheitsnetz

## Streaming

OpenAI-kompatibles SSE-Format mit dem üblichen `data: ... \n\n`-Framing und einem abschließenden `[DONE]`-Sentinel — Drop-in für jedes SDK, das bereits von OpenAI streamt.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Native Protokoll-Endpunkte (Anthropic + Gemini)

Lite spricht drei eingehende Protokolle über eine einzige Routing-Pipeline. Clients, die nur die Anthropic- oder Gemini-Wire-Formate sprechen, verbinden sich direkt — kein OpenAI-SDK erforderlich:

```bash
# Claude Code, auf Lite gerichtet (kein /v1-Suffix in der Basis-URL)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai-SDK, auf Lite gerichtet
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Anfragen werden am Eingang in dieselbe interne Pipeline übersetzt, sodass `model="auto"`, der provider-übergreifende Prompt-Cache (über alle Protokolle geteilt), die Routing-Strategien und das Analytics-Dashboard identisch funktionieren. Anleitungen: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Modellkatalog

Beim Start werden über 100 Chat-Modelle aus [LiteLLMs von der Community gepflegter Preisdatenbank](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) geladen — keine Modellliste, die manuell gepflegt werden muss. Jeder Eintrag enthält:

- `id` (z. B. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (auf Ihre konfigurierten Schlüssel abgebildet)
- Capability-Flags: `supports_tools`, `supports_vision`, `supports_json_mode`
- Kosten pro Token für Input/Output (treibt das Einsparungs-Widget + `model="auto"` an)

`GET /v1/models` liefert den Katalog im OpenAI-Format zurück.

## Anderswo deployen

| Plattform | One-Click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Repo verbinden, Root-Verzeichnis = `.` |
| Bare Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (Image folgt) |

## Was ist enthalten

- `POST /v1/chat/completions` — Proxy + Streaming + `model="auto"` + provider-übergreifender Prompt-Cache
- `POST /v1/messages` — **Anthropic-Messages-API-Ingress** (Claude Code / Anthropic-SDKs verbinden sich direkt; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **Gemini-API-Ingress** (google-genai-SDK verbindet sich direkt; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — auffindbarer Modellkatalog (100+ Modelle aus `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — verschlüsselte Provider-Schlüssel setzen / auflisten / widerrufen
- `GET/PUT /v1/routing` — Strategie ändern (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — lokale Analytics, keine Telemetrie verlässt die Box
- `GET  /v1/hosted` — Status des Hosted-Fallbacks (treibt die "Get $5 free credit"-Karte des Dashboards an)
- `GET/POST/DELETE /v1/keys/...` — API-Schlüssel auflisten / rotieren / widerrufen
- Single-Page-Dashboard unter `/`
- Standardmäßig SQLite; Postgres optional via `DATABASE_URL`; Redis optional

### Provider-übergreifender Prompt-Cache

Deterministische Anfragen (`temperature=0` oder fest gepinnter `seed`) werden bei Wiederholung aus dem Cache bedient — funktioniert bei **jedem** Provider, nicht nur bei Anthropic. Backend ist Redis, wenn `REDIS_URL` gesetzt ist, ansonsten ein In-Process-LRU. Cache-Treffer kommen sofort mit `x-orca-cache: HIT` zurück und kosten 0 $.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # gleicher Payload erneut
HTTP/1.1 200 OK
x-orca-cache: HIT          ← aus dem Cache, kein Upstream-Aufruf
```

### Einsparungs-Widget

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` zeigt, was Ihr Traffic mit immer-GPT-4 gekostet hätte gegenüber dem, was er tatsächlich gekostet hat. Das Dashboard zeigt das als Kachel an.

### Integrationen

Drop-in-Konfigurationen für [Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) und jedes Tool, das das OpenAI-Chat-Completions-Protokoll spricht — plus native Anthropic- und Gemini-Wire-Formate. Siehe [`integrations/`](./integrations/).

## Was bewusst nicht enthalten ist

Dies ist die **Single-Workspace**-Edition. Per Design ohne:
- Mandantenfähigkeit, RBAC, SSO
- Abrechnung, Wallets, Punkte, Partnerprogramm
- Admin-Konsole, Audit-Logs, Trust & Safety
- Multi-Pod-Deployment / Kubernetes
- E-Mail / Slack / Webhooks für Alerts

Dafür siehe das gehostete Produkt oder die (kommende) Teams-Edition.

## Testen

Test-First entwickelt. Jedes hier ausgelieferte Verhalten hatte zuerst einen fehlschlagenden Test.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| Slice | Tests | Was |
|---|---|---|
| 1. Config | 5 | env-Loading, Defaults, `env_provider_keys()` |
| 2. Seed | 3 | Bootstrap-Workspace + API-Schlüssel + RoutingConfig, idempotent |
| 3. Auth-Middleware | 4 | Bearer-Token-Validierung, 401 bei fehlend/ungültig |
| 4. App-Factory | 3 | /health, Error-Envelope, /v1/*-Gating |
| 5. Provider-Schlüssel CRUD | 5 | im Speicher verschlüsselt, Klartext geht nie hin und zurück |
| 6. Router-Cache | 13 | env+DB+hosted Deployment-Assembly mit Präzedenz |
| 7. Chat Completion | 5 | OpenAI-Format, RequestLog, Validierung |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + Strategie-Update |
| 10. Streaming | 4 | SSE-Format, `[DONE]`-Sentinel, Log-Writeback |
| 11. Katalog | 7 | 100+ Modelle, Capability-Flags, Pricing |
| 12. `model="auto"` | 21 | Capability-Erkennung, günstigstes-mit-passenden-Anforderungen (Unit + Integration) |
| 13. Kosteneinsparungen | 9 | Einsparungen vs. Always-GPT-4-Baseline + Hosted-Auto-Vergleich |
| 14. Prompt-Cache | 15 | provider-übergreifender Exact-Match-Cache + Chat-Integration |
| 15. Benchmark | 4 | summarize() + render_markdown()-Aggregation |
| 16. Hosted-Status | 7 | `/v1/hosted` Config-Source + Signup-URL-Surface |
| 17. Hosted-Auto-Einsparungen | 3 | `_hosted_auto_savings`-Edge-Cases auf synthetischen Katalogen |
| 18. Unerreichbare Modelle | 7 | "Modelle, die du nicht erreichen kannst"-Kachel verschwindet, wenn Hosted aktiv ist |
| 19. Multi-Protokoll-Auth | 6 | Scoping von x-api-key / x-goog-api-key / ?key=, /v1beta-Guard, 401-Envelopes pro Protokoll |
| 20. Anthropic `/v1/messages` | 53 | Request-/Response-/Stream-Übersetzung + Ingress-Integration |
| 21. Gemini `/v1beta` | 40 | Übersetzung inkl. Schema-Enum-Normalisierung + generateContent/Stream-Ingress |
| **Gesamt** | **403** | |

Die Slice-Zeilen zeigen die Tests, die beim Ausliefern des jeweiligen Slices hinzukamen; die Gesamtzahl ist die aktuelle vollständige Suite.

## Architektur

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

- [x] OpenAI-kompatible Chat-Completions
- [x] Streaming (SSE)
- [x] `model="auto"` günstigstes-geeignetes Routing
- [x] Hosted-als-Upstream
- [x] Verschlüsseltes BYOK im Speicher
- [x] Lokales Analytics-Dashboard
- [x] CI (GitHub Actions)
- [x] Provider-übergreifendes Prompt-Caching
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel-AI-SDK-Integrationen
- [x] Öffentlicher Benchmark + Einsparungs-Behauptung
- [ ] Embeddings + Image-Gen-Proxy

Siehe [DEMO.md](./DEMO.md) für die Failover-Demo.

## Lizenz

MIT. Siehe [LICENSE](./LICENSE).
