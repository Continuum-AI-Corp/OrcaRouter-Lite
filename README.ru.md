# ОркаРоутер Лайт

**Автономный маршрутизатор LLM с управляемой системой безопасности.**
Совместимость с OpenAI. БЁК. Единое рабочее место. Стриминг. `модель="авто"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![тесты](https://img.shields.io/badge/tests-127_passing-brightgreen)](#тестирование)
[![модели](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![лицензия](https://img.shields.io/badge/license-MIT-blue)](#license)

## Языки

- [Английский](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Deutsch](./README.de.md)
- [Français](./README.fr.md)
- [Испанский](./README.es.md)
- [Итальянский](./README.it.md)
- [Русский](./README.ru.md)
- [Португальский](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite — это версия [OrcaRouter] с открытым исходным кодом для одного рабочего пространства (https://www.orcarouter.ai). Запустите его на своем ноутбуке, включите в свой продукт или используйте размещенный api.orcarouter.ai непосредственно для длинного хвоста моделей, для которых вы не хотите управлять ключами.

> **Почему мы?** LiteLLM — это библиотека; OpenRouter размещается с закрытым исходным кодом; Оллама предназначен только для местных жителей. Мы **автономный сервер с управляемым резервным вариантом** — предложение, которое никто из них не может сказать.

## 60-секундное краткое руководство

Два способа использования OrcaRouter:

### Путь A — самостоятельное размещение (BYOK)

Запустите Lite на своем компьютере; принесите свои собственные ключи провайдера.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Базовый URL-адрес: `http://localhost:8000/v1`. Используйте ключ `sk-orca-*`, напечатанный при запуске.

### Путь B — Хостинг (требуется учетная запись)

