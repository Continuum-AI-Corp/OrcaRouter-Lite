#OrcaRouter Lite

**Routeur LLM auto-hébergé avec un filet de sécurité géré.**
Compatible OpenAI. BYOK. Espace de travail unique. Streaming. `modèle="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![modèles](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![licence](https://img.shields.io/badge/license-MIT-blue)](#license)

## Langues

- [Anglais](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Allemand](./README.de.md)
- [Français](./README.fr.md)
- [Espagnol](./README.es.md)
- [Italien](./README.it.md)
- [Русский](./README.ru.md)
- [Português](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite est l'édition open source à espace de travail unique d'[OrcaRouter](https://www.orcarouter.ai). Exécutez-le sur votre ordinateur portable, expédiez-le dans votre produit ou utilisez directement « api.orcarouter.ai » hébergé pour la longue traîne de modèles pour lesquels vous ne souhaitez pas gérer les clés.

> **Pourquoi nous ?** LiteLLM est une bibliothèque ; OpenRouter est hébergé en source fermée ; Ollama est uniquement local. Nous sommes le **serveur auto-hébergé avec une solution de secours gérée** — une phrase qu'aucun d'entre eux ne peut dire.

## Démarrage rapide en 60 secondes

Deux façons d'utiliser OrcaRouter :

### Chemin A — Auto-hébergé (BYOK)

Exécutez Lite sur votre propre machine ; apportez vos propres clés de fournisseur.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL de base : `http://localhost:8000/v1`. Utilisez la clé `sk-orca-*` imprimée au démarrage.

### Chemin B — Hébergé (compte requis)

