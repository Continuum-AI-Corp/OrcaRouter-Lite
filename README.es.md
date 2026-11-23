# OrcaRouter Lite

**Ponle un presupuesto a cada agente de código.**
Mira y limita cuánto gastan Claude Code, Aider, Cursor y tus propias apps, en todos los proveedores
de modelos, sin que tus prompts salgan de tu máquina. Una app de barra de menús para un desarrollador
y un enrutador autoalojado para todo un equipo. Licencia MIT.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="El panel de OrcaRouter Lite en la barra de menús: gasto de hoy frente a un presupuesto diario, agentes de código conectados y estado de los proveedores" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Configuración inicial: agentes de código detectados, adónde van las solicitudes y un presupuesto diario" width="420">
</p>

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

**Encuéntranos:** [Todas las API de modelos](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite es la edición open source de [OrcaRouter](https://www.orcarouter.ai). Se ejecuta en tu ordenador o en tu servidor, habla las API de OpenAI, Anthropic y Gemini, y puede usar el `api.orcarouter.ai` alojado como red de seguridad ante caídas y para los modelos de los que no tienes claves.

## La app de escritorio

La app Orca vive en tu barra de menús. Ejecuta el enrutador en `127.0.0.1`, conecta a él tus agentes
de código y muestra cuánto gastan.

- **Gasto de hoy, por agente.** El total del día aparece junto al reloj; el panel lo desglosa por agente.
- **Un presupuesto diario.** Notificaciones al 80 % y al 100 % del importe que fijes. Por defecto solo avisa; marca una casilla y Orca pausa tus agentes de código al alcanzarlo.
- **Conexión en un clic.** Orca edita la configuración propia del agente, guarda una copia de seguridad y la restaura cuando lo desconectas.
- **Nunca caído.** Cuando un proveedor falla o te aplica rate-limit, las solicitudes pasan a otro proveedor o al OrcaRouter alojado, y la app cuenta cuántas ha rescatado. Vincula tu cuenta con `orca link --key sk-orca-…` o desde la configuración inicial.
- **Privado por defecto.** Los prompts van directamente de tus agentes al proveedor que elijas. Sin telemetría.
- **Funciona con el gateway de tu equipo.** `orca login https://ai-gw.example.com --key …` (o "Join my company's gateway" en la configuración inicial) apunta tus agentes al gateway que gestiona tu equipo de plataforma; `orca logout` los restaura.

**Instalación.** Los instaladores (`.dmg`, `.deb`, `.AppImage`, `.msi`) los genera
[`desktop.yml`](./.github/workflows/desktop.yml) y se adjuntan a cada release a partir de la
próxima versión etiquetada. Hasta entonces, el mismo motor y la misma CLI están a un comando de distancia:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` sirve el panel en `http://127.0.0.1:8765/desktop/panel.html`; para compilar la propia
app de barra de menús, consulta [`desktop/`](./desktop/README.md). Cuando salga la primera release,
los usuarios de Mac con Apple silicon también podrán hacer `brew install --cask continuum-ai-corp/tap/orcarouter-lite`.

El gasto de hoy en la barra de estado de Claude Code: añade esto a `~/.claude/settings.json`.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` imprime la semana en Markdown (o `--format csv`) para pegarla en un chat o una hoja de cálculo.

| Agente | Cómo se conecta |
|---|---|
| Claude Code | Automático: configura `ANTHROPIC_BASE_URL` y una clave dedicada en `~/.claude/settings.json` |
| Aider | Automático: configura `openai-api-base`, una clave dedicada y `model: openai/auto` en `~/.aider.conf.yml` |
| Cursor | Un paso de copiar y pegar: la app muestra una URL base y una clave para la configuración de modelos de Cursor |
| Codex | Próximamente: necesita la API Responses de OpenAI (`/v1/responses`), que Lite aún no sirve |
| Gemini CLI | Próximamente |

Cada agente conectado recibe su propia clave: así se reparte el gasto por agente, y por eso al
desconectarlo se revoca el acceso al instante. Lo que la app puede tocar en tu ordenador se detalla
en [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

<a id="free-and-open-for-good"></a>

## Libre y abierto, para siempre

- **MIT, de forma permanente.** Todo lo que necesita un desarrollador o un equipo se queda en este repositorio bajo MIT: el enrutamiento, `model="auto"`, los presupuestos, el panel y la app de escritorio. No moveremos ninguna funcionalidad de Lite a un plan de pago.
- **Lo de pago es para organizaciones.** La gestión de muchos equipos (SSO/SCIM, acceso basado en roles, presupuestos y políticas para toda la flota, retención de auditoría, alertas a Slack y por email) está en el [OrcaRouter alojado](https://www.orcarouter.ai).
- **Verificable.** Las releases están firmadas e incluyen procedencia (provenance) y un SBOM. Consulta [SECURITY.md](./SECURITY.md).

## Cómo se compara

| | Ideal para | Cómo se ejecuta |
|---|---|---|
| **OrcaRouter Lite** | Desde un desarrollador hasta un equipo que quiere gasto por agente, presupuestos y failover sin infraestructura nueva | App de escritorio, `uvx`/`pip` o Docker; SQLite por defecto |
| Proxy de LiteLLM | Equipos que quieren una gran superficie de configuración y un SDK de Python | Servidor autoalojado; Postgres para el seguimiento del gasto |
| OpenRouter | Una sola clave de API para muchos modelos, facturados por OpenRouter | Solo alojado; los prompts pasan por su servicio |
| El soporte de gateway propio de Claude Code | Empresas que solo usan Claude | Apunta Claude Code a un gateway que gestionas tú; solo modelos Claude |

## Ejecútalo como servidor (60 segundos)

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

## `model="auto"`

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

| Plataforma | Cómo |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (se publica a partir de la próxima release etiquetada; verifícala con los comandos de [SECURITY.md](./SECURITY.md)) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Conecta el repo, directorio raíz = `.` |
| Railway | Plantilla en camino (seguimiento en #181) |

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
- `/v1/app/*` — agentes, resumen de gasto y presupuesto para la app de escritorio (solo al iniciar con `orca up`; consulta [SECURITY.md](./SECURITY.md))
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

Son funcionalidades para organizaciones y están en el [OrcaRouter alojado](https://www.orcarouter.ai); consulta [Libre y abierto, para siempre](#free-and-open-for-good).

## Pruebas

Construido con test-first: cada comportamiento entregado aquí tuvo primero un test fallando.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

- [x] Chat completions compatibles con OpenAI, streaming, `model="auto"`
- [x] Endpoints nativos de Anthropic y Gemini
- [x] Respaldo con hosted como upstream, BYOK cifrado, panel local
- [x] Caché de prompts entre proveedores
- [x] App de escritorio: gasto en la barra de menús, alertas de presupuesto diario, conexión de agentes en un clic
- [x] Releases firmadas con procedencia y SBOM; dependencias fijadas por hash
- [x] Presupuesto diario que avisa, o pausa los agentes de código al llegar al límite
- [x] `orca login` / "Join my company's gateway": usar el gateway de un equipo desde la app
- [ ] `/v1/responses` para que Codex pueda conectarse
- [ ] Presupuestos por desarrollador aplicados en un gateway de equipo compartido
- [ ] Embeddings, proveedores Ollama/vLLM, cadenas de respaldo personalizadas

Consulta [DEMO.md](./DEMO.md) para la demo de failover.

<a id="license"></a>

## Licencia

MIT. Consulta [LICENSE](./LICENSE).
