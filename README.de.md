# OrcaRouter Lite

**Selbst gehosteter LLM-Router mit verwaltetem Sicherheitsnetz.**
OpenAI-kompatibel. Na gut. Einzelarbeitsplatz. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![Modelle](https://img.shields.io/badge/models-100%2B-blue)](#Modellkatalog)
[![Lizenz](https://img.shields.io/badge/license-MIT-blue)](#Lizenz)

## Sprachen

- [Englisch](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Deutsch](./README.de.md)
- [Français](./README.fr.md)
- [Español](./README.es.md)
- [Italienisch](./README.it.md)
- [Russisch](./README.ru.md)
- [Português](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite ist die Open-Source-Single-Workspace-Edition von [OrcaRouter](https://www.orcarouter.ai). Führen Sie es auf Ihrem Laptop aus, liefern Sie es in Ihr Produkt ein oder verwenden Sie das gehostete „api.orcarouter.ai“ direkt für die lange Reihe von Modellen, für die Sie keine Schlüssel verwalten möchten.

> **Warum wir?** LiteLLM ist eine Bibliothek; OpenRouter ist ein Closed-Source-Hosting; Ollama ist nur lokal verfügbar. Wir sind der **selbstgehostete Server mit verwaltetem Fallback** – ein Satz, den keiner von denen sagen kann.

## 60-Sekunden-Schnellstart

Zwei Möglichkeiten, OrcaRouter zu verwenden:

### Pfad A – Selbstgehostet (BYOK)

Führen Sie Lite auf Ihrem eigenen Computer aus. Bringen Sie Ihre eigenen Anbieterschlüssel mit.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Basis-URL: „http://localhost:8000/v1“. Verwenden Sie die beim Start aufgedruckte Taste „sk-orca-*“.

### Pfad B – Gehostet (Konto erforderlich)

Kein Klon, kein Docker. Registrieren Sie sich, erhalten Sie einen Schlüssel und richten Sie ein beliebiges OpenAI-SDK auf gehostet ein.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Konto erforderlich.** Hosted übernimmt das Routing, die Abrechnung und den Long Tail der Anbieter – die Abrechnung erfolgt pro Token auf Ihrem OrcaRouter-Konto. Siehe [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Rufen Sie es dann von einem beliebigen OpenAI SDK aus auf

Die folgenden Beispiele verwenden die Localhost-Basis-URL von Pfad A – tauschen Sie sie gegen „https://api.orcarouter.ai/v1“ aus, wenn Sie sich auf Pfad B befinden.

<Details>
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

<Details>
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

<Details>
<summary><b>Curl</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

Öffnen Sie „http://localhost:8000/“ für das Dashboard – Anbieter, Routing, Analysen, Schlüssel (nur Pfad A).

## Warum?

| | Lite | LiteLLM-Bibliothek | OpenRouter | Ollama |
|---|---|---|---|---|
| Selbstgehosteter Server | ✓ | als Bibliothek | ✗ | ✓ |
| OpenAI-kompatibel | ✓ | ✓ | ✓ | ✓ |
| Multi-Anbieter (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Integriertes Armaturenbrett | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (am günstigsten fähig) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Als Fallback gehostet | ✓ | ✗ | n/a | ✗ |
| Kein Postgres / kein Redis erforderlich | ✓ | n/a | n/a | ✓ |

## `model="auto"` – die Schlagzeilenfunktion

Senden Sie „model="auto"` und OrcaRouter wählt das **günstigste** Modell Ihrer konfigurierten Anbieter aus, das die Leistungsanforderungen der Anfrage erfüllt (Tools, Vision, JSON-Modus). Keine manuellen Routing-Regeln; kein frequenzbegrenztes Turnen; nein `if x: ...` Kostenoptimierung in Ihrem Code.

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

Das aufgelöste Modell wird den Aufrufern über den Antwortheader „x-orca-resolved-model“ wieder angezeigt, sodass Sie protokollieren/anzeigen können, was tatsächlich verwendet wurde.

## Als Upstream gehostet (Lite + gehostet)

Läuft bereits Lite? Setzen Sie „ORCAROUTER_API_KEY“ auf Ihren „sk-orca-*“ von [www.orcarouter.ai](https://www.orcarouter.ai), und gehostet wird zu einem weiteren Anbieter in der Routing-Kette – und deckt Modelle ab, die Ihre lokalen Schlüssel nicht haben:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Anwendungsfälle:
- **Vor dem Kauf testen** – keine lokalen Anbieterschlüssel erforderlich
- **Lokale Protokollierung** – gehostet übernimmt das Routing, Lite speichert RequestLog-Zeilen für das Dashboard
- **Failover** – lokale Anbieter fallen aus, gehostet ist das Sicherheitsnetz

## Streaming

OpenAI-kompatibles SSE-Format mit dem Standardrahmen „data: ... \n\n“ und einem Terminal-Sentinel „[FERTIG]“ – Drop-In für jedes SDK, das bereits von OpenAI streamt.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Modellkatalog

Über 100 Chat-Modelle werden beim Start aus der von der Community gepflegten Preisdatenbank von LiteLLM geladen (https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) – keine Modellliste, die manuell verwaltet werden muss. Jeder Eintrag enthüllt:

- „id“ (z. B. „gpt-4o“, „claude-3-5-sonnet-latest“)
- „Anbieter“ (zugeordnet zu Ihren konfigurierten Schlüsseln)
- Fähigkeitsflags: „supports_tools“, „supports_vision“, „supports_json_mode“.
- Eingabe-/Ausgabekosten pro Token (steuert das Spar-Widget + „model="auto"`)

„GET /v1/models“ gibt den Katalog im OpenAI-Format zurück.

## Woanders bereitstellen

| Plattform | Ein Klick |
|---|---|
| Eisenbahn | [![Auf der Eisenbahn bereitstellen](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Rendern | Repo verbinden, Root-Verzeichnis = `.` |
| Nackter Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (Bild folgt bald) |

## Was ist in der Box?

- „POST /v1/chat/completions“ – Proxy + Streaming + „model="auto"“ + anbieterübergreifender Eingabeaufforderungs-Cache
- „GET /v1/models“ – erkennbarer Modellkatalog (über 100 Modelle aus „litellm.model_cost“)
- „GET/PUT/DELETE /v1/providers/{provider}“ – verschlüsselte Anbieterschlüssel festlegen/auflisten/widerrufen
- „GET/PUT /v1/routing“ – Strategie ändern („ausgewogen“ / „billigste“ / „schnellste“ / „Qualität“)
– „GET /v1/analytics/{recent,spend,latency, savings,unreachable}“ – lokale Analyse, keine Telemetrie verlässt die Box
- „GET /v1/hosted“ – Hosted-Fallback-Status (steuert die Karte „Get $5 free Credit“ im Dashboard)
- „GET/POST/DELETE /v1/keys/...“ – API-Schlüssel auflisten/drehen/widerrufen
- Einseitiges Dashboard unter „/“.
- SQLite standardmäßig; Postgres-Opt-in über „DATABASE_URL“; Redis optional

### Anbieterübergreifender Prompt-Cache

Deterministische Anfragen („Temperatur=0“ oder angehefteter „Seed“) werden bei Wiederholung aus dem Cache bedient – ​​funktioniert bei **jedem** Anbieter, nicht nur bei Anthropic. Das Backend ist Redis, wenn „REDIS_URL“ festgelegt ist, andernfalls In-Process-LRU. Cache-Treffer kehren sofort mit „x-orca-cache: HIT“ zurück und kosten 0 $.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Spar-Widget

„GET /v1/analytics/ savings?baseline=gpt-4o&days=7“ meldet, was Ihr Traffic bei Always-GPT-4 gekostet hätte, im Vergleich zu den tatsächlichen Kosten. Das Dashboard zeigt es als Kachel an.

### Integrationen

Drop-in-Konfigurationen für [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) und jedes Tool, das das OpenAI Chat Completions-Protokoll beherrscht. Siehe [`integrations/`](./integrations/).

## Was ist bewusst nicht

Dies ist die **Single-Workspace**-Edition. Absichtlich nein:
- Mandantenfähigkeit, RBAC, SSO
- Abrechnung, Geldbörsen, Punkte, Partnerprogramm
- Admin-Konsole, Audit-Protokolle, Vertrauen und Sicherheit
- Multi-Pod-Bereitstellung / Kubernetes
- E-Mail/Slack/Webhooks für Benachrichtigungen

Sehen Sie sich dazu das gehostete Produkt oder die (bevorstehende) Teams-Edition an.

## Testen

Zuerst als Test gebaut. Jedes hier ausgelieferte Verhalten hatte zunächst einen nicht bestandenen Test.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Scheibe | Tests | Was |
|---|---|---|
| 1. Konfiguration | 5 | env wird geladen, Standardeinstellungen, `env_provider_keys()` |
| 2. Samen | 3 | Bootstrap-Arbeitsbereich + API-Schlüssel + RoutingConfig, idempotent |
| 3. Authentifizierungs-Middleware | 4 | Bearer-Token-Validierung, 401 bei fehlendem/ungültigem |
| 4. App-Fabrik | 3 | /health, Fehlerumschlag, /v1/* Gating |
| 5. Anbieterschlüssel CRUD | 5 | im Ruhezustand verschlüsselt, Klartext niemals Roundtrips |
| 6. Router-Cache | 13 | env+DB+gehostete Bereitstellungsassembly mit Priorität |
| 7. Chat-Abschluss | 5 | OpenAI-Format, RequestLog, Validierung |
| 8. Analytik | 4 | aktuell / Ausgaben / Latenz p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | auflisten/erstellen/widerrufen + Strategieaktualisierung |
| 10. Streaming | 4 | SSE-Format, „[FERTIG]“ Sentinel, Protokollrückschreibung |
| 11. Katalog | 7 | Über 100 Modelle, Leistungsmerkmale, Preise |
| 12. `model="auto"` | 21 | Fähigkeitserkennung, billigste-Erfüllung-Bedürfnisse (Einheit + Integration) |
| 13. Kosteneinsparungen | 9 | Einsparungen gegenüber Always-GPT-4 Baseline + Hosted-Auto-Vergleich |
| 14. Prompt-Cache | 15 | Anbieterübergreifender Exact-Match-Cache + Chat-Integration |
| 15. Benchmark | 4 | summary() + render_markdown() Aggregation |
| 16. Gehosteter Status | 7 | `/v1/hosted` Konfigurationsquelle + Anmelde-URL-Oberfläche |
| 17. Hosted-Auto-Einsparungen | 3 | „_hosted_auto_ savings“-Randfälle für synthetische Kataloge |
| 18. Nicht erreichbare Modelle | 7 | Die Kachel „Modelle, die Sie nicht erreichen können“ wird gelöscht, wenn „Hosting“ aktiviert ist |
| **Gesamt** | **127** | |

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

- [x] OpenAI-kompatible Chat-Abschlüsse
- [x] Streaming (SSE)
- [x] `model="auto"` günstigstes Routing
- [x] Als Upstream gehostet
- [x] Verschlüsseltes BYOK im Ruhezustand
- [x] Lokales Analyse-Dashboard
- [x] CI (GitHub-Aktionen)
- [x] Anbieterübergreifendes Prompt-Caching
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK-Integrationen
- [x] Öffentlicher Benchmark + Sparanspruch
- [ ] Einbettungen + Image-Gen-Proxy

Die Failover-Demo finden Sie unter [DEMO.md](./DEMO.md).

## Lizenz

MIT. Siehe [LIZENZ](./LIZENZ).
