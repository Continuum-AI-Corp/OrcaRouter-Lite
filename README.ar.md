# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | [日本語](./README.ja.md) | [한국어](./README.ko.md) | [Deutsch](./README.de.md) | [Italiano](./README.it.md) | [Français](./README.fr.md) | [Español](./README.es.md) | **العربية**

<div dir="rtl">

**موجّه LLM ذاتي الاستضافة مع شبكة أمان مُدارة.**
متوافق مع OpenAI. BYOK. مساحة عمل واحدة. بث مباشر. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#الاختبارات)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#كتالوج-النماذج)
[![license](https://img.shields.io/badge/license-MIT-blue)](#الترخيص)

OrcaRouter Lite هو إصدار مفتوح المصدر لمساحة عمل واحدة من [OrcaRouter](https://www.orcarouter.ai). شغّله على حاسوبك المحمول، أو ادمجه في منتجك، أو استخدم `api.orcarouter.ai` المستضاف مباشرة لذيل النماذج الطويل التي لا ترغب في إدارة مفاتيحها.

> **لماذا نحن؟** LiteLLM هي مكتبة؛ OpenRouter مغلق المصدر ومستضاف؛ Ollama محلي فقط. نحن **خادم ذاتي الاستضافة مع احتياطي مُدار** — جملة لا يمكن لأي منهم قولها.

## بداية سريعة في 60 ثانية

طريقتان لاستخدام OrcaRouter:

### المسار A — ذاتي الاستضافة (BYOK)

شغّل Lite على جهازك الخاص؛ أحضر مفاتيح المزود الخاصة بك.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# أضف على الأقل واحداً: OPENAI_API_KEY=sk-...  (أو ORCAROUTER_API_KEY=...)

docker compose up
# السجلات: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

عنوان URL الأساسي: `http://localhost:8000/v1`. استخدم مفتاح `sk-orca-*` المطبوع عند بدء التشغيل.

### المسار B — مستضاف (الحساب مطلوب)

بدون استنساخ، بدون docker. سجّل، احصل على مفتاح، وجّه أي SDK من OpenAI إلى المستضاف.

```bash
# 1. سجّل في https://www.orcarouter.ai وانسخ مفتاح sk-orca-* الخاص بك
# 2. استخدم https://api.orcarouter.ai/v1 كعنوان URL أساسي
```

**الحساب مطلوب.** يتولى المستضاف التوجيه والفوترة والذيل الطويل من المزودين — يُحتسب لكل رمز على حساب OrcaRouter الخاص بك. انظر [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### ثم استدعه من أي SDK لـ OpenAI

تستخدم الأمثلة أدناه عنوان URL الأساسي localhost للمسار A — استبدله بـ `https://api.orcarouter.ai/v1` إذا كنت على المسار B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # أو "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "مرحبا!"}],
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
  messages: [{ role: "user", content: "مرحبا!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"مرحبا!"}]}'
```
</details>

افتح `http://localhost:8000/` للوحة التحكم — المزودون، التوجيه، التحليلات، المفاتيح (المسار A فقط).

## لماذا؟

| | Lite | مكتبة LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| خادم ذاتي الاستضافة | ✓ | كمكتبة | ✗ | ✓ |
| متوافق مع OpenAI | ✓ | ✓ | ✓ | ✓ |
| متعدد المزودين (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| لوحة تحكم مدمجة | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (الأرخص الذي يلبي الاحتياجات) | ✓ | ✗ | ✗ | غير متاح |
| البث المباشر | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | غير متاح |
| المستضاف كاحتياطي | ✓ | ✗ | غير متاح | ✗ |
| لا يتطلب Postgres / لا يتطلب Redis | ✓ | غير متاح | غير متاح | ✓ |

## `model="auto"` — الميزة الرئيسية

أرسل `model="auto"` ويختار OrcaRouter النموذج **الأرخص** بين المزودين المُكوّنين الذي يلبي متطلبات قدرات الطلب (الأدوات، الرؤية، وضع JSON). لا قواعد توجيه يدوية؛ لا جمباز لحدود المعدل؛ لا تحسين تكلفة `if x: ...` في الكود الخاص بك.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "ماذا يوجد في هذه الصورة؟"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → يوجّه إلى أرخص نموذج قادر على الرؤية تغطيه مفاتيحك
```

يتم عرض النموذج الذي تم حله للمتصلين عبر رأس الاستجابة `x-orca-resolved-model` حتى تتمكن من تسجيل/عرض ما تم استخدامه فعلياً.

## المستضاف كمصدر علوي (Lite + المستضاف)

هل تشغّل Lite بالفعل؟ عيّن `ORCAROUTER_API_KEY` على `sk-orca-*` الخاص بك من [www.orcarouter.ai](https://www.orcarouter.ai)، ويصبح المستضاف مزوداً آخر في سلسلة التوجيه — يغطي النماذج التي لا تغطيها مفاتيحك المحلية:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

حالات الاستخدام:
- **جرّب قبل الشراء** — لا حاجة لمفاتيح مزود محلية
- **التسجيل المحلي** — يتولى المستضاف التوجيه، ويخزن Lite صفوف RequestLog للوحة التحكم
- **التحويل عند الفشل** — تفشل المزودات المحلية، يكون المستضاف شبكة الأمان

## البث المباشر

تنسيق SSE متوافق مع OpenAI مع تأطير `data: ... \n\n` القياسي وحارس `[DONE]` نهائي — توصيل مباشر لأي SDK يبث بالفعل من OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "احكِ لي قصة"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## كتالوج النماذج

يتم تحميل أكثر من 100 نموذج محادثة عند بدء التشغيل من [قاعدة بيانات الأسعار التي تديرها مجتمع LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — بدون قائمة نماذج للصيانة يدوياً. يكشف كل إدخال:

- `id` (مثل `gpt-4o`، `claude-3-5-sonnet-latest`)
- `provider` (مرتبط بمفاتيحك المُكوّنة)
- علامات القدرة: `supports_tools`، `supports_vision`، `supports_json_mode`
- تكلفة الإدخال/الإخراج لكل رمز (تقود أداة التوفير + `model="auto"`)

يُرجع `GET /v1/models` الكتالوج بتنسيق OpenAI.

## النشر في مكان آخر

| المنصة | بنقرة واحدة |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | اربط المستودع، الدليل الجذر = `.` |
| Docker مجرد | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (الصورة قريباً) |

## ما الموجود في الصندوق

- `POST /v1/chat/completions` — وكيل + بث مباشر + `model="auto"` + ذاكرة تخزين موجهات عبر المزودين
- `GET  /v1/models` — كتالوج نماذج قابل للاكتشاف (أكثر من 100 نموذج من `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — تعيين / إدراج / إلغاء مفاتيح المزود المشفرة
- `GET/PUT /v1/routing` — تغيير الاستراتيجية (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — تحليلات محلية، لا قياس عن بُعد يغادر الصندوق
- `GET  /v1/hosted` — حالة الاحتياطي المستضاف (تقود بطاقة "احصل على رصيد مجاني بقيمة 5 دولارات" في لوحة التحكم)
- `GET/POST/DELETE /v1/keys/...` — إدراج / تدوير / إلغاء مفاتيح API
- لوحة تحكم بصفحة واحدة على `/`
- SQLite افتراضياً؛ Postgres اختياري عبر `DATABASE_URL`؛ Redis اختياري

### ذاكرة تخزين موجهات عبر المزودين

تُقدَّم الطلبات الحتمية (`temperature=0` أو `seed` مثبت) من ذاكرة التخزين عند التكرار — تعمل عبر **كل** مزود، ليس فقط Anthropic. الواجهة الخلفية هي Redis عند تعيين `REDIS_URL`، و LRU داخل العملية بخلاف ذلك. تُرجع نتائج ذاكرة التخزين فوراً مع `x-orca-cache: HIT` وتكلفة 0 دولار.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # نفس الحمولة مرة أخرى
HTTP/1.1 200 OK
x-orca-cache: HIT          ← قُدّمت من ذاكرة التخزين، بدون استدعاء أعلى
```

### أداة التوفير

يُبلّغ `GET /v1/analytics/savings?baseline=gpt-4o&days=7` عن ما كان سيكلفه حركة المرور الخاصة بك على دائماً-GPT-4 مقابل ما كلّفته فعلياً. تعرضه لوحة التحكم كبلاطة.

### التكاملات

تكوينات توصيل مباشر لـ [Continue.dev](./integrations/continue.json) و[Aider](./integrations/aider.md) و[Cursor](./integrations/cursor.md) و[LangChain](./integrations/langchain_orcarouter.py) و[LlamaIndex](./integrations/llamaindex_orcarouter.py) و[Vercel AI SDK](./integrations/vercel_ai.ts)، وأي أداة تتحدث ببروتوكول OpenAI Chat Completions. انظر [`integrations/`](./integrations/).

## ما هو غير متضمن عمداً

هذا هو إصدار **مساحة العمل الواحدة**. حسب التصميم، لا يوجد:
- متعدد المستأجرين، RBAC، SSO
- الفوترة، المحافظ، النقاط، برنامج الشركاء
- وحدة تحكم المسؤول، سجلات التدقيق، الثقة والأمان
- نشر متعدد الحُجَيرات / Kubernetes
- البريد الإلكتروني / Slack / webhooks للتنبيهات

لتلك الميزات، انظر المنتج المستضاف أو إصدار Teams (القادم).

## الاختبارات

تم إنشاؤه باختبار أولاً. كل سلوك تم شحنه هنا كان لديه اختبار فاشل أولاً.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| الشريحة | الاختبارات | ماذا |
|---|---|---|
| 1. التكوين | 5 | تحميل env، الافتراضيات، `env_provider_keys()` |
| 2. البذر | 3 | تمهيد مساحة العمل + مفتاح API + RoutingConfig، خامل |
| 3. وسيط المصادقة | 4 | التحقق من رمز bearer، 401 عند المفقود/غير الصالح |
| 4. مصنع التطبيق | 3 | /health، مظروف الخطأ، بوابة /v1/* |
| 5. CRUD مفاتيح المزود | 5 | مشفرة في وضع الراحة، النص العادي لا يقوم برحلة ذهاب وإياب أبداً |
| 6. ذاكرة تخزين الموجه | 13 | تجميع نشر env+DB+مستضاف بالأسبقية |
| 7. إكمال المحادثة | 5 | تنسيق OpenAI، RequestLog، التحقق |
| 8. التحليلات | 4 | حديث / إنفاق / زمن الاستجابة p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | إدراج/إنشاء/إلغاء + تحديث الاستراتيجية |
| 10. البث المباشر | 4 | تنسيق SSE، حارس `[DONE]`، إعادة كتابة السجل |
| 11. الكتالوج | 7 | أكثر من 100 نموذج، علامات القدرة، التسعير |
| 12. `model="auto"` | 21 | اكتشاف القدرة، الأرخص-الذي-يلبي-الاحتياجات (وحدة + تكامل) |
| 13. توفير التكاليف | 9 | التوفير مقابل خط أساس دائماً-GPT-4 + مقارنة hosted-auto |
| 14. ذاكرة تخزين الموجه | 15 | ذاكرة تخزين عبر المزود تطابق دقيق + تكامل المحادثة |
| 15. القياس المعياري | 4 | تجميع summarize() + render_markdown() |
| 16. حالة المستضاف | 7 | مصدر تكوين `/v1/hosted` + سطح URL التسجيل |
| 17. توفير hosted-auto | 3 | حالات حافة `_hosted_auto_savings` على كتالوجات اصطناعية |
| 18. النماذج التي لا يمكن الوصول إليها | 7 | بلاطة "النماذج التي لا يمكنك الوصول إليها" تُمسح عند تشغيل المستضاف |
| **الإجمالي** | **127** | |

## الهندسة المعمارية

```
app/
├── main.py             مصنع FastAPI + lifespan + تركيب SPA
├── config.py           الإعدادات (~15 حقل)
├── deps.py             مساعدو DI
├── seed.py             تمهيد التشغيل الأول
├── auto_routing.py     قدرة model="auto" + تسجيل التكلفة
├── router_cache.py     موجه مساحة العمل الواحدة
├── prompt_cache.py     ذاكرة تخزين عبر المزود تطابق دقيق (Redis أو LRU في الذاكرة)
├── schemas.py          مخطط طلب متوافق مع OpenAI
├── middleware/auth.py  التحقق من sk-orca-*
└── routes/
    ├── chat.py         /v1/chat/completions  (حظر + بث مباشر)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      تكوين الاستراتيجية
    ├── analytics.py    حديث / إنفاق / زمن الاستجابة / توفير / لا يمكن الوصول
    ├── keys.py         إدراج / تدوير / إلغاء مفاتيح API
    ├── hosted.py       /v1/hosted — حالة الاحتياطي المستضاف للوحة التحكم
    └── health.py

packages/
├── litellm_adapter/    غلاف الموجه + كتالوج أكثر من 100 نموذج
├── auth/               التجزئة + AES-256-GCM
└── db/                 النماذج + المحرك + الجلسة
```

## خارطة الطريق

- [x] إكمالات المحادثة المتوافقة مع OpenAI
- [x] البث المباشر (SSE)
- [x] توجيه `model="auto"` الأرخص-القادر
- [x] المستضاف كمصدر علوي
- [x] BYOK مشفر في وضع الراحة
- [x] لوحة تحليلات محلية
- [x] CI (GitHub Actions)
- [x] التخزين المؤقت للموجهات عبر المزود
- [x] تكاملات Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] قياس معياري عام + ادعاء التوفير
- [ ] التضمينات + وكيل توليد الصور

انظر [DEMO.md](./DEMO.md) لعرض التحويل عند الفشل.

## الترخيص

MIT. انظر [LICENSE](./LICENSE).

</div>
