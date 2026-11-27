# OrcaRouter Lite

**Ein Budget für jeden Coding-Agenten.**
Sehen und begrenzen Sie, was Claude Code, Codex, Gemini CLI, OpenCode und Ihre eigenen Apps ausgeben, über
alle Modell-Provider hinweg, ohne dass Ihre Prompts Ihren Rechner verlassen. Eine Menüleisten-App
für einzelne Entwickler und ein selbst gehosteter Router für ganze Teams. MIT-lizenziert.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="Das Menüleisten-Panel von OrcaRouter Lite: heutige Ausgaben im Vergleich zum Tagesbudget, verbundene Coding-Agenten und Provider-Status" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Ersteinrichtung: erkannte Coding-Agenten, wohin Anfragen gehen, und ein Tagesbudget" width="420">
</p>

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

**Mehr von uns:** [Alle Modell-APIs](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite ist die Open-Source-Edition von [OrcaRouter](https://www.orcarouter.ai). Es läuft auf Ihrem Rechner oder Ihrem Server, spricht die APIs von OpenAI, Anthropic und Gemini und kann das gehostete `api.orcarouter.ai` als Sicherheitsnetz bei Ausfällen und für Modelle nutzen, für die Sie keine Schlüssel haben.

**OrcaRouter** ist das gehostete Gateway hinter Lites Sicherheitsnetz: ein Schlüssel für jedes Modell, Failover zwischen Providern, kostenlose Modelle für den Einstieg und Bezahlung pro Anfrage für kostenpflichtige Modelle. Die Desktop-App schlägt es zuerst vor und startet Agenten mit den kostenlosen Modellen; Ihre eigenen Provider-Schlüssel bleiben eine vollwertige Alternative, mit oder ohne OrcaRouter.

## Die Desktop-App

Die Orca-App sitzt in Ihrer Menüleiste. Sie betreibt den Router auf `127.0.0.1`, verbindet Ihre
Coding-Agenten damit und zeigt, was sie ausgeben.

- **Heutige Ausgaben, pro Agent.** Die Tagessumme steht neben der Uhr; das Panel schlüsselt sie nach Agent auf, und montags fasst eine Benachrichtigung die Woche zusammen.
- **Ein Tagesbudget.** Benachrichtigungen bei 80 % und 100 % des festgelegten Betrags. Standardmäßig nur Warnungen; mit einem Häkchen pausiert Orca Ihre Coding-Agenten, sobald der Betrag erreicht ist.
- **Verbinden mit einem Klick.** Orca passt die Einstellungen des Agenten selbst an, legt ein Backup an und stellt es wieder her, wenn Sie die Verbindung trennen.
- **Nie offline.** Fällt ein Provider aus oder bremst Sie per Rate-Limit aus, weichen Anfragen auf einen anderen Provider oder auf das gehostete OrcaRouter aus, und die App zählt, wie viele sie gerettet hat. Ihr Konto verknüpfen Sie mit `orca link --key sk-orca-…` oder im Setup.
- **Standardmäßig privat.** Prompts gehen direkt von Ihren Agenten an den Provider Ihrer Wahl. Keine Telemetrie.
- **Funktioniert mit dem Gateway Ihres Teams.** `orca login https://ai-gw.example.com --key …` (oder "Join my company's gateway" in der Einrichtung) richtet Ihre Agenten auf das Gateway aus, das Ihr Plattform-Team betreibt; `orca logout` stellt den vorherigen Zustand wieder her.

**Installation.** Installer (`.dmg`, `.deb`, `.AppImage`, `.exe`) werden von
[`desktop.yml`](./.github/workflows/desktop.yml) gebaut und ab der nächsten getaggten Version an
jedes Release angehängt. Bis dahin sind dieselbe Engine und CLI nur einen Befehl entfernt:

**Nur die App nötig:** Sie bringt ihre eigene Engine und eine lokale SQLite-Datei mit – kein Server, keine Datenbank. Download, erster Start, Start bei der Anmeldung und Deinstallation: [INSTALL.md](./INSTALL.md) (Englisch).

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` stellt das Panel unter `http://127.0.0.1:8765/desktop/panel.html` bereit; wie Sie die
Menüleisten-App selbst bauen, steht in [`desktop/`](./desktop/README.md). Sobald das erste Release erschienen ist,
können macOS-Nutzer auch `brew install --cask continuum-ai-corp/tap/orcarouter-lite` ausführen.

Die heutigen Ausgaben in der Statusleiste von Claude Code: Fügen Sie dies zu `~/.claude/settings.json` hinzu.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` gibt die Woche als Markdown (oder `--format csv`) aus, zum Einfügen in einen Chat oder eine Tabelle.

| Agent | So wird verbunden |
|---|---|
| Claude Code | Automatisch: setzt `ANTHROPIC_BASE_URL` und einen eigenen Schlüssel in `~/.claude/settings.json` |
| Codex | Automatisch: fügt einen Provider `orca` (Responses API) zu `~/.codex/config.toml` hinzu und wählt ihn mit `model = "auto"` aus |
| Gemini CLI | Automatisch: setzt `GOOGLE_GEMINI_BASE_URL` und einen eigenen Schlüssel in `~/.gemini/.env` sowie die Gateway-Anmeldung von Gemini CLI in `~/.gemini/settings.json` |
| OpenCode | Automatisch: fügt einen Provider `orca` zu `~/.config/opencode/opencode.json` hinzu und wählt `orca/auto` aus; der Schlüssel bleibt in einer privaten Datei, die OpenCode liest |
| Command Code | Automatisch: fügt einen Provider `orca` zu `~/.commandcode/providers.json` hinzu, dessen Schlüssel aus einer privaten Datei kommt (Command Code lehnt dort Klartext-Schlüssel ab) |
| Cline | Ein Schritt per Copy & Paste: Wählen Sie in Cline API Provider → OpenAI Compatible und fügen Sie die Basis-URL und den Schlüssel ein, die die App anzeigt |
| Aider | Automatisch: setzt `openai-api-base`, einen eigenen Schlüssel und `model: openai/auto` in `~/.aider.conf.yml` |
| Cursor | Ein Schritt per Copy & Paste: Die App zeigt eine Basis-URL und einen Schlüssel für die Modelleinstellungen von Cursor |
| Hermes Agent | Automatisch: `~/.hermes/config.yaml` (Windows: `%LOCALAPPDATA%\hermes`) → `providers.orca`, `model.provider: custom:orca` |
| Pi | Automatisch: `~/.pi/agent/models.json` → `providers.orca`; `settings.json` → `defaultProvider: orca`, `defaultModel: auto` |
| OMP | Automatisch: `~/.omp/agent/models.yml` → `providers.orca`; `config.yml` → `modelRoles.default: orca/auto` |
| Kilo Code | Automatisch: `~/.config/kilo/kilo.json` → `provider.orca`, `model: orca/auto` (`{file:…}` key) |
| OpenClaw | Automatisch: `~/.openclaw/openclaw.json` → `models.providers.orca`, `agents.defaults.model.primary: orca/auto` |
| Kimi Code | Automatisch: `~/.kimi-code/config.toml` → `[providers.orca]`, `[models.orca-auto]`, `default_model` |
| Goose | Automatisch: `~/.config/goose/custom_providers/orca.json` (`auth.command` key) + `config.yaml` → `GOOSE_PROVIDER: orca` |
| Zed | Ein Schritt per Copy & Paste: `settings.json` → `language_models.openai_compatible.Orca` (`api_url`, model `auto`) + key in Zed / `ORCA_API_KEY` |
| OpenHands | Ein Schritt per Copy & Paste: `/settings` → Advanced: model `openai/auto`, base URL, key |
| DeepSeek Harness | Ein Schritt per Copy & Paste: Settings → Models → custom OpenAI-compatible provider, model `auto` |
| ZCode | Ein Schritt per Copy & Paste: Add provider → Create custom provider → OpenAI chat completions, model `auto` |

Jeder verbundene Agent erhält einen eigenen Schlüssel: So werden die Ausgaben pro Agent aufgeteilt,
und deshalb entzieht das Trennen der Verbindung sofort den Zugriff. Worauf die App auf Ihrem Rechner
zugreifen darf, ist in [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch) genau beschrieben.

<a id="free-and-open-for-good"></a>

## Frei und offen, für immer

- **MIT, dauerhaft.** Alles, was ein einzelner Entwickler oder ein Team braucht, bleibt unter MIT in diesem Repository: Routing, `model="auto"`, Budgets, das Dashboard, die Desktop-App. Wir werden kein Feature aus Lite in einen kostenpflichtigen Plan verschieben.
- **Kostenpflichtig ist das Angebot für Organisationen.** Die Verwaltung vieler Teams (SSO/SCIM, rollenbasierter Zugriff, flottenweite Budgets und Richtlinien, Aufbewahrung von Audit-Logs, Alerts an Slack und per E-Mail) gibt es im [gehosteten OrcaRouter](https://www.orcarouter.ai).
- **Überprüfbar.** Releases sind signiert und werden mit Provenance und einer SBOM ausgeliefert. Siehe [SECURITY.md](./SECURITY.md).

## Im Vergleich

| | Am besten für | So läuft es |
|---|---|---|
| **OrcaRouter Lite** | Vom einzelnen Entwickler bis zum Team, das Ausgaben pro Agent, Budgets und Failover ohne neue Infrastruktur will | Desktop-App, `uvx`/`pip` oder Docker; standardmäßig SQLite |
| LiteLLM-Proxy | Teams, die viele Konfigurationsmöglichkeiten und ein Python-SDK wollen | Selbst gehosteter Server; Postgres für das Ausgaben-Tracking |
| OpenRouter | Ein API-Schlüssel für viele Modelle, abgerechnet über OpenRouter | Nur gehostet; Prompts laufen über deren Dienst |
| Die eigene Gateway-Unterstützung von Claude Code | Unternehmen, die nur Claude nutzen | Richtet Claude Code auf ein Gateway aus, das Sie selbst betreiben; nur Claude-Modelle |

## Als Server betreiben (60 Sekunden)

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

**Konto erforderlich.** Kostenlose Modelle für den Einstieg; kostenpflichtige Modelle werden pro Anfrage über Ihr OrcaRouter-Konto abgerechnet. Hosted übernimmt Routing, Failover zwischen Providern und den Long Tail an Modellen. Siehe [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

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

## `model="auto"`

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
- **Kostenlos starten** — kostenlose Modelle brauchen keine Provider-Schlüssel; kostenpflichtige Modelle nur, wenn Sie sie wählen
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

| Plattform | So geht's |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (wird ab dem nächsten getaggten Release veröffentlicht; prüfen Sie es mit den Befehlen in [SECURITY.md](./SECURITY.md)) |
| Render | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Continuum-AI-Corp/OrcaRouter-Lite): nutzt [`render.yaml`](./render.yaml), erzeugt die Secrets, legt die Datenbank auf einer Disk ab |
| Fly.io | `fly launch --no-deploy`, dann die Schritte für das Volume und `fly secrets set` oben in [`fly.toml`](./fly.toml), dann `fly deploy` |
| Railway | `railway init`, `railway volume add --mount-path /data`, `railway variables --set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) --set API_KEY_PEPPER=$(openssl rand -hex 32) --set DATABASE_URL=sqlite+aiosqlite:////data/orca.db`, dann `railway up` (baut mit [`railway.json`](./railway.json)) |

## Was ist enthalten

- `POST /v1/chat/completions` — Proxy + Streaming + `model="auto"` + provider-übergreifender Prompt-Cache
- `POST /v1/messages` — **Anthropic-Messages-API-Ingress** (Claude Code / Anthropic-SDKs verbinden sich direkt; `+ /count_tokens`)
- `POST /v1/responses` — **OpenAI-Responses-API-Ingress** (Codex und Responses-SDK-Clients; Streaming, Function- und Custom-Tools)
- `POST /v1beta/models/{model}:generateContent` — **Gemini-API-Ingress** (google-genai-SDK verbindet sich direkt; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — auffindbarer Modellkatalog (100+ Modelle aus `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — verschlüsselte Provider-Schlüssel setzen / auflisten / widerrufen
- `GET/PUT /v1/routing` — Strategie ändern (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — lokale Analytics, keine Telemetrie verlässt die Box
- `GET  /v1/hosted` — Status des gehosteten Gateways (treibt die OrcaRouter-Karte des Dashboards an)
- `GET/POST/DELETE /v1/keys/...` — API-Schlüssel auflisten / rotieren / widerrufen
- `/v1/app/*` — Agenten, Ausgabenübersicht und Budget für die Desktop-App (nur wenn mit `orca up` gestartet; siehe [SECURITY.md](./SECURITY.md))
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

Das sind Funktionen für Organisationen, und es gibt sie im [gehosteten OrcaRouter](https://www.orcarouter.ai); siehe [Frei und offen, für immer](#free-and-open-for-good).

## Testen

Test-First entwickelt: Jedes hier ausgelieferte Verhalten hatte zuerst einen fehlschlagenden Test.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

- [x] OpenAI-kompatible Chat-Completions, Streaming, `model="auto"`
- [x] Native Anthropic- und Gemini-Endpunkte
- [x] Hosted-als-Upstream-Fallback, verschlüsseltes BYOK, lokales Dashboard
- [x] Provider-übergreifender Prompt-Cache
- [x] Desktop-App: Ausgaben in der Menüleiste, Benachrichtigungen zum Tagesbudget, Agenten mit einem Klick verbinden
- [x] Signierte Releases mit Provenance und SBOM; Abhängigkeiten per Hash gesperrt
- [x] Tagesbudget, das warnt oder Coding-Agenten am Limit pausiert
- [x] `orca login` / "Join my company's gateway": das Gateway eines Teams direkt aus der App nutzen
- [x] `/v1/responses`, damit Codex sich verbindet; ebenso Gemini CLI, OpenCode, Command Code und Cline
- [x] Verschlüsselungsschlüssel im Schlüsselbund des Betriebssystems; eine Update-Prüfung pro Tag
- [ ] Budgets pro Entwickler, durchgesetzt auf einem gemeinsamen Team-Gateway
- [ ] Embeddings, Ollama/vLLM-Provider, eigene Fallback-Ketten

Siehe [DEMO.md](./DEMO.md) für die Failover-Demo.

<a id="license"></a>

## Lizenz

MIT. Siehe [LICENSE](./LICENSE).
