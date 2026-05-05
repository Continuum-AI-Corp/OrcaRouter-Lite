#OrcaRouter Lite

**Enrutador LLM autohospedado con una red de seguridad administrada.**
Compatible con OpenAI. Bien. Espacio de trabajo único. Transmisión. `modelo="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![pruebas](https://img.shields.io/badge/tests-127_passing-brightgreen)](#pruebas)
[![modelos](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![licencia](https://img.shields.io/badge/license-MIT-blue)](#licencia)

## Idiomas

- [Inglés](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Deutsch](./README.de.md)
- [Francés](./README.fr.md)
- [Español](./README.es.md)
- [Italiano](./README.it.md)
- [Русский](./README.ru.md)
- [Português](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite es la edición de código abierto para un solo espacio de trabajo de [OrcaRouter](https://www.orcarouter.ai). Ejecútelo en su computadora portátil, envíelo en su producto o use `api.orcarouter.ai` alojado directamente para la larga cola de modelos para los que no desea administrar claves.

> **¿Por qué nosotros?** LiteLLM es una biblioteca; OpenRouter está alojado en código cerrado; Ollama es sólo local. Somos el **servidor autohospedado con un respaldo administrado**, una frase que ninguno de ellos puede decir.

## Inicio rápido de 60 segundos

Dos formas de utilizar OrcaRouter:

### Ruta A: autohospedado (BYOK)

Ejecute Lite en su propia máquina; traiga sus propias claves de proveedor.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Utilice la clave `sk-orca-*` impresa al inicio.

### Ruta B: alojada (se requiere cuenta)

Sin clon, sin ventana acoplable. Regístrese, obtenga una clave, apunte cualquier SDK de OpenAI al alojamiento.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Se requiere cuenta.** Hosted maneja el enrutamiento, la facturación y la larga cola de proveedores: se factura por token en su cuenta OrcaRouter. Consulte [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Luego llámalo desde cualquier SDK de OpenAI

Los ejemplos a continuación utilizan la URL base del host local de la Ruta A; cámbiela por `https://api.orcarouter.ai/v1` si está en la Ruta B.

<detalles>
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
</detalles>

<detalles>
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
</detalles>

<detalles>
<summary><b>rizo</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</detalles>

Abra `http://localhost:8000/` para acceder al panel: proveedores, enrutamiento, análisis, claves (solo ruta A).

## ¿Por qué?