Ни клона, ни докера. Зарегистрируйтесь, получите ключ, укажите любой OpenAI SDK на хостинге.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Требуется учетная запись.** Hosted управляет маршрутизацией, выставлением счетов и длинной цепочкой поставщиков — оплата производится за каждый токен в вашей учетной записи OrcaRouter. См. [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Затем вызовите его из любого OpenAI SDK

В приведенных ниже примерах используется базовый URL-адрес локального хоста пути A — замените его на https://api.orcarouter.ai/v1, если вы находитесь на пути B.

<подробности>
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
</подробнее>

<подробности>
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
</подробнее>

<подробности>
<summary><b>завиток</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</подробнее>

Откройте `http://localhost:8000/` для панели управления — поставщики, маршрутизация, аналитика, ключи (только путь A).

## Почему?

| | Лайт | библиотека LiteLLM | OpenRouter | Оллама |
|---|---|---|---|---|
| Автономный сервер | ✓ | как библиотека | ✗ | ✓ |
| Совместимость с OpenAI | ✓ | ✓ | ✓ | ✓ |
| Мультипровайдер (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Встроенная приборная панель | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (самый дешевый вариант) | ✓ | ✗ | ✗ | н/д |
| Потоковое | ✓ | ✓ | ✓ | ✓ |
| БЁК | ✓ | ✓ | ✗ | н/д |
| Размещено как резервный вариант | ✓ | ✗ | н/д | ✗ |
| Нет Postgres и Redis не требуется | ✓ | н/д | н/д | ✓ |

## `model="auto"` — функция заголовка

Отправьте `model="auto"`, и OrcaRouter выберет **самую дешевую** модель среди настроенных вами поставщиков, которая соответствует требованиям к возможностям запроса (инструменты, видение, режим JSON). Никаких правил ручной маршрутизации; нет скоростной гимнастики; нет `if x: ...` оптимизации затрат в вашем коде.

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

Разрешенная модель возвращается вызывающим абонентам через заголовок ответа `x-orca-resolved-model`, так что вы можете записать/отобразить то, что на самом деле использовалось.

## Хостинг как вышестоящий (Lite + хостинг)

Уже используете Lite? Установите для `ORCAROUTER_API_KEY` значение `sk-orca-*` из [www.orcarouter.ai](https://www.orcarouter.ai), и хостинг станет еще одним провайдером в цепочке маршрутизации, охватывая модели, которых нет в ваших локальных ключах:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Варианты использования:
- **Попробуйте перед покупкой** — ключи местного поставщика не нужны.
- **Локальное ведение журнала** — маршрутизация осуществляется на хосте, Lite сохраняет строки RequestLog для панели управления.
- **Аварийное переключение** – локальные провайдеры выходят из строя, хостинг – это система безопасности.

## Стриминг

Совместимый с OpenAI формат SSE со стандартным кадрированием `data: ... \n\n` и контрольным сигналом терминала `[DONE]` — вставка для любого SDK, который уже передает потоки из OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Каталог моделей

Более 100 моделей чата загружаются при запуске из [базы данных цен LiteLLM, поддерживаемой сообществом] (https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — список моделей не нужно поддерживать вручную. Каждая запись раскрывает:

- `id` (например, `gpt-4o`, `claude-3-5-sonnet-latest`)
- `провайдер` (сопоставляется с настроенными вами ключами)
- Флаги возможностей: `supports_tools`, `supports_vision`, `supports_json_mode`
- Стоимость ввода/вывода каждого токена (управляет виджетом экономии + `model="auto"`)

GET /v1/models возвращает каталог формата OpenAI.

## Развертывание в другом месте

| Платформа | В один клик |
|---|---|
| Железнодорожный | [![Развертывание на железной дороге](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Рендеринг | Подключить репозиторий, корневой каталог = `.` |
| Голый Докер | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (изображение скоро появится) |

## Что в коробке

- `POST /v1/chat/completions` — прокси + потоковая передача + `model="auto"` + кеш подсказок между поставщиками
- `GET /v1/models` — каталог доступных для обнаружения моделей (более 100 моделей из `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — установить/перечислить/отменить зашифрованные ключи провайдера
- `GET/PUT /v1/routing` — изменить стратегию (`сбалансированная`/`самая дешевая`/`самая быстрая`/`качественная`)
- `GET /v1/analytics/{recent,spend,latency,savings,unreachable}` — локальная аналитика, телеметрия не выходит из коробки
- `GET /v1/hosted` — статус резервного размещения (управляет картой панели управления «Получите бесплатный кредит на 5 долларов США»).
- `GET/POST/DELETE /v1/keys/...` — список/поворот/отзыв ключей API
- Одностраничная панель управления в `/`
- SQLite по умолчанию; Согласие на использование Postgres через `DATABASE_URL`; Redis необязательно

### Кэш запросов между поставщиками

Детерминированные запросы (temperature=0 или закрепленное начальное число) обслуживаются из кеша при повторении — работает для **каждого** поставщика, а не только для Anthropic. Серверная часть — это Redis, если установлен `REDIS_URL`, в противном случае — внутрипроцессный LRU. Попадания в кэш возвращаются мгновенно с помощью `x-orca-cache: HIT` и стоят 0 долларов.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Виджет экономии

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` сообщает, сколько будет стоить ваш трафик при использовании Always-GPT-4, а не сколько он будет стоить на самом деле. На приборной панели это отображается в виде плитки.

### Интеграции

Встраиваемые конфигурации для [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) и любой инструмент, поддерживающий протокол OpenAI Chat Completions. См. [`integrations/`](./integrations/).

## Чего намеренно нет

Это версия **с одним рабочим пространством**. По конструкции нет:
- мультитенантность, RBAC, SSO
- биллинг, кошельки, баллы, партнерская программа
- консоль администратора, журналы аудита, доверие и безопасность
- развертывание нескольких модулей / Kubernetes
- электронная почта/Slack/вебхуки для оповещений

Для этого ознакомьтесь с размещенным продуктом или (предстоящей) версией Teams.

## Тестирование

Создан сначала для тестирования. Каждое поведение, отправленное сюда, сначала проходило неудачный тест.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Срез | Тесты | Что |
|---|---|---|
| 1. Конфигурация | 5 | загрузка env, значения по умолчанию, `env_provider_keys()` |
| 2. Семена | 3 | рабочая область начальной загрузки + ключ API + RoutingConfig, идемпотент |
| 3. Промежуточное ПО для аутентификации | 4 | проверка токена на предъявителя, 401 при отсутствии/недействительности |
| 4. Фабрика приложений | 3 | /health, конверт ошибки, /v1/* стробирование |
| 5. Ключи провайдера CRUD | 5 | зашифровано в состоянии покоя, открытый текст никогда не передается туда и обратно |
| 6. Кэш роутера | 13 | env+DB+размещенная сборка развертывания с приоритетом |
| 7. Завершение чата | 5 | Формат OpenAI, RequestLog, проверка |
| 8. Аналитика | 4 | недавние/траты/задержка p50/p99 |
| 9. /v1/{модели,ключи,маршрутизация} | 8 | список/создать/отменить + обновление стратегии |
| 10. Стриминг | 4 | Формат SSE, контрольный сигнал `[DONE]`, обратная запись журнала |
| 11. Каталог | 7 | Более 100 моделей, флаги возможностей, цены |
| 12. `model="auto"` | 21 | определение возможностей, наиболее дешевое удовлетворение потребностей (единица + интеграция) |
| 13. Экономия средств | 9 | экономия по сравнению с базовым показателем всегда-GPT-4 + сравнение с размещенным автоматически |
| 14. Подскажите кэш | 15 | кеш с точным соответствием между поставщиками + интеграция с чатом |
| 15. Тест | 4 | summ() + агрегирование render_markdown() |
| 16. Статус хостинга | 7 | `/v1/hosted` config-source + поверхность URL-адреса регистрации |
| 17. Хостинг-авто экономия | 3 | Краевые случаи `_hosted_auto_savings` в синтетических каталогах |
| 18. Недостижимые модели | 7 | Плитка «Модели, с которыми вы не можете связаться» очищается при включенном хостинге |
| **Всего** | **127** | |

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

## Дорожная карта

- [x] Завершения чата, совместимые с OpenAI
- [x] Потоковая передача (SSE)
- [x] `model="auto"` самая дешевая маршрутизация
- [x] Размещено как восходящий поток
- [x] Зашифрованный BYOK в состоянии покоя
- [x] Панель локальной аналитики
- [x] CI (Действия GitHub)
- [x] Кеширование подсказок между поставщиками
- [x] Интеграция Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Государственный контрольный показатель + требование о сбережениях
- [ ] Встраивания + прокси-сервер для генерации изображений

См. [DEMO.md](./DEMO.md) для демонстрации аварийного переключения.

## Лицензия

Массачусетский технологический институт. См. [ЛИЦЕНЗИЯ](./ЛИЦЕНЗИЯ).
