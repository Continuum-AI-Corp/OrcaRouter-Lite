# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | [日本語](./README.ja.md) | [한국어](./README.ko.md) | **Deutsch** | [Italiano](./README.it.md) | [Français](./README.fr.md) | [Español](./README.es.md) | [العربية](./README.ar.md)

**Selbst gehosteter LLM-Router mit verwaltetem Sicherheitsnetz.**
OpenAI-kompatibel. BYOK. Einzel-Workspace. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#tests)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#modellkatalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#lizenz)

OrcaRouter Lite ist die Open-Source-Einzel-Workspace-Edition von [OrcaRouter](https://www.orcarouter.ai). Führen Sie es auf Ihrem Laptop aus, integrieren Sie es in Ihr Produkt oder verwenden Sie das gehostete `api.orcarouter.ai` direkt für die Long-Tail-Modelle, für die Sie keine Schlüssel verwalten möchten.

> **Warum wir?** LiteLLM ist eine Bibliothek; OpenRouter ist Closed-Source-Hosted; Ollama ist nur lokal. Wir sind der **selbst gehostete Server mit verwaltetem Fallback** — ein Satz, den keiner von ihnen sagen kann.

## 60-Sekunden-Schnellstart

Zwei Wege, OrcaRouter zu verwenden:

### Weg A — Selbst gehostet (BYOK)

Führen Sie Lite auf Ihrer eigenen Maschine aus; bringen Sie Ihre eigenen Provider-Schlüssel mit.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# Mindestens einen hinzufügen: OPENAI_API_KEY=sk-...  (oder ORCAROUTER_API_KEY=...)

docker compose up
# Logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Basis-URL: `http://localhost:8000/v1`. Verwenden Sie den `sk-orca-*`-Schlüssel, der beim Start ausgegeben wird.

### Weg B — Gehostet (Konto erforderlich)

Kein Klonen, kein Docker. Registrieren, Schlüssel holen, jedes OpenAI SDK auf Hosted zeigen.

```bash
# 1. Auf https://www.orcarouter.ai registrieren und Ihren sk-orca-*-Schlüssel kopieren
# 2. https://api.orcarouter.ai/v1 als Basis-URL verwenden
```

**Konto erforderlich.** Hosted übernimmt Routing, Abrechnung und den Long-Tail von Providern — pro Token auf Ihrem OrcaRouter-Konto abgerechnet. Siehe [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Dann von jedem OpenAI SDK aufrufen

Die Beispiele unten verwenden die localhost-Basis-URL aus Weg A — tauschen Sie diese gegen `https://api.orcarouter.ai/v1`, wenn Sie auf Weg B sind.

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
    messages=[{"role": "user", "content": "Hallo!"}],
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
  messages: [{ role: "user", content: "Hallo!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"Hallo!"}]}'
```
</details>

Öffnen Sie `http://localhost:8000/` für das Dashboard — Provider, Routing, Analysen, Schlüssel (nur Weg A).

## Warum?

| | Lite | LiteLLM-Bibliothek | OpenRouter | Ollama |
|---|---|---|---|---|
| Selbst gehosteter Server | ✓ | als Bibliothek | ✗ | ✓ |
| OpenAI-kompatibel | ✓ | ✓ | ✓ | ✓ |
| Multi-Provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Eingebautes Dashboard | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (günstigster geeignet) | ✓ | ✗ | ✗ | n.v. |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n.v. |
| Hosted-als-Fallback | ✓ | ✗ | n.v. | ✗ |
| Kein Postgres / kein Redis erforderlich | ✓ | n.v. | n.v. | ✓ |

## `model="auto"` — das Hauptmerkmal

Senden Sie `model="auto"`, und OrcaRouter wählt das **günstigste** Modell unter Ihren konfigurierten Providern aus, das die Anforderungen der Anfrage (Tools, Vision, JSON-Modus) erfüllt. Keine manuellen Routing-Regeln; keine Rate-Limit-Akrobatik; keine `if x: ...`-Kostenoptimierung in Ihrem Code.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "Was ist auf diesem Bild?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → routet zum günstigsten VISION-fähigen Modell, das Ihre Schlüssel abdecken
```

Das aufgelöste Modell wird über den `x-orca-resolved-model`-Antwort-Header an die Aufrufer zurückgegeben, sodass Sie protokollieren/anzeigen können, was tatsächlich verwendet wurde.

## Hosted als Upstream (Lite + Hosted)

Lite läuft bereits? Setzen Sie `ORCAROUTER_API_KEY` auf Ihren `sk-orca-*` von [www.orcarouter.ai](https://www.orcarouter.ai), und Hosted wird zu einem weiteren Provider in der Routing-Kette — er deckt Modelle ab, die Ihre lokalen Schlüssel nicht abdecken:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Anwendungsfälle:
- **Try-before-you-buy** — keine lokalen Provider-Schlüssel erforderlich
- **Lokales Logging** — Hosted übernimmt das Routing, Lite speichert RequestLog-Zeilen für das Dashboard
- **Failover** — lokale Provider scheitern, Hosted ist das Sicherheitsnetz

## Streaming

OpenAI-kompatibles SSE-Format mit dem standardmäßigen `data: ... \n\n`-Framing und einem terminalen `[DONE]`-Sentinel — ein Drop-in für jedes SDK, das bereits von OpenAI streamt.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Erzähl mir eine Geschichte"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Modellkatalog

100+ Chat-Modelle werden beim Start aus [LiteLLMs Community-gepflegter Preisdatenbank](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) geladen — keine Modellliste, die manuell gepflegt werden muss. Jeder Eintrag legt offen:

- `id` (z.B. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (zugeordnet zu Ihren konfigurierten Schlüsseln)
- Funktionsflags: `supports_tools`, `supports_vision`, `supports_json_mode`
- Eingabe-/Ausgabekosten pro Token (treibt das Einsparungs-Widget + `model="auto"` an)

`GET /v1/models` gibt den Katalog im OpenAI-Format zurück.

## Woanders bereitstellen

| Plattform | Ein-Klick |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Repository verbinden, Root-Verzeichnis = `.` |
| Bare Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (Image bald verfügbar) |

## Was ist im Lieferumfang

- `POST /v1/chat/completions` — Proxy + Streaming + `model="auto"` + Cross-Provider-Prompt-Cache
- `GET  /v1/models` — auffindbarer Modellkatalog (100+ Modelle aus `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — Setzen / Auflisten / Widerrufen verschlüsselter Provider-Schlüssel
- `GET/PUT /v1/routing` — Strategie ändern (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — lokale Analysen, keine Telemetrie verlässt die Box
- `GET  /v1/hosted` — Hosted-Fallback-Status (treibt die "Erhalten Sie $5 Gratis-Guthaben"-Karte des Dashboards an)
- `GET/POST/DELETE /v1/keys/...` — API-Schlüssel auflisten / rotieren / widerrufen
- Single-Page-Dashboard unter `/`
- SQLite standardmäßig; Postgres optional über `DATABASE_URL`; Redis optional

### Cross-Provider-Prompt-Cache

Deterministische Anfragen (`temperature=0` oder fixierter `seed`) werden bei Wiederholungen aus dem Cache bedient — funktioniert über **alle** Provider, nicht nur Anthropic. Backend ist Redis, wenn `REDIS_URL` gesetzt ist, sonst In-Process-LRU. Cache-Treffer kehren sofort mit `x-orca-cache: HIT` zurück und kosten $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # selbe Payload erneut
HTTP/1.1 200 OK
x-orca-cache: HIT          ← aus Cache bedient, kein Upstream-Aufruf
```

### Einsparungs-Widget

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` meldet, was Ihr Verkehr bei immer-GPT-4 gekostet hätte vs. was er tatsächlich gekostet hat. Das Dashboard zeigt es als Kachel an.

### Integrationen

Drop-in-Konfigurationen für [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) und jedes Tool, das das OpenAI Chat Completions-Protokoll spricht. Siehe [`integrations/`](./integrations/).

## Was bewusst nicht enthalten ist

Dies ist die **Einzel-Workspace**-Edition. Per Design kein:
- Multi-Tenancy, RBAC, SSO
- Abrechnung, Wallets, Punkte, Partnerprogramm
- Admin-Konsole, Audit-Logs, Trust & Safety
- Multi-Pod-Deployment / Kubernetes
- E-Mail / Slack / Webhooks für Warnmeldungen

Für diese siehe das gehostete Produkt oder die (kommende) Teams-Edition.

## Tests

Test-First gebaut. Jedes Verhalten, das hier ausgeliefert wurde, hatte zuerst einen fehlschlagenden Test.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Slice | Tests | Was |
|---|---|---|
| 1. Konfiguration | 5 | env-Laden, Standardwerte, `env_provider_keys()` |
| 2. Seed | 3 | Bootstrap-Workspace + API-Schlüssel + RoutingConfig, idempotent |
| 3. Auth-Middleware | 4 | Bearer-Token-Validierung, 401 bei fehlend/ungültig |
| 4. App-Factory | 3 | /health, Fehler-Envelope, /v1/*-Gating |
| 5. Provider-Schlüssel-CRUD | 5 | im Ruhezustand verschlüsselt, Klartext fließt nie zurück |
| 6. Router-Cache | 13 | env+DB+Hosted-Deployment-Assembly mit Vorrang |
| 7. Chat-Completion | 5 | OpenAI-Format, RequestLog, Validierung |
| 8. Analysen | 4 | Recent / Spend / Latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | Auflisten/Erstellen/Widerrufen + Strategie-Update |
| 10. Streaming | 4 | SSE-Format, `[DONE]`-Sentinel, Log-Rückschreiben |
| 11. Katalog | 7 | 100+ Modelle, Funktionsflags, Preise |
| 12. `model="auto"` | 21 | Funktionserkennung, günstigster-erfüllt-Bedürfnisse (Unit + Integration) |
| 13. Kosteneinsparungen | 9 | Einsparungen vs. immer-GPT-4-Baseline + Hosted-Auto-Vergleich |
| 14. Prompt-Cache | 15 | Cross-Provider-Exact-Match-Cache + Chat-Integration |
| 15. Benchmark | 4 | summarize() + render_markdown()-Aggregation |
| 16. Hosted-Status | 7 | `/v1/hosted`-Konfigurationsquelle + Anmelde-URL-Oberfläche |
| 17. Hosted-Auto-Einsparungen | 3 | `_hosted_auto_savings`-Edge-Cases auf synthetischen Katalogen |
| 18. Nicht erreichbare Modelle | 7 | "Modelle, die Sie nicht erreichen können"-Kachel verschwindet, wenn Hosted aktiv ist |
| **Gesamt** | **127** | |

## Architektur

```
app/
├── main.py             FastAPI-Factory + Lifespan + SPA-Mount
├── config.py           Einstellungen (~15 Felder)
├── deps.py             DI-Helfer
├── seed.py             Erst-Run-Bootstrap
├── auto_routing.py     model="auto" Funktion + Kostenbewertung
├── router_cache.py     Einzel-Workspace-Router
├── prompt_cache.py     Cross-Provider-Exact-Match-Cache (Redis oder In-Memory-LRU)
├── schemas.py          OpenAI-kompatibles Anfrageschema
├── middleware/auth.py  sk-orca-* Validierung
└── routes/
    ├── chat.py         /v1/chat/completions  (blockierend + streaming)
    ├── models.py       /v1/models
    ├── providers.py    BYOK-CRUD
    ├── routing.py      Strategie-Konfiguration
    ├── analytics.py    Recent / Spend / Latency / Savings / Unreachable
    ├── keys.py         API-Schlüssel auflisten / rotieren / widerrufen
    ├── hosted.py       /v1/hosted — Hosted-Fallback-Status für das Dashboard
    └── health.py

packages/
├── litellm_adapter/    Router-Wrapper + 100+ Modellkatalog
├── auth/               Hashing + AES-256-GCM
└── db/                 Modelle + Engine + Session
```

## Roadmap

- [x] OpenAI-kompatible Chat-Completions
- [x] Streaming (SSE)
- [x] `model="auto"` günstigstes geeignetes Routing
- [x] Hosted-als-Upstream
- [x] Verschlüsseltes BYOK im Ruhezustand
- [x] Lokales Analyse-Dashboard
- [x] CI (GitHub Actions)
- [x] Cross-Provider-Prompt-Caching
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK Integrationen
- [x] Öffentlicher Benchmark + Einsparungs-Anspruch
- [ ] Embeddings + Bildgenerierungs-Proxy

Siehe [DEMO.md](./DEMO.md) für die Failover-Demo.

## Lizenz

MIT. Siehe [LICENSE](./LICENSE).