| | Lite | Biblioteca LiteLLM | Enrutador abierto | Ollamá |
|---|---|---|---|---|
| Servidor autohospedado | ✓ | como biblioteca | ✗ | ✓ |
| Compatible con OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multiproveedor (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Tablero incorporado | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (el más barato) | ✓ | ✗ | ✗ | n/a |
| Transmisión | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Alojado como respaldo | ✓ | ✗ | n/a | ✗ |
| No se requiere Postgres/no Redis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — la característica del título

Envíe `model="auto"` y OrcaRouter elegirá el modelo **más barato** en sus proveedores configurados que cumpla con los requisitos de capacidad de la solicitud (herramientas, visión, modo JSON). Sin reglas de enrutamiento manuales; gimnasia sin límite de ritmo; no hay optimización de costos `if x: ...` en su código.

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

El modelo resuelto se expone a las personas que llaman a través del encabezado de respuesta `x-orca-resolved-model` para que pueda registrar/mostrar lo que realmente se usó.

## Alojado como upstream (Lite + alojado)

¿Ya estás ejecutando Lite? Configure `ORCAROUTER_API_KEY` en su `sk-orca-*` de [www.orcarouter.ai](https://www.orcarouter.ai) y hosting se convierte en un proveedor más en la cadena de enrutamiento, cubriendo modelos que sus claves locales no cubren:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casos de uso:
- **Pruebe antes de comprar**: no se necesitan claves de proveedor local
- **Registro local**: el alojamiento gestiona el enrutamiento, Lite almacena las filas de RequestLog para el panel
- **Conmutación por error**: los proveedores locales fallan, el alojamiento es la red de seguridad

## Transmisión

Formato SSE compatible con OpenAI con el marco estándar `datos: ... \n\n` y un terminal centinela `[DONE]`: complemento para cualquier SDK que ya transmita desde OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catálogo de modelos

Se cargan más de 100 modelos de chat al inicio desde [la base de datos de precios mantenida por la comunidad de LiteLLM] (https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json): no hay una lista de modelos que mantener manualmente. Cada entrada expone:

- `id` (por ejemplo, `gpt-4o`, `claude-3-5-sonnet-latest`)
- `proveedor` (asignado a sus claves configuradas)
- Indicadores de capacidad: `supports_tools`, `supports_vision`, `supports_json_mode`
- Costo de entrada/salida por token (impulsa el widget de ahorro + `model="auto"`)

`GET /v1/models` devuelve el catálogo en formato OpenAI.

## Implementar en otro lugar

| Plataforma | Un clic |
|---|---|
| Ferrocarril | [![Implementar en ferrocarril](https://railway.app/button.svg)](https://railway.app/new/template) |
| volar.io | `lanzamiento de mosca --dockerfile Dockerfile` |
| Renderizar | Conecte el repositorio, directorio raíz = `.` |
| Docker desnudo | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (imagen próximamente) |

## ¿Qué hay en la caja?

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + caché de mensajes entre proveedores
- `GET /v1/models` — catálogo de modelos reconocibles (más de 100 modelos de `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — establecer/enumerar/revocar claves de proveedor cifradas
- `GET/PUT /v1/routing` — cambiar estrategia (`equilibrado` / `más barato` / `más rápido` / `calidad`)
- `GET /v1/analytics/{recent,spend,latency, Savings,unreachable}`: análisis local, sin telemetría sale del cuadro
- `GET /v1/hosted` — estado de respaldo alojado (controla la tarjeta "Obtenga $5 de crédito gratis" en el panel de control)
- `GET/POST/DELETE /v1/keys/...` — enumerar/rotar/revocar claves API
- Panel de control de una sola página en `/`
- SQLite por defecto; Optar por Postgres a través de `DATABASE_URL`; Redis opcional

### Caché de avisos entre proveedores

Las solicitudes deterministas (`temperatura=0` o `semilla` anclada) se atienden desde la caché una vez repetidas; funciona en **todos** los proveedores, no solo en Anthropic. El backend es Redis cuando se establece `REDIS_URL`; en caso contrario, LRU en proceso. Los hits de caché regresan instantáneamente con `x-orca-cache: HIT` y cuestan $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Widget de ahorro

`GET /v1/analytics/ Savings?baseline=gpt-4o&days=7` informa cuánto habría costado su tráfico en siempre-GPT-4 frente a lo que realmente costó. El panel lo muestra como un mosaico.

### Integraciones

Configuraciones directas para [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) y cualquier herramienta que hable el protocolo OpenAI Chat Completions. Consulte [`integraciones/`](./integraciones/).

## Lo que no es deliberadamente

Esta es la edición de **espacio de trabajo único**. Por diseño, no:
- multiinquilino, RBAC, SSO
- facturación, billeteras, puntos, programa de socios
- consola de administración, registros de auditoría, confianza y seguridad
- implementación de múltiples pods/Kubernetes
- correo electrónico/Slack/webhooks para alertas

Para ellos, consulte el producto alojado o la (próxima) edición de Teams.

## Pruebas

Prueba construida primero. Cada comportamiento enviado aquí tuvo primero una prueba fallida.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Rebanada | Pruebas | Qué |
|---|---|---|
| 1. Configuración | 5 | carga de entorno, valores predeterminados, `env_provider_keys()` |
| 2. Semilla | 3 | espacio de trabajo de arranque + clave API + RoutingConfig, idempotente |
| 3. Middleware de autenticación | 4 | validación de token de portador, 401 si falta/no es válido |
| 4. Fábrica de aplicaciones | 3 | /health, sobre de error, /v1/* puerta |
| 5. Claves de proveedor CRUD | 5 | cifrado en reposo, texto sin formato nunca de ida y vuelta |
| 6. Caché del enrutador | 13 | env+DB+ensamblado de implementación alojado con prioridad |
| 7. Finalización del chat | 5 | Formato OpenAI, RequestLog, validación |
| 8. Análisis | 4 | reciente / gasto / latencia p50/p99 |
| 9. /v1/{modelos,claves,enrutamiento} | 8 | lista/crear/revocar + actualización de estrategia |
| 10. Transmisión | 4 | Formato SSE, centinela `[DONE]`, reescritura de registros |
| 11. Catálogo | 7 | Más de 100 modelos, indicadores de capacidad, precios |
| 12. `modelo="auto"` | 21 | detección de capacidades, satisfacción de necesidades más barata (unidad + integración) |
| 13. Ahorro de costes | 9 | ahorros frente a la línea base siempre GPT-4 + comparación automática alojada |
| 14. Caché de aviso | 15 | caché de coincidencia exacta entre proveedores + integración de chat |
| 15. Punto de referencia | 4 | resumen() + render_markdown() agregación |
| 16. Estado alojado | 7 | `/v1/hosted` fuente de configuración + superficie de URL de registro |
| 17. Ahorros en automóviles alojados | 3 | `_hosted_auto_ Savings` casos extremos en catálogos sintéticos |
| 18. Modelos inalcanzables | 7 | El mosaico "modelos a los que no puedes acceder" se borra cuando el alojamiento está activado |
| **Totales** | **127** | |

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

## Hoja de ruta

- [x] Finalizaciones de chat compatibles con OpenAI
- [x] Transmisión (SSE)
- [x] `model="auto"` enrutamiento más barato
- [x] Alojado como ascendente
- [x] BYOK cifrado en reposo
- [x] Panel de análisis local
- [x] CI (acciones de GitHub)
- [x] Almacenamiento en caché de mensajes entre proveedores
- [x] Integraciones de Continuar.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Punto de referencia público + reclamo de ahorro
- [] Incrustaciones + proxy de generación de imágenes

Consulte [DEMO.md](./DEMO.md) para ver la demostración de conmutación por error.

## Licencia

MIT. Consulte [LICENCIA](./LICENCIA).
