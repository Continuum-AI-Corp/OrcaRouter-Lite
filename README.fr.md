# OrcaRouter Lite

**Fixez un budget à chaque agent de code.**
Voyez et plafonnez ce que dépensent Claude Code, Codex, Gemini CLI, OpenCode et vos propres applications, sur
tous les fournisseurs de modèles, sans que vos prompts quittent votre machine. Une app de barre de
menus pour un développeur seul, et un routeur auto-hébergé pour toute une équipe. Sous licence MIT.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="Le panneau d'OrcaRouter Lite dans la barre de menus : dépenses du jour face au budget quotidien, agents de code connectés et état des fournisseurs" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Configuration au premier lancement : agents de code détectés, destination des requêtes et budget quotidien" width="420">
</p>

## Langues

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

**Nous retrouver :** [Toutes les API de modèles](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite est l'édition open source d'[OrcaRouter](https://www.orcarouter.ai). Il tourne sur votre ordinateur ou votre serveur, parle les API OpenAI, Anthropic et Gemini, et peut utiliser `api.orcarouter.ai` hébergé comme filet de sécurité en cas de panne et pour les modèles dont vous n'avez pas les clés.

## L'application de bureau

L'app Orca vit dans votre barre de menus. Elle fait tourner le routeur sur `127.0.0.1`, y connecte
vos agents de code et affiche ce qu'ils dépensent.

- **Dépenses du jour, par agent.** Le total du jour s'affiche à côté de l'horloge ; le panneau le ventile par agent, et chaque lundi une notification résume la semaine.
- **Un budget quotidien.** Notifications à 80 % et 100 % du montant que vous fixez. Simples alertes par défaut ; cochez une case et Orca met en pause vos agents de code une fois le montant atteint.
- **Connexion en un clic.** Orca modifie les réglages propres à l'agent, en garde une sauvegarde et la restaure quand vous le déconnectez.
- **Jamais en panne.** Quand un fournisseur tombe ou vous impose un rate-limit, les requêtes basculent vers un autre fournisseur ou vers OrcaRouter hébergé, et l'app compte combien elle en a sauvées. Liez votre compte avec `orca link --key sk-orca-…` ou dans la configuration.
- **Privé par défaut.** Les prompts vont directement de vos agents au fournisseur de votre choix. Aucune télémétrie.
- **Compatible avec la gateway de votre équipe.** `orca login https://ai-gw.example.com --key …` (ou "Join my company's gateway" dans la configuration) dirige vos agents vers la gateway gérée par votre équipe plateforme ; `orca logout` les rétablit.

**Installation.** Les installeurs (`.dmg`, `.deb`, `.AppImage`, `.msi`) sont construits par
[`desktop.yml`](./.github/workflows/desktop.yml) et joints à chaque release, à partir de la
prochaine version taguée. En attendant, le même moteur et la même CLI sont à une commande près :

**L'app suffit :** elle embarque son propre moteur et un fichier SQLite local ; aucun serveur ni base de données à installer. Téléchargement, premier lancement, démarrage à l'ouverture de session et désinstallation : [INSTALL.md](./INSTALL.md) (en anglais).

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` sert le panneau sur `http://127.0.0.1:8765/desktop/panel.html` ; pour construire l'app
de barre de menus elle-même, voir [`desktop/`](./desktop/README.md). Dès la première release publiée,
les utilisateurs de macOS pourront aussi faire `brew install --cask continuum-ai-corp/tap/orcarouter-lite`.

Les dépenses du jour dans la barre d'état de Claude Code : ajoutez ceci à `~/.claude/settings.json`.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` affiche la semaine en Markdown (ou `--format csv`), à coller dans un chat ou un tableur.

| Agent | Mode de connexion |
|---|---|
| Claude Code | Automatique : définit `ANTHROPIC_BASE_URL` et une clé dédiée dans `~/.claude/settings.json` |
| Codex | Automatique : ajoute un fournisseur `orca` (API Responses) à `~/.codex/config.toml` et le sélectionne avec `model = "auto"` |
| Gemini CLI | Automatique : définit `GOOGLE_GEMINI_BASE_URL` et une clé dédiée dans `~/.gemini/.env`, ainsi que la connexion par gateway de Gemini CLI dans `~/.gemini/settings.json` |
| OpenCode | Automatique : ajoute un fournisseur `orca` à `~/.config/opencode/opencode.json` et sélectionne `orca/auto` ; la clé reste dans un fichier privé que lit OpenCode |
| Command Code | Automatique : ajoute un fournisseur `orca` à `~/.commandcode/providers.json` dont la clé provient d'un fichier privé (Command Code y refuse les clés en clair) |
| Cline | Un copier-coller : choisissez API Provider → OpenAI Compatible dans Cline et collez l'URL de base et la clé affichées par l'app |
| Aider | Automatique : définit `openai-api-base`, une clé dédiée et `model: openai/auto` dans `~/.aider.conf.yml` |
| Cursor | Un copier-coller : l'app affiche une URL de base et une clé pour les réglages de modèles de Cursor |
| Hermes Agent | Automatique : `~/.hermes/config.yaml` (Windows: `%LOCALAPPDATA%\hermes`) → `providers.orca`, `model.provider: custom:orca` |
| Pi | Automatique : `~/.pi/agent/models.json` → `providers.orca`; `settings.json` → `defaultProvider: orca`, `defaultModel: auto` |
| OMP | Automatique : `~/.omp/agent/models.yml` → `providers.orca`; `config.yml` → `modelRoles.default: orca/auto` |
| Kilo Code | Automatique : `~/.config/kilo/kilo.json` → `provider.orca`, `model: orca/auto` (`{file:…}` key) |
| OpenClaw | Automatique : `~/.openclaw/openclaw.json` → `models.providers.orca`, `agents.defaults.model.primary: orca/auto` |
| Kimi Code | Automatique : `~/.kimi-code/config.toml` → `[providers.orca]`, `[models.orca-auto]`, `default_model` |
| Goose | Automatique : `~/.config/goose/custom_providers/orca.json` (`auth.command` key) + `config.yaml` → `GOOSE_PROVIDER: orca` |
| Zed | Un copier-coller : `settings.json` → `language_models.openai_compatible.Orca` (`api_url`, model `auto`) + key in Zed / `ORCA_API_KEY` |
| OpenHands | Un copier-coller : `/settings` → Advanced: model `openai/auto`, base URL, key |
| DeepSeek Harness | Un copier-coller : Settings → Models → custom OpenAI-compatible provider, model `auto` |
| ZCode | Un copier-coller : Add provider → Create custom provider → OpenAI chat completions, model `auto` |

Chaque agent connecté reçoit sa propre clé : c'est ainsi que les dépenses sont réparties par agent,
et c'est pourquoi la déconnexion révoque l'accès immédiatement. Ce que l'app peut toucher sur votre
ordinateur est détaillé dans [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

<a id="free-and-open-for-good"></a>

## Libre et ouvert, pour de bon

- **MIT, pour toujours.** Tout ce dont un développeur ou une équipe a besoin reste dans ce dépôt sous MIT : routage, `model="auto"`, budgets, tableau de bord, application de bureau. Nous ne déplacerons aucune fonctionnalité de Lite vers une offre payante.
- **Le payant, c'est pour les organisations.** La gouvernance de nombreuses équipes (SSO/SCIM, contrôle d'accès basé sur les rôles, budgets et politiques à l'échelle de toute la flotte, conservation des journaux d'audit, alertes vers Slack et par e-mail) se trouve dans [OrcaRouter hébergé](https://www.orcarouter.ai).
- **Vérifiable.** Les releases sont signées et livrées avec leur provenance et un SBOM. Voir [SECURITY.md](./SECURITY.md).

## Comparaison

| | Idéal pour | Mode d'exécution |
|---|---|---|
| **OrcaRouter Lite** | Du développeur seul à l'équipe qui veut les dépenses par agent, des budgets et du failover sans nouvelle infrastructure | App de bureau, `uvx`/`pip` ou Docker ; SQLite par défaut |
| Proxy LiteLLM | Les équipes qui veulent une large surface de configuration et un SDK Python | Serveur auto-hébergé ; Postgres pour le suivi des dépenses |
| OpenRouter | Une seule clé API pour de nombreux modèles, facturés par OpenRouter | Hébergé uniquement ; les prompts transitent par leur service |
| Le support de gateway intégré à Claude Code | Les entreprises qui n'utilisent que Claude | Pointe Claude Code vers une gateway que vous exploitez ; modèles Claude uniquement |

## Le faire tourner en serveur (60 secondes)

Deux façons d'utiliser OrcaRouter :

### Voie A — Auto-hébergé (BYOK)

Exécutez Lite sur votre propre machine ; apportez vos propres clés de fournisseur.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# ajoutez au moins une : OPENAI_API_KEY=sk-...  (ou ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL de base : `http://localhost:8000/v1`. Utilisez la clé `sk-orca-*` affichée au démarrage.

### Voie B — Hébergé (compte requis)

Pas de clone, pas de docker. Inscrivez-vous, récupérez une clé, pointez n'importe quel SDK OpenAI sur l'instance hébergée.

```bash
# 1. Inscrivez-vous sur https://www.orcarouter.ai et copiez votre clé sk-orca-*
# 2. Utilisez https://api.orcarouter.ai/v1 comme URL de base
```

**Compte requis.** L'instance hébergée gère le routage, la facturation et la longue traîne de fournisseurs — facturé au token sur votre compte OrcaRouter. Voir [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Puis appelez-le depuis n'importe quel SDK OpenAI

Les exemples ci-dessous utilisent l'URL de base localhost de la Voie A — remplacez par `https://api.orcarouter.ai/v1` si vous êtes sur la Voie B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # ou "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

Ouvrez `http://localhost:8000/` pour le tableau de bord — fournisseurs, routage, analytics, clés (Voie A uniquement).

## `model="auto"`

Envoyez `model="auto"` et OrcaRouter choisit le modèle **le moins cher** parmi vos fournisseurs configurés qui répond aux exigences de capacité de la requête (tools, vision, mode JSON). Pas de règles de routage manuelles ; pas d'acrobaties avec les rate-limits ; pas d'optimisation de coût `if x: ...` dans votre code.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → route vers le modèle compatible VISION le moins cher couvert par vos clés
```

Le modèle résolu est exposé en retour aux appelants via l'en-tête de réponse `x-orca-resolved-model`, pour que vous puissiez logger/afficher ce qui a réellement été utilisé.

## Hébergé en upstream (Lite + hébergé)

Lite déjà en marche ? Définissez `ORCAROUTER_API_KEY` avec votre `sk-orca-*` de [www.orcarouter.ai](https://www.orcarouter.ai), et l'hébergé devient un fournisseur de plus dans la chaîne de routage — couvrant les modèles que vos clés locales ne couvrent pas :

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Cas d'usage :
- **Essayer avant d'acheter** — pas besoin de clés de fournisseur locales
- **Logging local** — l'hébergé gère le routage, Lite stocke les lignes RequestLog pour le tableau de bord
- **Failover** — les fournisseurs locaux échouent, l'hébergé est le filet de sécurité

## Streaming

Format SSE compatible OpenAI avec le framing standard `data: ... \n\n` et un sentinel terminal `[DONE]` — drop-in pour tout SDK qui stream déjà depuis OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Endpoints protocolaires natifs (Anthropic + Gemini)

Lite parle trois protocoles entrants sur un seul pipeline de routage. Les clients qui ne parlent que les formats wire Anthropic ou Gemini se connectent directement — aucun SDK OpenAI requis :

```bash
# Claude Code, pointé sur Lite (pas de suffixe /v1 dans l'URL de base)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# SDK google-genai, pointé sur Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Les requêtes sont traduites à l'entrée vers le même pipeline interne, donc `model="auto"`, le cache de prompts inter-fournisseurs (partagé entre les protocoles), les stratégies de routage et le tableau de bord d'analytics fonctionnent tous à l'identique. Guides : [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Catalogue de modèles

Plus de 100 modèles de chat sont chargés au démarrage depuis la [base de données de prix maintenue par la communauté de LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — pas de liste de modèles à maintenir à la main. Chaque entrée expose :

- `id` (par ex. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mappé sur vos clés configurées)
- Drapeaux de capacité : `supports_tools`, `supports_vision`, `supports_json_mode`
- Coût par token entrée/sortie (alimente le widget d'économies + `model="auto"`)

`GET /v1/models` renvoie le catalogue au format OpenAI.

## Déployer ailleurs

| Plateforme | Comment |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (publiée à partir de la prochaine release taguée ; vérifiez-la avec les commandes de [SECURITY.md](./SECURITY.md)) |
| Render | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) : utilise [`render.yaml`](./render.yaml), génère les secrets, conserve la base de données sur un disque |
| Fly.io | `fly launch --no-deploy`, puis les étapes du volume et de `fly secrets set` en haut de [`fly.toml`](./fly.toml), puis `fly deploy` |
| Railway | `railway init`, `railway volume add --mount-path /data`, `railway variables --set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) --set API_KEY_PEPPER=$(openssl rand -hex 32) --set DATABASE_URL=sqlite+aiosqlite:////data/orca.db`, puis `railway up` (build avec [`railway.json`](./railway.json)) |

## Ce qu'il y a dans la boîte

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache de prompts inter-fournisseurs
- `POST /v1/messages` — **ingress de l'API Messages d'Anthropic** (Claude Code / les SDK Anthropic se connectent directement ; `+ /count_tokens`)
- `POST /v1/responses` — **ingress de l'API Responses d'OpenAI** (Codex et les clients du SDK Responses ; streaming, outils de fonction et personnalisés)
- `POST /v1beta/models/{model}:generateContent` — **ingress de l'API Gemini** (le SDK google-genai se connecte directement ; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — catalogue de modèles découvrable (100+ modèles depuis `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — définir / lister / révoquer des clés de fournisseur chiffrées
- `GET/PUT /v1/routing` — changer la stratégie (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics locales, aucune télémétrie ne sort de la boîte
- `GET  /v1/hosted` — statut du fallback hébergé (alimente la carte « Get $5 free credit » du tableau de bord)
- `GET/POST/DELETE /v1/keys/...` — lister / faire tourner / révoquer des clés API
- `/v1/app/*` — agents, résumé des dépenses et budget pour l'app de bureau (uniquement si lancé avec `orca up` ; voir [SECURITY.md](./SECURITY.md))
- Tableau de bord en page unique sur `/`
- SQLite par défaut ; Postgres opt-in via `DATABASE_URL` ; Redis optionnel

### Cache de prompts inter-fournisseurs

Les requêtes déterministes (`temperature=0` ou `seed` figée) sont servies depuis le cache lors des répétitions — fonctionne sur **tous** les fournisseurs, pas seulement Anthropic. Le backend est Redis si `REDIS_URL` est défini, sinon un LRU en processus. Les hits cache reviennent instantanément avec `x-orca-cache: HIT` et coûtent 0 $.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # même payload, deuxième fois
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servi depuis le cache, pas d'appel upstream
```

### Widget d'économies

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` indique ce que votre trafic aurait coûté en toujours-GPT-4 face à ce qu'il a réellement coûté. Le tableau de bord l'affiche sous forme de tuile.

### Intégrations

Configurations drop-in pour [Claude Code](./integrations/claude-code.md), [SDK Gemini](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) et tout outil parlant le protocole OpenAI Chat Completions — plus les formats wire natifs d'Anthropic et de Gemini. Voir [`integrations/`](./integrations/).

## Ce qui n'est délibérément pas inclus

C'est l'édition **mono-workspace**. Par conception, pas de :
- multi-tenant, RBAC, SSO
- facturation, wallets, points, programme partenaire
- console d'administration, logs d'audit, trust & safety
- déploiement multi-pod / Kubernetes
- e-mail / Slack / webhooks pour les alertes

Ce sont des fonctionnalités pour les organisations, disponibles dans [OrcaRouter hébergé](https://www.orcarouter.ai) ; voir [Libre et ouvert, pour de bon](#free-and-open-for-good).

## Tests

Construit en test-first : chaque comportement livré ici a d'abord eu un test qui échouait.

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

- [x] Chat completions compatibles OpenAI, streaming, `model="auto"`
- [x] Endpoints natifs Anthropic et Gemini
- [x] Fallback hébergé en upstream, BYOK chiffré, tableau de bord local
- [x] Cache de prompts inter-fournisseurs
- [x] App de bureau : dépenses dans la barre de menus, alertes de budget quotidien, connexion des agents en un clic
- [x] Releases signées avec provenance et SBOM ; dépendances verrouillées par hash
- [x] Budget quotidien qui alerte, ou met en pause les agents de code à la limite
- [x] `orca login` / "Join my company's gateway" : utiliser la gateway d'une équipe depuis l'app
- [x] `/v1/responses`, pour que Codex se connecte ; Gemini CLI, OpenCode, Command Code et Cline aussi
- [x] Clé de chiffrement dans le trousseau du système d'exploitation ; une vérification de mise à jour par jour
- [ ] Budgets par développeur appliqués sur une gateway d'équipe partagée
- [ ] Embeddings, fournisseurs Ollama/vLLM, chaînes de fallback personnalisées

Voir [DEMO.md](./DEMO.md) pour la démo de failover.

<a id="license"></a>

## Licence

MIT. Voir [LICENSE](./LICENSE).
