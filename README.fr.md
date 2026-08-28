# OrcaRouter Lite

**Routeur LLM auto-hébergé avec filet de sécurité géré.**
Compatible OpenAI. BYOK. Workspace unique. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

![Démo de failover OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"` absorbe une panne de fournisseur en temps réel — sans changement de code. Comment l’enregistrer : [DEMO.md](./DEMO.md).*

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

OrcaRouter Lite est l'édition open source mono-workspace d'[OrcaRouter](https://www.orcarouter.ai). Exécutez-le sur votre laptop, embarquez-le dans votre produit, ou utilisez directement `api.orcarouter.ai` hébergé pour la longue traîne de modèles dont vous ne voulez pas gérer les clés.

> **Pourquoi nous ?** LiteLLM est une bibliothèque ; OpenRouter est en source fermée et hébergé ; Ollama est uniquement local. Nous sommes le **serveur auto-hébergé avec un fallback géré** — une phrase qu'aucun d'eux ne peut prononcer.

## Démarrage rapide en 60 secondes

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

## Pourquoi ?

| | OrcaRouter Lite | Bibliothèque LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Serveur auto-hébergé | ✓ | en tant que bibliothèque | ✗ | ✓ |
| Compatible OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-fournisseur (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Tableau de bord intégré | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (le moins cher capable) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hébergé en fallback | ✓ | ✗ | n/a | ✗ |
| Pas de Postgres / pas de Redis requis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la fonctionnalité phare

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

| Plateforme | One-click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Connectez le repo, répertoire racine = `.` |
| Docker brut | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (image bientôt) |

## Ce qu'il y a dans la boîte

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache de prompts inter-fournisseurs
- `POST /v1/messages` — **ingress de l'API Messages d'Anthropic** (Claude Code / les SDK Anthropic se connectent directement ; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **ingress de l'API Gemini** (le SDK google-genai se connecte directement ; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — catalogue de modèles découvrable (100+ modèles depuis `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — définir / lister / révoquer des clés de fournisseur chiffrées
- `GET/PUT /v1/routing` — changer la stratégie (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics locales, aucune télémétrie ne sort de la boîte
- `GET  /v1/hosted` — statut du fallback hébergé (alimente la carte « Get $5 free credit » du tableau de bord)
- `GET/POST/DELETE /v1/keys/...` — lister / faire tourner / révoquer des clés API
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

Pour cela, voyez le produit hébergé ou la (future) édition Teams.

## Tests

Construit en test-first. Chaque comportement livré ici a d'abord eu un test qui échouait.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| Slice | Tests | Quoi |
|---|---|---|
| 1. Config | 5 | chargement env, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + clé API + RoutingConfig, idempotent |
| 3. Middleware d'auth | 4 | validation bearer-token, 401 si manquant/invalide |
| 4. App factory | 3 | /health, enveloppe d'erreur, gating /v1/* |
| 5. CRUD clés de fournisseur | 5 | chiffré au repos, le plaintext ne fait jamais d'aller-retour |
| 6. Cache du routeur | 13 | assemblage de déploiement env+DB+hosted avec préséance |
| 7. Chat completion | 5 | format OpenAI, RequestLog, validation |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + mise à jour de stratégie |
| 10. Streaming | 4 | format SSE, sentinel `[DONE]`, log writeback |
| 11. Catalogue | 7 | 100+ modèles, drapeaux de capacité, pricing |
| 12. `model="auto"` | 21 | détection de capacité, le moins cher répondant aux besoins (unit + intégration) |
| 13. Économies de coût | 9 | économies vs baseline toujours-GPT-4 + comparaison hosted-auto |
| 14. Cache de prompts | 15 | cache exact-match inter-fournisseurs + intégration chat |
| 15. Benchmark | 4 | agrégation summarize() + render_markdown() |
| 16. Statut hosted | 7 | `/v1/hosted` config-source + surface URL d'inscription |
| 17. Économies hosted-auto | 3 | cas limites de `_hosted_auto_savings` sur catalogues synthétiques |
| 18. Modèles inaccessibles | 7 | la tuile « modèles inaccessibles » se vide quand hosted est actif |
| 19. Auth multi-protocole | 6 | scoping x-api-key / x-goog-api-key / ?key=, garde /v1beta, enveloppes 401 par protocole |
| 20. Anthropic `/v1/messages` | 53 | traduction requête/réponse/stream + intégration de l'ingress |
| 21. Gemini `/v1beta` | 40 | traduction incluant la normalisation schema-enum + ingress generateContent/stream |
| **Total** | **403** | |

Les lignes de slice montrent les tests ajoutés à la livraison de chaque slice ; le total est la suite complète actuelle.

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

packages/
├── litellm_adapter/    Router wrapper + 100+ model catalog
├── auth/               hashing + AES-256-GCM
└── db/                 models + engine + session
```

## Roadmap

- [x] Chat completions compatibles OpenAI
- [x] Streaming (SSE)
- [x] Routage `model="auto"` le moins cher capable
- [x] Hosted-en-upstream
- [x] BYOK chiffré au repos
- [x] Tableau de bord d'analytics local
- [x] CI (GitHub Actions)
- [x] Cache de prompts inter-fournisseurs
- [x] Intégrations Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark public + revendication d'économies
- [ ] Proxy embeddings + génération d'images

Voir [DEMO.md](./DEMO.md) pour la démo de failover.

## Licence

MIT. Voir [LICENSE](./LICENSE).
