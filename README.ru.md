# OrcaRouter Lite

**Задайте бюджет каждому агенту для кодинга.**
Отслеживайте и ограничивайте расходы Claude Code, Aider, Cursor и ваших собственных приложений у всех провайдеров моделей — при этом ваши промпты не покидают вашу машину. Приложение в строке меню для одного разработчика и self-hosted-роутер для всей команды. Лицензия MIT.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="Панель OrcaRouter Lite в строке меню: расходы за сегодня относительно дневного бюджета, подключённые агенты для кодинга и состояние провайдеров" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Первичная настройка: найденные агенты для кодинга, куда уходят запросы, и дневной бюджет" width="420">
</p>

## Языки

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

**Наши проекты:** [Все API моделей](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite — это open-source-редакция [OrcaRouter](https://www.orcarouter.ai). Он работает на вашем компьютере или сервере, говорит на API OpenAI, Anthropic и Gemini и может использовать hosted `api.orcarouter.ai` как страховочную сетку на случай сбоев и для моделей, ключей к которым у вас нет.

## Десктопное приложение

Приложение Orca живёт в строке меню. Оно запускает роутер на `127.0.0.1`, подключает к нему ваших агентов для кодинга и показывает, сколько они тратят.

- **Расходы за сегодня, по агентам.** Сумма за день видна рядом с часами; панель разбивает её по агентам.
- **Дневной бюджет.** Уведомления при 80% и 100% заданной вами суммы. Агенты продолжают работать: Orca предупреждает, а не блокирует.
- **Подключение в один клик.** Orca правит собственные настройки агента, сохраняет резервную копию и восстанавливает её, когда вы отключаете агента.
- **Без простоев.** Когда провайдер падает или упирается в rate limit, запросы переключаются на другого провайдера или на hosted OrcaRouter, а приложение считает, сколько запросов удалось спасти.
- **Приватность по умолчанию.** Промпты идут напрямую от ваших агентов к выбранному вами провайдеру. Никакой телеметрии.

**Установка.** Установщики (`.dmg`, `.deb`, `.AppImage`, `.msi`) собираются в [`desktop.yml`](./.github/workflows/desktop.yml) и прикладываются к каждому релизу, начиная со следующей версии с тегом. А пока тот же движок и CLI доступны одной командой:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` отдаёт панель по адресу `http://127.0.0.1:8765/desktop/panel.html`; как собрать само приложение для строки меню, см. [`desktop/`](./desktop/README.md).

| Агент | Как подключается |
|---|---|
| Claude Code | Автоматически: прописывает `ANTHROPIC_BASE_URL` и выделенный ключ в `~/.claude/settings.json` |
| Aider | Автоматически: прописывает `openai-api-base`, выделенный ключ и `model: openai/auto` в `~/.aider.conf.yml` |
| Cursor | Один шаг вручную: приложение показывает базовый URL и ключ, которые нужно вставить в настройки моделей Cursor |
| Codex | Скоро: нужен OpenAI Responses API (`/v1/responses`), который Lite пока не поддерживает |
| Gemini CLI | Скоро |

Каждый подключённый агент получает собственный ключ: так расходы разделяются по агентам, и поэтому отключение сразу отзывает доступ. Что приложению разрешено трогать на вашем компьютере, подробно описано в [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

<a id="free-and-open-for-good"></a>
## Бесплатно и открыто — навсегда

- **MIT, навсегда.** Всё, что нужно одному разработчику или одной команде, остаётся в этом репозитории под MIT: маршрутизация, `model="auto"`, бюджеты, дашборд, десктопное приложение. Мы не будем переносить фичи из Lite в платный план.
- **Платное — для организаций.** Управление множеством команд (SSO/SCIM, ролевой доступ, бюджеты и политики для всей организации, хранение аудит-логов, алерты в Slack и на email) — это [hosted OrcaRouter](https://www.orcarouter.ai).
- **Проверяемо.** Релизы подписаны и поставляются с provenance и SBOM. См. [SECURITY.md](./SECURITY.md).

## Сравнение с альтернативами

| | Кому подходит | Как работает |
|---|---|---|
| **OrcaRouter Lite** | От одного разработчика до команды, которой нужны расходы по агентам, бюджеты и failover без новой инфраструктуры | Десктопное приложение, `uvx`/`pip` или Docker; по умолчанию SQLite |
| LiteLLM proxy | Командам, которым нужна обширная конфигурация и Python SDK | Self-hosted-сервер; Postgres для учёта расходов |
| OpenRouter | Тем, кому нужен один API-ключ ко множеству моделей с оплатой через OpenRouter | Только hosted; промпты проходят через их сервис |
| Встроенная поддержка шлюзов в Claude Code | Компаниям, которые используют только Claude | Направляет Claude Code на шлюз, который вы держите сами; только модели Claude |

## Запуск в виде сервера (60 секунд)

Два способа использовать OrcaRouter:

### Путь A — Self-hosted (BYOK)

Запустите Lite на своей машине; принесите свои ключи провайдеров.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# добавьте хотя бы один: OPENAI_API_KEY=sk-...  (или ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Базовый URL: `http://localhost:8000/v1`. Используйте ключ `sk-orca-*`, выведенный при старте.

### Путь B — Hosted (требуется аккаунт)

Без клонирования, без docker. Зарегистрируйтесь, получите ключ, направьте любой OpenAI SDK на hosted-эндпоинт.

```bash
# 1. Зарегистрируйтесь на https://www.orcarouter.ai и скопируйте свой ключ sk-orca-*
# 2. Используйте https://api.orcarouter.ai/v1 как базовый URL
```

**Требуется аккаунт.** Hosted берёт на себя маршрутизацию, биллинг и длинный хвост провайдеров — оплата по токенам на вашем аккаунте OrcaRouter. См. [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Затем вызывайте из любого OpenAI SDK

В примерах ниже используется localhost-URL из Пути A — замените на `https://api.orcarouter.ai/v1`, если вы на Пути B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # или "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

Откройте `http://localhost:8000/` для дашборда — провайдеры, маршрутизация, аналитика, ключи (только Путь A).

## `model="auto"`

Отправьте `model="auto"`, и OrcaRouter выберет **самую дешёвую** модель среди настроенных провайдеров, которая удовлетворяет требованиям запроса по возможностям (tools, vision, JSON-режим). Никаких ручных правил маршрутизации; никакой акробатики с rate-limit; никаких `if x: ...`-оптимизаций по цене в вашем коде.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → маршрутизирует на самую дешёвую VISION-модель, покрытую вашими ключами
```

Выбранная модель возвращается вызывающему через заголовок ответа `x-orca-resolved-model`, чтобы вы могли логировать/показывать, что фактически использовалось.

## Hosted как upstream (Lite + hosted)

Уже запустили Lite? Установите `ORCAROUTER_API_KEY` равным вашему `sk-orca-*` с [www.orcarouter.ai](https://www.orcarouter.ai), и hosted станет ещё одним провайдером в цепочке маршрутизации — покрывая модели, которых нет у ваших локальных ключей:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Сценарии:
- **Try-before-you-buy** — локальные ключи провайдеров не нужны
- **Локальное логирование** — hosted делает маршрутизацию, Lite пишет строки RequestLog для дашборда
- **Failover** — локальные провайдеры падают, hosted — страховочная сетка

## Стриминг

OpenAI-совместимый SSE-формат со стандартным `data: ... \n\n`-фреймингом и завершающим маркером `[DONE]` — drop-in для любого SDK, который уже стримит из OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Нативные протокольные эндпоинты (Anthropic + Gemini)

Lite говорит на трёх входящих протоколах поверх одного пайплайна маршрутизации. Клиенты, которые говорят только на wire-форматах Anthropic или Gemini, подключаются напрямую — OpenAI SDK не требуется:

```bash
# Claude Code, направленный на Lite (без суффикса /v1 в базовом URL)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK, направленный на Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Запросы транслируются на входе в тот же внутренний пайплайн, поэтому `model="auto"`, кросс-провайдерный кэш промптов (общий для всех протоколов), стратегии маршрутизации и аналитический дашборд работают одинаково. Гайды: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Каталог моделей

При старте загружается более 100 чат-моделей из [community-поддерживаемой базы цен LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — никакого списка моделей вручную. Каждая запись содержит:

- `id` (например, `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (мапится на ваши настроенные ключи)
- Capability-флаги: `supports_tools`, `supports_vision`, `supports_json_mode`
- Стоимость на токен входа/выхода (питает виджет экономии + `model="auto"`)

`GET /v1/models` возвращает каталог в формате OpenAI.

## Деплой в другом месте

| Платформа | Как |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (публикуется начиная со следующего релиза с тегом; проверить образ можно командами из [SECURITY.md](./SECURITY.md)) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Подключите репозиторий, корневая директория = `.` |
| Railway | Шаблон скоро (задача #181) |

## Что в коробке

- `POST /v1/chat/completions` — proxy + стриминг + `model="auto"` + кросс-провайдерный кэш промптов
- `POST /v1/messages` — **ingress для Anthropic Messages API** (Claude Code / Anthropic SDK подключаются напрямую; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **ingress для Gemini API** (google-genai SDK подключается напрямую; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — обнаруживаемый каталог моделей (100+ моделей из `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — установка / список / отзыв зашифрованных ключей провайдеров
- `GET/PUT /v1/routing` — смена стратегии (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — локальная аналитика, никакая телеметрия не уходит из коробки
- `GET  /v1/hosted` — статус hosted-fallback (питает карточку «Get $5 free credit» в дашборде)
- `GET/POST/DELETE /v1/keys/...` — список / ротация / отзыв API-ключей
- `/v1/app/*` — агенты, сводка расходов и бюджет для десктопного приложения (только при запуске через `orca up`; см. [SECURITY.md](./SECURITY.md))
- Single-page-дашборд по `/`
- SQLite по умолчанию; Postgres опционально через `DATABASE_URL`; Redis опционально

### Кросс-провайдерный кэш промптов

Детерминированные запросы (`temperature=0` или закреплённый `seed`) при повторе обслуживаются из кэша — работает на **любом** провайдере, не только Anthropic. Бэкенд — Redis, если задан `REDIS_URL`, иначе in-process LRU. Попадания в кэш возвращаются мгновенно с `x-orca-cache: HIT` и стоят $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # тот же payload снова
HTTP/1.1 200 OK
x-orca-cache: HIT          ← из кэша, без запроса к upstream
```

### Виджет экономии

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` показывает, сколько ваш трафик стоил бы на «всегда GPT-4» против того, сколько стоил на самом деле. Дашборд показывает это в виде плитки.

### Интеграции

Готовые конфиги для [Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) и любого инструмента, говорящего на протоколе OpenAI Chat Completions, — плюс нативные wire-форматы Anthropic и Gemini. См. [`integrations/`](./integrations/).

## Чего намеренно нет

Это редакция **single-workspace**. По дизайну, нет:
- мульти-арендности, RBAC, SSO
- биллинга, кошельков, баллов, партнёрской программы
- админ-консоли, audit-логов, trust & safety
- multi-pod-деплоя / Kubernetes
- email / Slack / webhook-алертов

Это функции для организаций, и они есть в [hosted OrcaRouter](https://www.orcarouter.ai); см. [Бесплатно и открыто — навсегда](#free-and-open-for-good).

## Тестирование

Сделано test-first: у каждого поведения, выпущенного здесь, сначала был падающий тест.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

## Архитектура

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

- [x] OpenAI-совместимые chat completions, стриминг, `model="auto"`
- [x] Нативные эндпоинты Anthropic и Gemini
- [x] Hosted как upstream-fallback, зашифрованный BYOK, локальный дашборд
- [x] Кросс-провайдерный кэш промптов
- [x] Десктопное приложение: расходы в строке меню, алерты по дневному бюджету, подключение агентов в один клик
- [x] Подписанные релизы с provenance и SBOM; зависимости, зафиксированные по хешам
- [ ] `/v1/responses`, чтобы мог подключиться Codex
- [ ] Жёсткие лимиты бюджета на разработчика (алерты уже работают)
- [ ] `orca login`: подключение к шлюзу команды прямо из приложения
- [ ] Embeddings, провайдеры Ollama/vLLM, настраиваемые цепочки fallback

См. [DEMO.md](./DEMO.md) для демо failover.

<a id="license"></a>
## Лицензия

MIT. См. [LICENSE](./LICENSE).
