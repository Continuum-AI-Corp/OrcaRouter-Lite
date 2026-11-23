# OrcaRouter Lite

**हर कोडिंग एजेंट पर बजट लगाएँ।**
देखें और सीमित करें कि Claude Code, Aider, Cursor और आपके अपने ऐप्स हर मॉडल प्रोवाइडर पर कितना खर्च करते हैं — और आपके प्रॉम्प्ट्स आपकी मशीन से बाहर नहीं जाते। एक डेवलपर के लिए मेन्यू-बार ऐप, और पूरी टीम के लिए self-hosted राउटर। MIT लाइसेंस।

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="OrcaRouter Lite का मेन्यू-बार पैनल: दैनिक बजट के मुकाबले आज का खर्च, कनेक्टेड कोडिंग एजेंट और प्रोवाइडर की स्थिति" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="पहली बार का सेटअप: पहचाने गए कोडिंग एजेंट, requests कहाँ जाती हैं, और एक दैनिक बजट" width="420">
</p>

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

**हमें यहाँ भी पाएँ:** [सभी मॉडल API](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite, [OrcaRouter](https://www.orcarouter.ai) का ओपन-सोर्स संस्करण है। यह आपके कंप्यूटर या आपके सर्वर पर चलता है, OpenAI, Anthropic और Gemini API बोलता है, और आउटेज के समय तथा उन मॉडलों के लिए जिनकी कुंजियाँ आपके पास नहीं हैं, hosted `api.orcarouter.ai` को सेफ्टी नेट के रूप में उपयोग कर सकता है।

## डेस्कटॉप ऐप

Orca ऐप आपके मेन्यू बार में रहता है। यह `127.0.0.1` पर राउटर चलाता है, आपके कोडिंग एजेंटों को उससे कनेक्ट करता है, और दिखाता है कि वे कितना खर्च करते हैं।

- **आज का खर्च, प्रति एजेंट।** आज का कुल खर्च घड़ी के बगल में दिखता है; पैनल इसे एजेंट के हिसाब से बाँटता है।
- **दैनिक बजट।** आपकी तय की गई राशि के 80% और 100% पर नोटिफ़िकेशन। डिफ़ॉल्ट रूप से सिर्फ़ अलर्ट; एक बॉक्स टिक करें और राशि पूरी होते ही Orca आपके कोडिंग एजेंटों को पॉज़ कर देता है।
- **वन-क्लिक कनेक्ट।** Orca एजेंट की अपनी सेटिंग्स बदलता है, उनका बैकअप रखता है, और डिस्कनेक्ट करने पर उन्हें वापस बहाल कर देता है।
- **कभी डाउन नहीं।** जब कोई प्रोवाइडर फेल होता है या आप पर rate limit लगाता है, तो requests किसी दूसरे प्रोवाइडर या hosted OrcaRouter पर फ़ॉलबैक कर जाती हैं, और ऐप गिनता है कि उसने कितनी requests बचाईं।
- **डिफ़ॉल्ट रूप से प्राइवेट।** प्रॉम्प्ट्स आपके एजेंटों से सीधे आपके चुने हुए प्रोवाइडर तक जाते हैं। कोई टेलीमेट्री नहीं।
- **आपकी टीम के gateway के साथ काम करता है।** `orca login https://ai-gw.example.com --key …` (या सेटअप में "Join my company's gateway") आपके एजेंटों को उस gateway की ओर पॉइंट करता है जिसे आपकी प्लेटफ़ॉर्म टीम चलाती है; `orca logout` उन्हें वापस बहाल कर देता है।

**इंस्टॉल।** इंस्टॉलर (`.dmg`, `.deb`, `.AppImage`, `.msi`) [`desktop.yml`](./.github/workflows/desktop.yml) से बनते हैं और अगले टैग किए गए वर्ज़न से शुरू होकर हर रिलीज़ के साथ अटैच किए जाते हैं। तब तक, वही इंजन और CLI बस एक कमांड दूर हैं:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` पैनल को `http://127.0.0.1:8765/desktop/panel.html` पर सर्व करता है; मेन्यू-बार ऐप खुद बिल्ड करने के लिए [`desktop/`](./desktop/README.md) देखें। पहली रिलीज़ आने के बाद, Apple silicon Mac उपयोगकर्ता `brew install --cask continuum-ai-corp/tap/orcarouter-lite` से भी इंस्टॉल कर सकेंगे।

Claude Code के स्टेटस बार में आज का खर्च: इसे `~/.claude/settings.json` में जोड़ें।

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` हफ़्ते का ब्योरा Markdown (या `--format csv`) में प्रिंट करता है, ताकि आप उसे किसी चैट या शीट में पेस्ट कर सकें।

| एजेंट | कैसे कनेक्ट होता है |
|---|---|
| Claude Code | स्वचालित: `~/.claude/settings.json` में `ANTHROPIC_BASE_URL` और एक अलग कुंजी सेट करता है |
| Aider | स्वचालित: `~/.aider.conf.yml` में `openai-api-base`, एक अलग कुंजी और `model: openai/auto` सेट करता है |
| Cursor | एक पेस्ट स्टेप: ऐप Cursor की मॉडल सेटिंग्स के लिए एक base URL और कुंजी दिखाता है |
| Codex | जल्द आ रहा है: इसके लिए OpenAI Responses API (`/v1/responses`) चाहिए, जिसे Lite अभी सर्व नहीं करता |
| Gemini CLI | जल्द आ रहा है |

हर कनेक्टेड एजेंट को अपनी अलग कुंजी मिलती है: इसी से खर्च प्रति एजेंट बँटता है, और इसी वजह से डिस्कनेक्ट करते ही एक्सेस तुरंत रद्द हो जाता है। ऐप आपके कंप्यूटर पर क्या-क्या छू सकता है, यह [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch) में विस्तार से बताया गया है।

<a id="free-and-open-for-good"></a>
## मुफ़्त और ओपन, हमेशा के लिए

- **MIT, स्थायी रूप से।** एक डेवलपर या एक टीम को जो कुछ भी चाहिए, वह इसी रिपॉज़िटरी में MIT के तहत रहता है: रूटिंग, `model="auto"`, बजट, डैशबोर्ड, डेस्कटॉप ऐप। हम कोई भी फ़ीचर Lite से हटाकर पेड प्लान में नहीं ले जाएँगे।
- **पेड प्लान संगठनों के लिए है।** कई टीमों का प्रबंधन (SSO/SCIM, रोल-आधारित एक्सेस, पूरे संगठन के लिए बजट और पॉलिसी, ऑडिट रिटेंशन, Slack और ईमेल पर अलर्ट) [hosted OrcaRouter](https://www.orcarouter.ai) में है।
- **सत्यापन योग्य।** रिलीज़ साइन की जाती हैं और provenance तथा SBOM के साथ आती हैं। देखें [SECURITY.md](./SECURITY.md)।

## दूसरों से तुलना

| | किसके लिए सबसे अच्छा | कैसे चलता है |
|---|---|---|
| **OrcaRouter Lite** | एक डेवलपर से लेकर ऐसी टीम तक, जिसे नए इंफ्रास्ट्रक्चर के बिना प्रति-एजेंट खर्च, बजट और failover चाहिए | डेस्कटॉप ऐप, `uvx`/`pip`, या Docker; डिफ़ॉल्ट रूप से SQLite |
| LiteLLM proxy | ऐसी टीमें जिन्हें बड़ी कॉन्फ़िगरेशन सतह और Python SDK चाहिए | Self-hosted सर्वर; खर्च ट्रैकिंग के लिए Postgres |
| OpenRouter | कई मॉडलों के लिए एक API कुंजी, बिलिंग उन्हीं के ज़रिए | केवल hosted; प्रॉम्प्ट्स उनकी सेवा से होकर गुज़रते हैं |
| Claude Code का अपना gateway सपोर्ट | ऐसी कंपनियाँ जो केवल Claude इस्तेमाल करती हैं | Claude Code को आपके द्वारा चलाए गए gateway पर पॉइंट करता है; केवल Claude मॉडल |

## इसे सर्वर के रूप में चलाएँ (60 सेकंड)

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

## `model="auto"`

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

| प्लेटफ़ॉर्म | कैसे |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (अगली टैग की गई रिलीज़ से प्रकाशित होगी; [SECURITY.md](./SECURITY.md) में दिए कमांड से इसे सत्यापित करें) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | रेपो कनेक्ट करें, root dir = `.` |
| Railway | टेम्पलेट जल्द आ रहा है (#181 में ट्रैक किया जा रहा है) |

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
- `/v1/app/*` — डेस्कटॉप ऐप के लिए एजेंट, खर्च सारांश और बजट (केवल तब जब `orca up` से शुरू किया गया हो; देखें [SECURITY.md](./SECURITY.md))
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

ये संगठनों के लिए फ़ीचर हैं और [hosted OrcaRouter](https://www.orcarouter.ai) में उपलब्ध हैं; देखें [मुफ़्त और ओपन, हमेशा के लिए](#free-and-open-for-good)।

## टेस्टिंग

टेस्ट-फ़र्स्ट बनाया गया: यहाँ शिप किए गए हर व्यवहार के लिए पहले एक फेल होने वाला टेस्ट था।

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

## रोडमैप

- [x] OpenAI-compatible चैट कंप्लीशन, स्ट्रीमिंग, `model="auto"`
- [x] Anthropic और Gemini के नेटिव एंडपॉइंट
- [x] Hosted-as-upstream फ़ॉलबैक, एन्क्रिप्टेड BYOK, लोकल डैशबोर्ड
- [x] Cross-provider प्रॉम्प्ट कैश
- [x] डेस्कटॉप ऐप: मेन्यू बार में खर्च, दैनिक बजट अलर्ट, वन-क्लिक एजेंट कनेक्ट
- [x] provenance और SBOM के साथ साइन की गई रिलीज़; हैश-लॉक्ड dependencies
- [x] दैनिक बजट जो अलर्ट करता है, या सीमा पर कोडिंग एजेंटों को पॉज़ कर देता है
- [x] `orca login` / "Join my company's gateway": ऐप से ही किसी टीम के gateway का इस्तेमाल
- [ ] `/v1/responses`, ताकि Codex कनेक्ट हो सके
- [ ] साझा टीम gateway पर लागू होने वाले प्रति-डेवलपर बजट
- [ ] Embeddings, Ollama/vLLM providers, कस्टम फ़ॉलबैक चेन

Failover डेमो के लिए [DEMO.md](./DEMO.md) देखें।

<a id="license"></a>
## लाइसेंस

MIT। देखें [LICENSE](./LICENSE)।
