# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | [日本語](./README.ja.md) | [한국어](./README.ko.md) | [Deutsch](./README.de.md) | [Italiano](./README.it.md) | [Français](./README.fr.md) | **Español** | [العربية](./README.ar.md)

**Router LLM auto-alojado con red de seguridad gestionada.**
Compatible con OpenAI. BYOK. Espacio de trabajo único. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#pruebas)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#catálogo-de-modelos)
[![license](https://img.shields.io/badge/license-MIT-blue)](#licencia)

OrcaRouter Lite es la edición open-source de espacio de trabajo único de [OrcaRouter](https://www.orcarouter.ai). Ejecútalo en tu portátil, distribúyelo en tu producto, o usa el `api.orcarouter.ai` alojado directamente para la cola larga de modelos para los que no quieres gestionar claves.

> **¿Por qué nosotros?** LiteLLM es una librería; OpenRouter es alojado de código cerrado; Ollama es solo local. Somos el **servidor auto-alojado con respaldo gestionado** — una frase que ninguno de ellos puede decir.

## Inicio rápido en 60 segundos

Dos formas de usar OrcaRouter:

### Camino A — Auto-alojado (BYOK)

Ejecuta Lite en tu propia máquina; trae tus propias claves de proveedor.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# añade al menos una: OPENAI_API_KEY=sk-...  (o ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Usa la clave `sk-orca-*` impresa al iniciar.

### Camino B — Alojado (cuenta requerida)

Sin clonar, sin docker. Regístrate, obtén una clave, apunta cualquier SDK de OpenAI a alojado.

```bash
# 1. Regístrate en https://www.orcarouter.ai y copia tu clave sk-orca-*
# 2. Usa https://api.orcarouter.ai/v1 como URL base
```

**Cuenta requerida.** Alojado maneja enrutamiento, facturación y la cola larga de proveedores — facturado por token en tu cuenta de OrcaRouter. Ver [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Luego llámalo desde cualquier SDK de OpenAI

Los ejemplos a continuación usan la URL base localhost del Camino A — sustituye por `https://api.orcarouter.ai/v1` si estás en el Camino B.

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
    messages=[{"role": "user", "content": "¡Hola!"}],
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
  messages: [{ role: "user", content: "¡Hola!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"¡Hola!"}]}'
```
</details>

Abre `http://localhost:8000/` para el panel — proveedores, enrutamiento, analíticas, claves (solo Camino A).

## ¿Por qué?

| | Lite | Librería LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Servidor auto-alojado | ✓ | como librería | ✗ | ✓ |
| Compatible con OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-proveedor (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Panel integrado | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (más barato capaz) | ✓ | ✗ | ✗ | n/d |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/d |
| Alojado-como-respaldo | ✓ | ✗ | n/d | ✗ |
| Sin Postgres / sin Redis requeridos | ✓ | n/d | n/d | ✓ |

## `model="auto"` — la característica estrella

Envía `model="auto"` y OrcaRouter elige el modelo **más barato** entre tus proveedores configurados que cumpla con los requisitos de capacidad de la solicitud (herramientas, visión, modo JSON). Sin reglas de enrutamiento manuales; sin gimnasia de límites de tasa; sin optimización de costos `if x: ...` en tu código.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "¿Qué hay en esta imagen?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → enruta al modelo capaz de VISION más barato cubierto por tus claves
```

El modelo resuelto se expone a los llamadores a través de la cabecera de respuesta `x-orca-resolved-model` para que puedas registrar/mostrar lo que realmente se usó.

## Alojado como upstream (Lite + alojado)

¿Ya estás ejecutando Lite? Configura `ORCAROUTER_API_KEY` con tu `sk-orca-*` de [www.orcarouter.ai](https://www.orcarouter.ai), y alojado se convierte en un proveedor más en la cadena de enrutamiento — cubriendo modelos que tus claves locales no cubren:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casos de uso:
- **Probar antes de comprar** — no se necesitan claves de proveedores locales
- **Registro local** — alojado maneja el enrutamiento, Lite almacena filas RequestLog para el panel
- **Conmutación por error** — los proveedores locales fallan, alojado es la red de seguridad

## Streaming

Formato SSE compatible con OpenAI con el framing estándar `data: ... \n\n` y un centinela terminal `[DONE]` — drop-in para cualquier SDK que ya haga streaming desde OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Cuéntame una historia"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catálogo de modelos

100+ modelos de chat se cargan al iniciar desde [la base de datos de precios mantenida por la comunidad de LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — sin lista de modelos para mantener manualmente. Cada entrada expone:

- `id` (ej. `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapeado a tus claves configuradas)
- Banderas de capacidad: `supports_tools`, `supports_vision`, `supports_json_mode`
- Costo de entrada/salida por token (impulsa el widget de ahorro + `model="auto"`)

`GET /v1/models` devuelve el catálogo en formato OpenAI.

## Desplegar en otro lugar

| Plataforma | Un clic |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Conecta el repo, dir raíz = `.` |
| Docker desnudo | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (imagen próximamente) |

## Qué hay en la caja

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + caché de prompts cross-proveedor
- `GET  /v1/models` — catálogo de modelos descubrible (100+ modelos desde `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — establecer / listar / revocar claves de proveedor cifradas
- `GET/PUT /v1/routing` — cambiar estrategia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analíticas locales, sin telemetría que salga de la caja
- `GET  /v1/hosted` — estado de respaldo alojado (impulsa la tarjeta "Obtén $5 de crédito gratis" del panel)
- `GET/POST/DELETE /v1/keys/...` — listar / rotar / revocar claves API
- Panel single-page en `/`
- SQLite por defecto; Postgres opt-in vía `DATABASE_URL`; Redis opcional

### Caché de prompts cross-proveedor

Las solicitudes deterministas (`temperature=0` o `seed` fijada) se sirven desde caché en repetición — funciona en **todos** los proveedores, no solo Anthropic. El backend es Redis cuando `REDIS_URL` está configurado, LRU en proceso de lo contrario. Los aciertos de caché regresan instantáneamente con `x-orca-cache: HIT` y cuestan $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # mismo payload de nuevo
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servido desde caché, sin llamada upstream
```

### Widget de ahorro

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` reporta lo que tu tráfico habría costado en siempre-GPT-4 vs lo que realmente costó. El panel lo muestra como una baldosa.

### Integraciones

Configuraciones drop-in para [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts), y cualquier herramienta que hable el protocolo OpenAI Chat Completions. Ver [`integrations/`](./integrations/).

## Lo que deliberadamente no hay

Esta es la edición de **espacio de trabajo único**. Por diseño, no hay:
- multi-tenancy, RBAC, SSO
- facturación, billeteras, puntos, programa de socios
- consola de admin, registros de auditoría, trust & safety
- despliegue multi-pod / Kubernetes
- email / Slack / webhooks para alertas

Para eso, ver el producto alojado o la edición Teams (próximamente).

## Pruebas

Construido test-first. Cada comportamiento enviado aquí tuvo primero una prueba que falló.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Slice | Pruebas | Qué |
|---|---|---|
| 1. Configuración | 5 | carga de env, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + clave API + RoutingConfig, idempotente |
| 3. Middleware Auth | 4 | validación bearer-token, 401 en faltante/inválido |
| 4. App factory | 3 | /health, sobre de error, gating /v1/* |
| 5. CRUD claves de proveedor | 5 | cifrado en reposo, el plaintext nunca hace ida y vuelta |
| 6. Caché de router | 13 | ensamblaje de despliegue env+DB+alojado con precedencia |
| 7. Chat completion | 5 | formato OpenAI, RequestLog, validación |
| 8. Analíticas | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | listar/crear/revocar + actualización de estrategia |
| 10. Streaming | 4 | formato SSE, centinela `[DONE]`, reescritura de log |
| 11. Catálogo | 7 | 100+ modelos, banderas de capacidad, precios |
| 12. `model="auto"` | 21 | detección de capacidad, más-barato-cumpliendo-necesidades (unitario + integración) |
| 13. Ahorro de costos | 9 | ahorros vs baseline siempre-GPT-4 + comparación hosted-auto |
| 14. Caché de prompts | 15 | caché cross-proveedor exact-match + integración chat |
| 15. Benchmark | 4 | agregación summarize() + render_markdown() |
| 16. Estado alojado | 7 | `/v1/hosted` config-source + superficie URL de registro |
| 17. Ahorros hosted-auto | 3 | casos límite `_hosted_auto_savings` en catálogos sintéticos |
| 18. Modelos inalcanzables | 7 | la baldosa "modelos que no puedes alcanzar" se vacía cuando alojado está activo |
| **Total** | **127** | |

## Arquitectura

```
app/
├── main.py             Factory FastAPI + lifespan + montaje SPA
├── config.py           Settings (~15 campos)
├── deps.py             Helpers DI
├── seed.py             Bootstrap primer arranque
├── auto_routing.py     Capacidad model="auto" + scoring de costo
├── router_cache.py     Router single-workspace
├── prompt_cache.py     Caché cross-proveedor exact-match (Redis o LRU en memoria)
├── schemas.py          Schema de solicitud compatible con OpenAI
├── middleware/auth.py  Validación sk-orca-*
└── routes/
    ├── chat.py         /v1/chat/completions  (blocking + streaming)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      Configuración de estrategia
    ├── analytics.py    Recent / spend / latency / savings / unreachable
    ├── keys.py         Listar / rotar / revocar claves API
    ├── hosted.py       /v1/hosted — estado de respaldo alojado para el panel
    └── health.py

packages/
├── litellm_adapter/    Wrapper de router + catálogo 100+ modelos
├── auth/               Hashing + AES-256-GCM
└── db/                 Modelos + engine + sesión
```

## Hoja de ruta

- [x] Chat completions compatibles con OpenAI
- [x] Streaming (SSE)
- [x] Enrutamiento `model="auto"` más-barato-capaz
- [x] Alojado-como-upstream
- [x] BYOK cifrado en reposo
- [x] Panel de analíticas local
- [x] CI (GitHub Actions)
- [x] Caché de prompts cross-proveedor
- [x] Integraciones Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark público + reclamación de ahorros
- [ ] Embeddings + proxy de generación de imágenes

Ver [DEMO.md](./DEMO.md) para la demo de failover.

## Licencia

MIT. Ver [LICENSE](./LICENSE).
