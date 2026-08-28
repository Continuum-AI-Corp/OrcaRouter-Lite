# OrcaRouter Lite

**Self-hosted LLM-роутер с управляемой страховочной сеткой.**
OpenAI-совместимый. BYOK. Один рабочий пространство (workspace). Стриминг. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

![Демо failover OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"` в реальном времени поглощает сбой провайдера — без изменений в коде. Как записать: [DEMO.md](./DEMO.md).*

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

OrcaRouter Lite — это open-source-редакция [OrcaRouter](https://www.orcarouter.ai) для одного workspace. Запустите его на ноутбуке, поставьте в свой продукт или используйте hosted-эндпоинт `api.orcarouter.ai` напрямую для длинного хвоста моделей, ключи которых вы не хотите вести самостоятельно.

> **Почему мы?** LiteLLM — это библиотека; OpenRouter — closed-source и hosted; Ollama — только локально. Мы — **self-hosted-сервер с управляемым fallback** — фразу, которую никто из них сказать не может.

## Быстрый старт за 60 секунд

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

## Почему?

| | OrcaRouter Lite | Библиотека LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Self-hosted-сервер | ✓ | как библиотека | ✗ | ✓ |
| OpenAI-совместимый | ✓ | ✓ | ✓ | ✓ |
| Мульти-провайдер (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Встроенный дашборд | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (самый дешёвый подходящий) | ✓ | ✗ | ✗ | n/a |
| Стриминг | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hosted как fallback | ✓ | ✗ | n/a | ✗ |
| Без Postgres / без Redis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — главная фича

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

| Платформа | One-click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Подключите репо, корневая директория = `.` |
| Голый Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (образ скоро) |

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

Для этого см. hosted-продукт или (будущую) Teams-редакцию.

## Тестирование

Сделано test-first. У каждого поведения, выпущенного здесь, сначала был падающий тест.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| Слайс | Тесты | Что |
|---|---|---|
| 1. Config | 5 | загрузка env, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + API-ключ + RoutingConfig, идемпотентно |
| 3. Auth-middleware | 4 | валидация bearer-токена, 401 при отсутствии/невалидном |
| 4. App factory | 3 | /health, error-конверт, gating /v1/* |
| 5. CRUD ключей провайдеров | 5 | шифровано at rest, plaintext не делает round-trip |
| 6. Кэш роутера | 13 | сборка деплоя env+DB+hosted с приоритетами |
| 7. Chat completion | 5 | формат OpenAI, RequestLog, валидация |
| 8. Аналитика | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + обновление стратегии |
| 10. Стриминг | 4 | SSE-формат, маркер `[DONE]`, log writeback |
| 11. Каталог | 7 | 100+ моделей, capability-флаги, цены |
| 12. `model="auto"` | 21 | детект возможностей, самый-дешёвый-из-подходящих (unit + интеграция) |
| 13. Экономия затрат | 9 | экономия vs always-GPT-4 baseline + сравнение hosted-auto |
| 14. Кэш промптов | 15 | кросс-провайдерный exact-match-кэш + интеграция с чатом |
| 15. Бенчмарк | 4 | агрегация summarize() + render_markdown() |
| 16. Hosted-статус | 7 | `/v1/hosted` config-source + signup-URL surface |
| 17. Hosted-auto-экономия | 3 | edge cases `_hosted_auto_savings` на синтетических каталогах |
| 18. Недоступные модели | 7 | плитка «модели, до которых вы не дотянетесь» очищается, когда hosted включён |
| 19. Мульти-протокольная аутентификация | 6 | скоупинг x-api-key / x-goog-api-key / ?key=, guard для /v1beta, 401-конверты для каждого протокола |
| 20. Anthropic `/v1/messages` | 53 | трансляция request/response/stream + ingress-интеграция |
| 21. Gemini `/v1beta` | 40 | трансляция, вкл. нормализацию schema-enum + ingress для generateContent/stream |
| **Всего** | **403** | |

Строки слайсов показывают тесты, добавленные при выпуске каждого слайса; итог — текущий полный набор тестов.

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

packages/
├── litellm_adapter/    Router wrapper + 100+ model catalog
├── auth/               hashing + AES-256-GCM
└── db/                 models + engine + session
```

## Roadmap

- [x] OpenAI-совместимые chat completions
- [x] Стриминг (SSE)
- [x] `model="auto"` маршрутизация на самый-дешёвый-подходящий
- [x] Hosted-как-upstream
- [x] Зашифрованный BYOK at rest
- [x] Локальный аналитический дашборд
- [x] CI (GitHub Actions)
- [x] Кросс-провайдерное кэширование промптов
- [x] Интеграции Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Публичный бенчмарк + заявление по экономии
- [ ] Прокси для embeddings + image-gen

См. [DEMO.md](./DEMO.md) для демо failover.

## Лицензия

MIT. См. [LICENSE](./LICENSE).
