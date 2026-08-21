# OrcaRouter Lite

**Enrutador LLM autoalojado con red de seguridad gestionada.**
Compatible con OpenAI. BYOK. Workspace único. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

## Idiomas

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

OrcaRouter Lite es la edición open source de un solo workspace de [OrcaRouter](https://www.orcarouter.ai). Ejecútalo en tu portátil, intégralo en tu producto o usa directamente el `api.orcarouter.ai` alojado para la larga cola de modelos cuyas claves no quieres gestionar.

> **¿Por qué nosotros?** LiteLLM es una librería; OpenRouter es de código cerrado y alojado; Ollama es solo local. Nosotros somos el **servidor autoalojado con respaldo gestionado** — una frase que ninguno de ellos puede decir.

## Inicio rápido en 60 segundos

Dos formas de usar OrcaRouter:

### Camino A — Autoalojado (BYOK)

Ejecuta Lite en tu propia máquina; trae tus propias claves de proveedor.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# añade al menos una: OPENAI_API_KEY=sk-...  (o ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Usa la clave `sk-orca-*` que se imprime al arrancar.

### Camino B — Alojado (requiere cuenta)

Sin clonar, sin docker. Regístrate, obtén una clave, apunta cualquier SDK de OpenAI al servicio alojado.

```bash
# 1. Regístrate en https://www.orcarouter.ai y copia tu clave sk-orca-*
# 2. Usa https://api.orcarouter.ai/v1 como URL base
```

**Requiere cuenta.** El servicio alojado se encarga del enrutamiento, la facturación y la larga cola de proveedores — facturado por token en tu cuenta de OrcaRouter. Consulta [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Luego invócalo desde cualquier SDK de OpenAI

Los ejemplos de abajo usan la URL base de localhost del Camino A — cámbiala por `https://api.orcarouter.ai/v1` si estás en el Camino B.

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

Abre `http://localhost:8000/` para el panel — proveedores, enrutamiento, analítica, claves (solo Camino A).

## ¿Por qué?

| | OrcaRouter Lite | Librería LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Servidor autoalojado | ✓ | como librería | ✗ | ✓ |
| Compatible con OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multiproveedor (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Panel integrado | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (el más barato capaz) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Alojado como respaldo | ✓ | ✗ | n/a | ✗ |
| Sin Postgres / sin Redis requerido | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la característica estrella

Envía `model="auto"` y OrcaRouter elige el modelo **más barato** entre los proveedores configurados que cumpla los requisitos de capacidad de la solicitud (tools, vision, modo JSON). Sin reglas de enrutamiento manuales; sin acrobacias con rate-limits; sin optimización de costes con `if x: ...` en tu código.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → enruta al modelo más barato compatible con VISION que cubran tus claves
```

El modelo resuelto se expone de vuelta a quien llama a través de la cabecera de respuesta `x-orca-resolved-model`, para que puedas registrar/mostrar lo que realmente se usó.

## Alojado como upstream (Lite + alojado)

¿Ya tienes Lite en marcha? Configura `ORCAROUTER_API_KEY` con tu `sk-orca-*` de [www.orcarouter.ai](https://www.orcarouter.ai) y el alojado pasa a ser un proveedor más en la cadena de enrutamiento — cubriendo modelos que tus claves locales no tienen:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casos de uso:
- **Probar antes de comprar** — sin necesidad de claves de proveedor locales
- **Logging local** — el alojado gestiona el enrutamiento, Lite guarda filas de RequestLog para el panel
- **Failover** — los proveedores locales fallan, el alojado es la red de seguridad

## Streaming

Formato SSE compatible con OpenAI con el framing estándar `data: ... \n\n` y un sentinel terminal `[DONE]` — drop-in para cualquier SDK que ya transmita desde OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Endpoints de protocolos nativos (Anthropic + Gemini)

Lite habla tres protocolos de entrada sobre un único pipeline de enrutamiento. Los clientes que solo hablan los formatos wire de Anthropic o Gemini se conectan directamente — sin necesidad de un SDK de OpenAI:

```bash
# Claude Code, apuntando a Lite (sin sufijo /v1 en la URL base)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# SDK google-genai, apuntando a Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Las solicitudes se traducen en la entrada hacia el mismo pipeline interno, así que `model="auto"`, la caché de prompts entre proveedores (compartida entre protocolos), las estrategias de enrutamiento y el panel de analítica funcionan todos de forma idéntica. Guías: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Catálogo de modelos

Se cargan más de 100 modelos de chat al arrancar desde la [base de datos de precios mantenida por la comunidad de LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — sin lista de modelos que mantener manualmente. Cada entrada expone:

- `id` (p. ej. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapeado a tus claves configuradas)
- Flags de capacidad: `supports_tools`, `supports_vision`, `supports_json_mode`
- Coste por token de entrada/salida (alimenta el widget de ahorro + `model="auto"`)

`GET /v1/models` devuelve el catálogo en formato OpenAI.

## Despliegue en otros sitios

| Plataforma | One-click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Conecta el repo, directorio raíz = `.` |
| Docker pelado | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (imagen próximamente) |

## Qué incluye

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + caché de prompts entre proveedores
- `POST /v1/messages` — **ingress de la API Messages de Anthropic** (Claude Code / los SDK de Anthropic se conectan directamente; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **ingress de la API de Gemini** (el SDK google-genai se conecta directamente; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — catálogo de modelos descubrible (100+ modelos desde `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — crea / lista / revoca claves de proveedor cifradas
- `GET/PUT /v1/routing` — cambia la estrategia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analítica local, sin telemetría que salga de la caja
- `GET  /v1/hosted` — estado del respaldo alojado (alimenta la tarjeta "Get $5 free credit" del panel)
- `GET/POST/DELETE /v1/keys/...` — lista / rota / revoca claves de API
- Panel de una sola página en `/`
- SQLite por defecto; Postgres opt-in vía `DATABASE_URL`; Redis opcional

### Caché de prompts entre proveedores

Las solicitudes deterministas (`temperature=0` o `seed` fijado) se sirven desde caché en repeticiones — funciona con **todos** los proveedores, no solo Anthropic. El backend es Redis si `REDIS_URL` está definido, en caso contrario un LRU en proceso. Los aciertos de caché se devuelven al instante con `x-orca-cache: HIT` y cuestan $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # mismo payload otra vez
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servido desde caché, sin llamada upstream
```

### Widget de ahorros

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` informa de lo que tu tráfico habría costado con siempre-GPT-4 frente a lo que costó realmente. El panel lo muestra como una tarjeta.

### Integraciones

Configuraciones drop-in para [Claude Code](./integrations/claude-code.md), [SDK de Gemini](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) y cualquier herramienta que hable el protocolo de Chat Completions de OpenAI — además de los formatos wire nativos de Anthropic y Gemini. Consulta [`integrations/`](./integrations/).

## Lo que deliberadamente no incluye

Esta es la edición de **un solo workspace**. Por diseño, sin:
- multi-tenant, RBAC, SSO
- facturación, monederos, puntos, programa de partners
- consola de administración, logs de auditoría, trust & safety
- despliegue multi-pod / Kubernetes
- email / Slack / webhooks para alertas

Para eso, consulta el producto alojado o la (próxima) edición Teams.

## Pruebas

Construido con test-first. Cada comportamiento entregado aquí tuvo primero un test fallando.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| Slice | Tests | Qué |
|---|---|---|
| 1. Config | 5 | carga de env, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + clave API + RoutingConfig, idempotente |
| 3. Middleware de auth | 4 | validación de bearer-token, 401 si falta/es inválida |
| 4. App factory | 3 | /health, sobre de error, gating /v1/* |
| 5. CRUD de claves de proveedor | 5 | cifrado en reposo, el plaintext nunca va y vuelve |
| 6. Caché del router | 13 | ensamblado de despliegue env+DB+alojado con precedencia |
| 7. Chat completion | 5 | formato OpenAI, RequestLog, validación |
| 8. Analítica | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + actualización de estrategia |
| 10. Streaming | 4 | formato SSE, sentinel `[DONE]`, log writeback |
| 11. Catálogo | 7 | 100+ modelos, flags de capacidad, pricing |
| 12. `model="auto"` | 21 | detección de capacidades, el más barato que cumple (unit + integración) |
| 13. Ahorro de costes | 9 | ahorros vs baseline siempre-GPT-4 + comparación hosted-auto |
| 14. Caché de prompts | 15 | caché de coincidencia exacta entre proveedores + integración chat |
| 15. Benchmark | 4 | agregación de summarize() + render_markdown() |
| 16. Estado de hosted | 7 | `/v1/hosted` config-source + superficie de URL de signup |
| 17. Ahorros de hosted-auto | 3 | casos límite de `_hosted_auto_savings` en catálogos sintéticos |
| 18. Modelos inalcanzables | 7 | la tarjeta "modelos que no puedes alcanzar" se vacía cuando hosted está activo |
| 19. Auth multiprotocolo | 6 | scoping de x-api-key / x-goog-api-key / ?key=, guard de /v1beta, sobres 401 por protocolo |
| 20. Anthropic `/v1/messages` | 53 | traducción de solicitud/respuesta/stream + integración del ingress |
| 21. Gemini `/v1beta` | 40 | traducción incl. normalización de schema-enum + ingress de generateContent/stream |
| **Total** | **403** | |

Las filas de slice muestran los tests añadidos cuando se entregó cada slice; el total es la suite completa actual.

## Arquitectura

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

- [x] Chat completions compatibles con OpenAI
- [x] Streaming (SSE)
- [x] Enrutamiento del más barato capaz con `model="auto"`
- [x] Hosted-como-upstream
- [x] BYOK cifrado en reposo
- [x] Panel local de analítica
- [x] CI (GitHub Actions)
- [x] Caché de prompts entre proveedores
- [x] Integraciones con Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark público + reclamo de ahorros
- [ ] Proxy de embeddings + generación de imágenes

Consulta [DEMO.md](./DEMO.md) para la demo de failover.

## Licencia

MIT. Consulta [LICENSE](./LICENSE).
