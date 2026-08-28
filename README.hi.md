# OrcaRouter Lite

**मैनेज्ड सेफ्टी नेट के साथ self-hosted LLM राउटर।**
OpenAI-compatible। BYOK। एकल-वर्कस्पेस। स्ट्रीमिंग। `model="auto"`।

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

![OrcaRouter Lite फेलओवर डेमो](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"` रीयल-टाइम में प्रोवाइडर आउटेज को सोख लेता है — कोड में कोई बदलाव नहीं। रिकॉर्डिंग तरीका: [DEMO.md](./DEMO.md)।*

## भाषाएँ

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

OrcaRouter Lite, [OrcaRouter](https://www.orcarouter.ai) का ओपन-सोर्स single-workspace संस्करण है। इसे अपने लैपटॉप पर चलाएँ, अपने प्रोडक्ट में पैक करें, या उन मॉडलों की लंबी टेल के लिए सीधे hosted `api.orcarouter.ai` का उपयोग करें जिनकी कुंजियाँ आप खुद नहीं मैनेज करना चाहते।

> **हम क्यों?** LiteLLM एक लाइब्रेरी है; OpenRouter closed-source hosted है; Ollama केवल local है। हम **मैनेज्ड फ़ॉलबैक के साथ self-hosted सर्वर** हैं — एक ऐसा वाक्य जो उनमें से कोई नहीं कह सकता।

## 60-सेकंड क्विकस्टार्ट

OrcaRouter उपयोग करने के दो तरीके:

### पथ A — Self-hosted (BYOK)

Lite को अपनी मशीन पर चलाएँ; अपनी provider कुंजियाँ साथ लाएँ।

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# कम से कम एक जोड़ें: OPENAI_API_KEY=sk-...  (या ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

बेस URL: `http://localhost:8000/v1`। स्टार्टअप पर प्रिंट हुई `sk-orca-*` कुंजी का उपयोग करें।

### पथ B — Hosted (खाता आवश्यक)

न क्लोन, न docker। पंजीकरण करें, कुंजी प्राप्त करें, किसी भी OpenAI SDK को hosted पर पॉइंट करें।

```bash
# 1. https://www.orcarouter.ai पर पंजीकरण करें और अपनी sk-orca-* कुंजी कॉपी करें
# 2. बेस URL के रूप में https://api.orcarouter.ai/v1 का उपयोग करें
```

**खाता आवश्यक।** Hosted, रूटिंग, बिलिंग और providers की लंबी टेल को संभालता है — आपके OrcaRouter खाते पर प्रति-टोकन बिलिंग के साथ। देखें [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction)।

### फिर इसे किसी भी OpenAI SDK से कॉल करें

नीचे के उदाहरण पथ A के localhost बेस URL का उपयोग करते हैं — यदि आप पथ B पर हैं तो `https://api.orcarouter.ai/v1` से बदलें।

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # या "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

डैशबोर्ड के लिए `http://localhost:8000/` खोलें — providers, रूटिंग, analytics, कुंजियाँ (केवल पथ A)।

## क्यों?

| | OrcaRouter Lite | LiteLLM लाइब्रेरी | OpenRouter | Ollama |
|---|---|---|---|---|
| Self-hosted सर्वर | ✓ | लाइब्रेरी के रूप में | ✗ | ✓ |
| OpenAI-compatible | ✓ | ✓ | ✓ | ✓ |
| Multi-provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| बिल्ट-इन डैशबोर्ड | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (सबसे सस्ता सक्षम) | ✓ | ✗ | ✗ | n/a |
| स्ट्रीमिंग | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hosted-as-fallback | ✓ | ✗ | n/a | ✗ |
| न Postgres / न Redis आवश्यक | ✓ | n/a | n/a | ✓ |

## `model="auto"` — मुख्य फ़ीचर

`model="auto"` भेजें और OrcaRouter आपके कॉन्फ़िगर किए गए providers में से **सबसे सस्ता** मॉडल चुनेगा जो request की क्षमता आवश्यकताओं (tools, vision, JSON मोड) को पूरा करता है। न मैनुअल रूटिंग नियम; न rate-limit जिमनास्टिक्स; आपके कोड में न कोई `if x: ...` कॉस्ट ऑप्टिमाइज़ेशन।

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → आपकी कुंजियों द्वारा कवर सबसे सस्ते VISION-सक्षम मॉडल पर रूट करता है
```

समाधान किया गया मॉडल `x-orca-resolved-model` रिस्पॉन्स हेडर के माध्यम से कॉलर को वापस उजागर किया जाता है, ताकि आप लॉग/प्रदर्शित कर सकें कि वास्तव में क्या उपयोग हुआ।

## Hosted को upstream के रूप में (Lite + hosted)

पहले से Lite चला रहे हैं? `ORCAROUTER_API_KEY` को [www.orcarouter.ai](https://www.orcarouter.ai) से अपनी `sk-orca-*` पर सेट करें, और hosted रूटिंग चेन में एक और provider बन जाता है — उन मॉडलों को कवर करते हुए जो आपकी local कुंजियों के पास नहीं हैं:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

उपयोग के मामले:
- **खरीदने-से-पहले-आज़माएँ** — local provider कुंजियों की आवश्यकता नहीं
- **लोकल लॉगिंग** — hosted रूटिंग संभालता है, Lite डैशबोर्ड के लिए RequestLog रिकॉर्ड संग्रहित करता है
- **Failover** — local providers विफल होते हैं, hosted सेफ्टी नेट है

## स्ट्रीमिंग

मानक `data: ... \n\n` फ्रेमिंग और टर्मिनल `[DONE]` सेन्टिनल के साथ OpenAI-compatible SSE फ़ॉर्मेट — किसी भी SDK के लिए drop-in जो पहले से OpenAI से स्ट्रीम करता है।

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## नेटिव प्रोटोकॉल एंडपॉइंट (Anthropic + Gemini)

Lite एक ही रूटिंग पाइपलाइन पर तीन इनबाउंड प्रोटोकॉल बोलता है। जो क्लाइंट केवल Anthropic या Gemini wire फ़ॉर्मेट बोलते हैं, वे सीधे कनेक्ट होते हैं — किसी OpenAI SDK की आवश्यकता नहीं:

```bash
# Claude Code, Lite पर पॉइंट किया गया (बेस URL में /v1 सफ़िक्स नहीं)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK, Lite पर पॉइंट किया गया
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Requests को एज पर उसी आंतरिक पाइपलाइन में अनुवादित किया जाता है, इसलिए `model="auto"`, cross-provider प्रॉम्प्ट कैश (सभी प्रोटोकॉल में साझा), रूटिंग रणनीतियाँ और analytics डैशबोर्ड सभी एक जैसे काम करते हैं। गाइड: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md)।

## मॉडल कैटलॉग

स्टार्टअप पर 100+ चैट मॉडल [LiteLLM के समुदाय-संचालित मूल्य डेटाबेस](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) से लोड किए जाते हैं — कोई मॉडल सूची मैनुअली बनाए रखने के लिए नहीं। प्रत्येक प्रविष्टि उजागर करती है:

- `id` (जैसे `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (आपकी कॉन्फ़िगर की गई कुंजियों पर मैप)
- क्षमता फ्लैग्स: `supports_tools`, `supports_vision`, `supports_json_mode`
- प्रति-टोकन इनपुट/आउटपुट लागत (बचत विजेट + `model="auto"` को चलाती है)

`GET /v1/models` OpenAI-format कैटलॉग लौटाता है।

## कहीं और डिप्लॉय करें

| प्लेटफ़ॉर्म | वन-क्लिक |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | रेपो कनेक्ट करें, root dir = `.` |
| बेयर Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (इमेज जल्द आ रही है) |

## बॉक्स में क्या है

- `POST /v1/chat/completions` — proxy + स्ट्रीमिंग + `model="auto"` + cross-provider प्रॉम्प्ट कैश
- `POST /v1/messages` — **Anthropic Messages API इनग्रेस** (Claude Code / Anthropic SDK सीधे कनेक्ट होते हैं; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **Gemini API इनग्रेस** (google-genai SDK सीधे कनेक्ट होता है; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — खोज योग्य मॉडल कैटलॉग (`litellm.model_cost` से 100+ मॉडल)
- `GET/PUT/DELETE /v1/providers/{provider}` — एन्क्रिप्टेड provider कुंजियाँ सेट / सूचीबद्ध / रद्द करें
- `GET/PUT /v1/routing` — रणनीति बदलें (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — local analytics, कोई टेलीमेट्री बॉक्स से बाहर नहीं जाती
- `GET  /v1/hosted` — hosted-fallback स्थिति (डैशबोर्ड के "Get $5 free credit" कार्ड को चलाती है)
- `GET/POST/DELETE /v1/keys/...` — API कुंजियाँ सूचीबद्ध / रोटेट / रद्द करें
- `/` पर सिंगल-पेज डैशबोर्ड
- डिफ़ॉल्ट रूप से SQLite; `DATABASE_URL` के माध्यम से Postgres opt-in; Redis वैकल्पिक

### Cross-provider प्रॉम्प्ट कैश

डिटरमिनिस्टिक requests (`temperature=0` या पिन की गई `seed`) दोहराव पर कैश से सर्व होते हैं — यह **हर** provider पर काम करता है, केवल Anthropic पर नहीं। Backend Redis है यदि `REDIS_URL` सेट है, अन्यथा in-process LRU। कैश हिट तुरंत `x-orca-cache: HIT` के साथ लौटते हैं और लागत $0।

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # वही payload फिर से
HTTP/1.1 200 OK
x-orca-cache: HIT          ← कैश से सर्व, कोई upstream कॉल नहीं
```

### बचत विजेट

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` बताता है कि आपका ट्रैफ़िक हमेशा-GPT-4 पर कितना खर्च होता बनाम वास्तव में कितना खर्च हुआ। डैशबोर्ड इसे एक टाइल के रूप में दिखाता है।

### इंटीग्रेशन

[Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) और किसी भी टूल के लिए drop-in कॉन्फ़िगरेशन जो OpenAI Chat Completions प्रोटोकॉल बोलता है — साथ ही नेटिव Anthropic और Gemini wire फ़ॉर्मेट भी। देखें [`integrations/`](./integrations/)।

## जो जानबूझकर नहीं है

यह **single-workspace** संस्करण है। डिज़ाइन के अनुसार, नहीं:
- मल्टी-टेनेंसी, RBAC, SSO
- बिलिंग, वॉलेट्स, पॉइंट्स, पार्टनर प्रोग्राम
- एडमिन कंसोल, ऑडिट लॉग्स, trust & safety
- मल्टी-पॉड डिप्लॉयमेंट / Kubernetes
- अलर्ट्स के लिए ईमेल / Slack / webhooks

उनके लिए, hosted प्रोडक्ट या (आगामी) Teams संस्करण देखें।

## टेस्टिंग

टेस्ट-फ़र्स्ट बनाया गया। यहाँ शिप किए गए हर व्यवहार के लिए पहले एक फेल होने वाला टेस्ट था।

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| स्लाइस | टेस्ट | क्या |
|---|---|---|
| 1. Config | 5 | env लोडिंग, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + API कुंजी + RoutingConfig, idempotent |
| 3. Auth मिडलवेयर | 4 | bearer-token सत्यापन, अनुपस्थित/अमान्य पर 401 |
| 4. App factory | 3 | /health, error envelope, /v1/* gating |
| 5. Provider कुंजी CRUD | 5 | रेस्ट पर एन्क्रिप्टेड, plaintext कभी round-trip नहीं करता |
| 6. राउटर कैश | 13 | प्राथमिकता के साथ env+DB+hosted डिप्लॉयमेंट असेंबली |
| 7. चैट कंप्लीशन | 5 | OpenAI फ़ॉर्मेट, RequestLog, सत्यापन |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + रणनीति अपडेट |
| 10. स्ट्रीमिंग | 4 | SSE फ़ॉर्मेट, `[DONE]` सेन्टिनल, log writeback |
| 11. कैटलॉग | 7 | 100+ मॉडल, क्षमता फ्लैग्स, pricing |
| 12. `model="auto"` | 21 | क्षमता डिटेक्शन, सबसे-सस्ता-जो-ज़रूरत-पूरी-करता-है (unit + एकीकरण) |
| 13. लागत बचत | 9 | हमेशा-GPT-4 बेसलाइन बनाम बचत + hosted-auto तुलना |
| 14. प्रॉम्प्ट कैश | 15 | cross-provider exact-match कैश + चैट एकीकरण |
| 15. Benchmark | 4 | summarize() + render_markdown() एग्रीगेशन |
| 16. Hosted स्थिति | 7 | `/v1/hosted` config-source + signup-URL surface |
| 17. Hosted-auto बचत | 3 | सिंथेटिक कैटलॉग पर `_hosted_auto_savings` एज केस |
| 18. अनुपलब्ध मॉडल | 7 | "जिन मॉडलों तक नहीं पहुँच सकते" टाइल hosted चालू होने पर खाली हो जाती है |
| 19. मल्टी-प्रोटोकॉल auth | 6 | x-api-key / x-goog-api-key / ?key= स्कोपिंग, /v1beta guard, प्रति-प्रोटोकॉल 401 envelopes |
| 20. Anthropic `/v1/messages` | 53 | request/response/stream अनुवाद + इनग्रेस एकीकरण |
| 21. Gemini `/v1beta` | 40 | schema-enum सामान्यीकरण सहित अनुवाद + generateContent/stream इनग्रेस |
| **कुल** | **403** | |

स्लाइस पंक्तियाँ प्रत्येक स्लाइस के शिप होने पर जोड़े गए टेस्ट दिखाती हैं; कुल वर्तमान पूर्ण टेस्ट सुइट है।

## आर्किटेक्चर

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

## रोडमैप

- [x] OpenAI-compatible चैट कंप्लीशन
- [x] स्ट्रीमिंग (SSE)
- [x] `model="auto"` सबसे-सस्ता-सक्षम रूटिंग
- [x] Hosted-as-upstream
- [x] रेस्ट पर एन्क्रिप्टेड BYOK
- [x] लोकल analytics डैशबोर्ड
- [x] CI (GitHub Actions)
- [x] Cross-provider प्रॉम्प्ट कैशिंग
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK इंटीग्रेशन
- [x] सार्वजनिक benchmark + बचत दावा
- [ ] Embeddings + image-gen proxy

Failover डेमो के लिए [DEMO.md](./DEMO.md) देखें।

## लाइसेंस

MIT। देखें [LICENSE](./LICENSE)।
