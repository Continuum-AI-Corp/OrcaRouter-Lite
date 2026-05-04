# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | [日本語](./README.ja.md) | [한국어](./README.ko.md) | [Deutsch](./README.de.md) | [Italiano](./README.it.md) | **Français** | [Español](./README.es.md) | [العربية](./README.ar.md)

**Routeur LLM auto-hébergé avec un filet de sécurité géré.**
Compatible OpenAI. BYOK. Espace de travail unique. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#tests)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#catalogue-de-modèles)
[![license](https://img.shields.io/badge/license-MIT-blue)](#licence)

OrcaRouter Lite est l'édition open-source à espace de travail unique d'[OrcaRouter](https://www.orcarouter.ai). Exécutez-le sur votre ordinateur portable, livrez-le dans votre produit, ou utilisez `api.orcarouter.ai` hébergé directement pour la longue traîne de modèles dont vous ne voulez pas gérer les clés.

> **Pourquoi nous ?** LiteLLM est une bibliothèque ; OpenRouter est hébergé closed-source ; Ollama est local uniquement. Nous sommes le **serveur auto-hébergé avec basculement géré** — une phrase qu'aucun d'eux ne peut dire.

## Démarrage rapide en 60 secondes

Deux façons d'utiliser OrcaRouter :

### Voie A — Auto-hébergé (BYOK)

Exécutez Lite sur votre propre machine ; apportez vos propres clés de fournisseurs.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# ajoutez au moins une : OPENAI_API_KEY=sk-...  (ou ORCAROUTER_API_KEY=...)

docker compose up
# logs : ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL de base : `http://localhost:8000/v1`. Utilisez la clé `sk-orca-*` affichée au démarrage.

### Voie B — Hébergé (compte requis)

Pas de clone, pas de docker. Inscrivez-vous, obtenez une clé, pointez n'importe quel SDK OpenAI vers hébergé.

```bash
# 1. Inscrivez-vous sur https://www.orcarouter.ai et copiez votre clé sk-orca-*
# 2. Utilisez https://api.orcarouter.ai/v1 comme URL de base
```

**Compte requis.** Hébergé gère le routage, la facturation et la longue traîne de fournisseurs — facturé par token sur votre compte OrcaRouter. Voir [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

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
    messages=[{"role": "user", "content": "Bonjour !"}],
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
  messages: [{ role: "user", content: "Bonjour !" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"Bonjour !"}]}'
```
</details>

Ouvrez `http://localhost:8000/` pour le tableau de bord — fournisseurs, routage, analyses, clés (Voie A uniquement).

## Pourquoi ?

| | Lite | Bibliothèque LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Serveur auto-hébergé | ✓ | en tant que bibliothèque | ✗ | ✓ |
| Compatible OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-fournisseurs (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Tableau de bord intégré | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (le moins cher capable) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hébergé-comme-fallback | ✓ | ✗ | n/a | ✗ |
| Pas de Postgres / pas de Redis requis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la fonctionnalité phare

Envoyez `model="auto"` et OrcaRouter choisit le modèle **le moins cher** parmi les fournisseurs configurés qui répond aux exigences de capacité de la requête (outils, vision, mode JSON). Pas de règles de routage manuelles ; pas d'acrobaties de rate-limit ; pas d'optimisation de coût `if x: ...` dans votre code.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "Qu'y a-t-il sur cette image ?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → route vers le modèle compatible VISION le moins cher couvert par vos clés
```

Le modèle résolu est exposé aux appelants via l'en-tête de réponse `x-orca-resolved-model` afin que vous puissiez logger/afficher ce qui a été réellement utilisé.

## Hébergé en amont (Lite + hébergé)

Vous exécutez déjà Lite ? Définissez `ORCAROUTER_API_KEY` sur votre `sk-orca-*` de [www.orcarouter.ai](https://www.orcarouter.ai), et hébergé devient un fournisseur de plus dans la chaîne de routage — couvrant les modèles que vos clés locales ne couvrent pas :

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Cas d'usage :
- **Essayer avant d'acheter** — pas de clés de fournisseurs locaux nécessaires
- **Logging local** — hébergé gère le routage, Lite stocke les lignes RequestLog pour le tableau de bord
- **Failover** — les fournisseurs locaux échouent, hébergé est le filet de sécurité

## Streaming

Format SSE compatible OpenAI avec le framing standard `data: ... \n\n` et un sentinel terminal `[DONE]` — drop-in pour n'importe quel SDK qui stream déjà depuis OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Raconte-moi une histoire"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catalogue de modèles

100+ modèles de chat sont chargés au démarrage depuis [la base de données de prix maintenue par la communauté de LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — pas de liste de modèles à maintenir manuellement. Chaque entrée expose :

- `id` (ex. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mappé à vos clés configurées)
- Drapeaux de capacité : `supports_tools`, `supports_vision`, `supports_json_mode`
- Coût d'entrée/sortie par token (alimente le widget d'économies + `model="auto"`)

`GET /v1/models` retourne le catalogue au format OpenAI.

## Déployer ailleurs

| Plateforme | Un clic |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Connectez le dépôt, dir racine = `.` |
| Docker nu | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (image bientôt) |

## Ce qu'il y a dans la boîte

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache de prompt cross-fournisseur
- `GET  /v1/models` — catalogue de modèles découvrable (100+ modèles depuis `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — définir / lister / révoquer les clés de fournisseurs chiffrées
- `GET/PUT /v1/routing` — changer la stratégie (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analyses locales, aucune télémétrie ne quitte la boîte
- `GET  /v1/hosted` — statut de fallback hébergé (alimente la carte "Obtenez 5 $ de crédit gratuit" du tableau de bord)
- `GET/POST/DELETE /v1/keys/...` — lister / faire tourner / révoquer les clés API
- Tableau de bord single-page sur `/`
- SQLite par défaut ; Postgres opt-in via `DATABASE_URL` ; Redis optionnel

### Cache de prompt cross-fournisseur

Les requêtes déterministes (`temperature=0` ou `seed` épinglé) sont servies depuis le cache lors d'une répétition — fonctionne sur **tous** les fournisseurs, pas seulement Anthropic. Le backend est Redis quand `REDIS_URL` est défini, LRU in-process sinon. Les hits du cache renvoient instantanément avec `x-orca-cache: HIT` et coûtent 0 $.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # même payload à nouveau
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servi depuis le cache, pas d'appel upstream
```

### Widget d'économies

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` rapporte ce qu'aurait coûté votre trafic en toujours-GPT-4 vs ce qu'il a réellement coûté. Le tableau de bord l'affiche comme une tuile.

### Intégrations

Configurations drop-in pour [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts), et tout outil qui parle le protocole OpenAI Chat Completions. Voir [`integrations/`](./integrations/).

## Ce qui n'est délibérément pas inclus

C'est l'édition **espace de travail unique**. Par conception, pas de :
- multi-tenancy, RBAC, SSO
- facturation, portefeuilles, points, programme partenaire
- console admin, journaux d'audit, trust & safety
- déploiement multi-pod / Kubernetes
- email / Slack / webhooks pour les alertes

Pour cela, voir le produit hébergé ou l'édition Teams (à venir).

## Tests

Construit test-first. Chaque comportement livré ici avait d'abord un test qui échouait.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Slice | Tests | Quoi |
|---|---|---|
| 1. Configuration | 5 | chargement env, valeurs par défaut, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + clé API + RoutingConfig, idempotent |
| 3. Middleware Auth | 4 | validation bearer-token, 401 sur manquant/invalide |
| 4. App factory | 3 | /health, enveloppe d'erreur, gating /v1/* |
| 5. CRUD clés fournisseurs | 5 | chiffré au repos, le plaintext ne fait jamais d'aller-retour |
| 6. Cache router | 13 | assemblage de déploiement env+DB+hébergé avec préséance |
| 7. Chat completion | 5 | format OpenAI, RequestLog, validation |
| 8. Analyses | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | lister/créer/révoquer + mise à jour de stratégie |
| 10. Streaming | 4 | format SSE, sentinel `[DONE]`, réécriture de log |
| 11. Catalogue | 7 | 100+ modèles, drapeaux de capacité, prix |
| 12. `model="auto"` | 21 | détection de capacité, le moins cher répondant aux besoins (unitaire + intégration) |
| 13. Économies de coûts | 9 | économies vs baseline toujours-GPT-4 + comparaison hosted-auto |
| 14. Cache de prompt | 15 | cache cross-fournisseur exact-match + intégration chat |
| 15. Benchmark | 4 | agrégation summarize() + render_markdown() |
| 16. Statut hébergé | 7 | source de configuration `/v1/hosted` + surface URL d'inscription |
| 17. Économies hosted-auto | 3 | cas limites `_hosted_auto_savings` sur des catalogues synthétiques |
| 18. Modèles inaccessibles | 7 | la tuile "modèles que vous ne pouvez pas atteindre" se vide quand hébergé est activé |
| **Total** | **127** | |

## Architecture

```
app/
├── main.py             Factory FastAPI + lifespan + montage SPA
├── config.py           Paramètres (~15 champs)
├── deps.py             Helpers DI
├── seed.py             Bootstrap premier lancement
├── auto_routing.py     Capacité model="auto" + scoring de coût
├── router_cache.py     Routeur single-workspace
├── prompt_cache.py     Cache cross-fournisseur exact-match (Redis ou LRU in-memory)
├── schemas.py          Schéma de requête compatible OpenAI
├── middleware/auth.py  Validation sk-orca-*
└── routes/
    ├── chat.py         /v1/chat/completions  (blocking + streaming)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      Configuration de stratégie
    ├── analytics.py    Recent / spend / latency / savings / unreachable
    ├── keys.py         Lister / faire tourner / révoquer les clés API
    ├── hosted.py       /v1/hosted — statut de fallback hébergé pour le tableau de bord
    └── health.py

packages/
├── litellm_adapter/    Wrapper de routeur + catalogue 100+ modèles
├── auth/               Hashing + AES-256-GCM
└── db/                 Modèles + engine + session
```

## Feuille de route

- [x] Chat completions compatibles OpenAI
- [x] Streaming (SSE)
- [x] Routage `model="auto"` le-moins-cher-capable
- [x] Hébergé-en-amont
- [x] BYOK chiffré au repos
- [x] Tableau de bord d'analyses local
- [x] CI (GitHub Actions)
- [x] Cache de prompt cross-fournisseur
- [x] Intégrations Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark public + revendication d'économies
- [ ] Embeddings + proxy de génération d'images

Voir [DEMO.md](./DEMO.md) pour la démo de failover.

## Licence

MIT. Voir [LICENSE](./LICENSE).