Pas de clone, pas de docker. Inscrivez-vous, obtenez une clé, pointez n'importe quel SDK OpenAI vers l'hébergement.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Compte requis.** Hosted gère le routage, la facturation et la longue traîne des fournisseurs — facturés par jeton sur votre compte OrcaRouter. Voir [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Ensuite, appelez-le depuis n'importe quel SDK OpenAI

Les exemples ci-dessous utilisent l'URL de base localhost du chemin A — remplacez-la par « https://api.orcarouter.ai/v1 » si vous êtes sur le chemin B.

<détails>
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
</détails>

<détails>
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
</détails>

<détails>
<summary><b>boucle</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</détails>

Ouvrez « http://localhost:8000/ » pour le tableau de bord : fournisseurs, routage, analyses, clés (chemin A uniquement).

## Pourquoi?

| | Léger | Bibliothèque LiteLLM | OuvrirRouter | Ollama |
|---|---|---|---|---|
| Serveur auto-hébergé | ✓ | comme bibliothèque | ✗ | ✓ |
| Compatible OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-fournisseur (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Tableau de bord intégré | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (le moins cher) | ✓ | ✗ | ✗ | n/a |
| Diffusion | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hébergé comme solution de secours | ✓ | ✗ | n/a | ✗ |
| Aucun Postgres/aucun Redis requis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la fonctionnalité de titre

Envoyez `model="auto"` et OrcaRouter sélectionne le modèle **le moins cher** parmi vos fournisseurs configurés qui répond aux exigences de capacité de la demande (outils, vision, mode JSON). Aucune règle de routage manuelle ; pas de gymnastique à taux limite ; pas d'optimisation des coûts `if x : ...` dans votre code.

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

Le modèle résolu est exposé aux appelants via l'en-tête de réponse « x-orca-resolved-model » afin que vous puissiez enregistrer/afficher ce qui a été réellement utilisé.

## Hébergé en amont (Lite + hébergé)

Vous utilisez déjà Lite ? Définissez `ORCAROUTER_API_KEY` sur votre `sk-orca-*` depuis [www.orcarouter.ai](https://www.orcarouter.ai), et l'hébergement devient un fournisseur supplémentaire dans la chaîne de routage — couvrant les modèles que vos clés locales ne font pas :

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Cas d'utilisation :
- **Essayez avant d'acheter** — aucune clé de fournisseur local n'est nécessaire
- **Journalisation locale** : l'hébergement gère le routage, Lite stocke les lignes RequestLog pour le tableau de bord
- **Failover** : les fournisseurs locaux échouent, l'hébergement est le filet de sécurité

## Streaming

Format SSE compatible OpenAI avec le cadrage standard `data: ... \n\n` et une sentinelle de terminal `[DONE]` — ajout à tout SDK qui diffuse déjà depuis OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catalogue de modèles

Plus de 100 modèles de chat sont chargés au démarrage à partir de [base de données de tarification gérée par la communauté LiteLLM] (https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — aucune liste de modèles à gérer manuellement. Chaque entrée expose :

- `id` (par exemple `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mappé sur vos clés configurées)
- Indicateurs de capacités : `supports_tools`, `supports_vision`, `supports_json_mode`
- Coût d'entrée/sortie par jeton (pilote le widget d'épargne + `model="auto"`)

`GET /v1/models` renvoie le catalogue au format OpenAI.

## Déployer ailleurs

| Plateforme | Un clic |
|---|---|
| Chemin de fer | [![Déployer sur le chemin de fer](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Rendu | Connectez le dépôt, répertoire racine = `.` |
| Docker nu | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (image à venir) |

## Qu'y a-t-il dans la boîte

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache d'invites multi-fournisseurs
- `GET /v1/models` — catalogue de modèles détectables (plus de 100 modèles de `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — définir/lister/révoquer les clés de fournisseur cryptées
- `GET/PUT /v1/routing` — stratégie de changement (`balanced` / `moins cher` / `plus rapide` / `qualité`)
- `GET /v1/analytics/{recent,spend,latency, saving,unreachable}` — analyses locales, aucune télémétrie ne sort de la boîte
- `GET /v1/hosted` — statut de secours hébergé (pilote la carte « Obtenez 5 $ de crédit gratuit » du tableau de bord)
- `GET/POST/DELETE /v1/keys/...` — liste/rotation/révoquer les clés API
- Tableau de bord d'une seule page à `/`
- SQLite par défaut ; Opt-in Postgres via `DATABASE_URL` ; Redis facultatif

### Cache d'invites multi-fournisseurs

Les requêtes déterministes (« température = 0 » ou « graine » épinglée) sont servies à partir du cache de manière répétée – fonctionnent sur **tous** les fournisseurs, pas seulement Anthropic. Le backend est Redis lorsque `REDIS_URL` est défini, sinon LRU en cours. Les accès au cache reviennent instantanément avec « x-orca-cache : HIT » et coûtent 0 $.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Widget d'épargne

`GET /v1/analytics/ saving?baseline=gpt-4o&days=7` indique ce qu'aurait coûté votre trafic sur toujours-GPT-4 par rapport à ce qu'il coûte réellement. Le tableau de bord l'affiche sous forme de vignette.

### Intégrations

Configurations déroulantes pour [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts), et tout outil qui parle le protocole OpenAI Chat Completions. Voir [`integrations/`](./integrations/).

## Ce qui n'est délibérément pas

Il s'agit de l'édition **espace de travail unique**. De par sa conception, non :
- multilocation, RBAC, SSO
- facturation, portefeuilles, points, programme partenaire
- console d'administration, journaux d'audit, confiance et sécurité
- déploiement multi-pod / Kubernetes
- email / Slack / webhooks pour les alertes

Pour ceux-ci, consultez le produit hébergé ou l’édition (à venir) Teams.

## Tests

Construit en test d'abord. Chaque comportement livré ici a d'abord connu un échec de test.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Tranche | Essais | Quoi |
|---|---|---|
| 1. Configuration | 5 | chargement de l'environnement, valeurs par défaut, `env_provider_keys()` |
| 2. Semences | 3 | espace de travail bootstrap + clé API + RoutingConfig, idempotent |
| 3. Middleware d'authentification | 4 | validation du jeton du porteur, 401 en cas de manque/invalide |
| 4. Usine d'applications | 3 | /health, enveloppe d'erreur, /v1/* gate |
| 5. Clés du fournisseur CRUD | 5 | chiffré au repos, texte en clair jamais aller-retour |
| 6. Cache du routeur | 13 | env+DB+assembly de déploiement hébergé avec priorité |
| 7. Achèvement du chat | 5 | Format OpenAI, RequestLog, validation |
| 8. Analyses | 4 | récent / dépenses / latence p50/p99 |
| 9. /v1/{modèles, clés, routage} | 8 | lister/créer/révoquer + mise à jour de la stratégie |
| 10. Diffusion | 4 | Format SSE, sentinelle `[TERMINÉ]`, réécriture du journal |
| 11. Catalog | 7 | Plus de 100 modèles, indicateurs de capacités, prix |
| 12. `model="auto"` | 21 | détection des capacités, réponse aux besoins les moins chers (unité + intégration) |
| 13. Économies de coûts | 9 | économies par rapport à la référence toujours GPT-4 + comparaison automatique hébergée |
| 14. Cache d'invite | 15 | Cache de correspondance exacte entre fournisseurs + intégration de chat |
| 15. Référence | 4 | agrégation summary() + render_markdown() |
| 16. Statut hébergé | 7 | `/v1/hosted` source de configuration + surface de l'URL d'inscription |
| 17. Économies automatiques hébergées | 3 | Cas extrêmes `_hosted_auto_ savings` sur les catalogues synthétiques |
| 18. Modèles inaccessibles | 7 | La vignette « Modèles que vous ne pouvez pas atteindre » s'efface lorsque l'hébergement est activé |
| **Total** | **127** | |

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

## Feuille de route

- [x] Fins de chat compatibles OpenAI
- [x] Streaming (SSE)
- [x] `model="auto"` routage le moins cher
- [x] Hébergé en amont
- [x] BYOK chiffré au repos
- [x] Tableau de bord d'analyse locale
- [x] CI (actions GitHub)
- [x] Mise en cache des invites entre fournisseurs
- [x] Intégrations Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Indice de référence public + demande d'épargne
- [ ] Intégrations + proxy de génération d'images

Voir [DEMO.md](./DEMO.md) pour la démonstration de basculement.

## Licence

MIT. Voir [LICENCE](./LICENCE).
