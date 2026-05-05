# ओर्काराउटर लाइट

**प्रबंधित सुरक्षा जाल के साथ स्व-होस्टेड एलएलएम राउटर।**
OpenAI-संगत। ब्योक. एकल-कार्यक्षेत्र। स्ट्रीमिंग. `मॉडल='ऑटो'`।

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![परीक्षण](https://img.shields.io/ Badge/tests-127_passing-brightgreen)](#परीक्षण)
[![मॉडल](https://img.shields.io/ Badge/models-100%2B-blue)](#model-catalog)
[![लाइसेंस](https://img.shields.io/ Badge/license-MIT-blue)](#license)

## भाषाएँ

- [अंग्रेजी](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [जर्मन](./README.de.md)
- [फ़्रांसीसी](./README.fr.md)
- [Español](./README.es.md)
- [इतालवी](./README.it.md)
- [Русский](./README.ru.md)
- [पुर्तगाली](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite [OrcaRouter](https://www.orcarouter.ai) का ओपन-सोर्स सिंगल-वर्कस्पेस संस्करण है। इसे अपने लैपटॉप पर चलाएं, इसे अपने उत्पाद में शिप करें, या उन मॉडलों की लंबी श्रृंखला के लिए सीधे होस्ट किए गए `api.orcarouter.ai` का उपयोग करें जिनके लिए आप कुंजी प्रबंधित नहीं करना चाहते हैं।

> **हम क्यों?** लाइटएलएलएम एक पुस्तकालय है; ओपनराउटर क्लोज-सोर्स होस्ट किया गया है; ओलामा केवल स्थानीय है। हम **प्रबंधित फ़ॉलबैक के साथ स्वयं-होस्ट किए गए सर्वर** हैं - एक ऐसा वाक्य जो इनमें से कोई भी नहीं कह सकता।

## 60-सेकंड की त्वरित शुरुआत

OrcaRouter का उपयोग करने के दो तरीके:

### पथ ए - स्व-होस्टेड (BYOK)

अपनी मशीन पर लाइट चलाएँ; अपनी स्वयं की प्रदाता कुंजियाँ लाएँ।

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

बेस यूआरएल: `http://localhost:8000/v1`. स्टार्टअप पर मुद्रित `sk-orca-*` कुंजी का उपयोग करें।

### पथ बी - होस्ट किया गया (खाता आवश्यक)

कोई क्लोन नहीं, कोई डॉकर नहीं. रजिस्टर करें, एक कुंजी प्राप्त करें, किसी भी OpenAI SDK को होस्ट पर इंगित करें।

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**खाता आवश्यक है।** होस्टेड रूटिंग, बिलिंग और प्रदाताओं की लंबी पूंछ को संभालता है - आपके OrcaRouter खाते पर प्रति-टोकन बिल किया जाता है। [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction) देखें।

### फिर इसे किसी भी OpenAI SDK से कॉल करें

नीचे दिए गए उदाहरण पथ ए के लोकलहोस्ट बेस यूआरएल का उपयोग करते हैं - यदि आप पथ बी पर हैं तो `https://api.orcarouter.ai/v1` के लिए स्वैप करें।

<विवरण>
<सारांश><b>पायथन</b></सारांश>

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
</विवरण>

<विवरण>
<सारांश><b>Node.js</b></सारांश>

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
</विवरण>

<विवरण>
<सारांश><b>कर्ल</b></सारांश>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</विवरण>

डैशबोर्ड के लिए `http://localhost:8000/` खोलें - प्रदाता, रूटिंग, एनालिटिक्स, कुंजियाँ (केवल पथ A)।

## क्यों?

| | लाइट | लाइटएलएलएम लाइब्रेरी | ओपनराउटर | ओलामा |
|---|---|---|---|---|
| स्व-होस्टेड सर्वर | ✓ | एक पुस्तकालय के रूप में | ✗ | ✓ |
| OpenAI-संगत | ✓ | ✓ | ✓ | ✓ |
| बहु-प्रदाता (ओपनएआई/एंथ्रोपिक/गूगल/…) | ✓ | ✓ | ✓ | ✗ |
| अंतर्निर्मित डैशबोर्ड | ✓ | ✗ | ✓ | ✗ |
| `मॉडल='ऑटो'` (सबसे सस्ता सक्षम) | ✓ | ✗ | ✗ | एन/ए |
| स्ट्रीमिंग | ✓ | ✓ | ✓ | ✓ |
| ब्योक | ✓ | ✓ | ✗ | एन/ए |
| फ़ॉलबैक के रूप में होस्ट किया गया | ✓ | ✗ | एन/ए | ✗ |
| कोई पोस्टग्रेज़/कोई रेडिस आवश्यक नहीं | ✓ | एन/ए | एन/ए | ✓ |

## `मॉडल = "ऑटो"` - शीर्षक विशेषता

`model='auto'` भेजें और OrcaRouter आपके कॉन्फ़िगर किए गए प्रदाताओं में **सबसे सस्ता** मॉडल चुनता है जो अनुरोध की क्षमता आवश्यकताओं (टूल्स, विज़न, JSON मोड) को पूरा करता है। कोई मैन्युअल रूटिंग नियम नहीं; कोई दर-सीमा जिम्नास्टिक नहीं; आपके कोड में कोई `if x: ...` लागत अनुकूलन नहीं है।

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

हल किया गया मॉडल `x-orca-resolved-model` प्रतिक्रिया हेडर के माध्यम से कॉल करने वालों के सामने वापस आ जाता है ताकि आप लॉग इन/प्रदर्शित कर सकें कि वास्तव में क्या उपयोग किया गया था।

## अपस्ट्रीम के रूप में होस्ट किया गया (लाइट + होस्ट किया गया)

पहले से ही लाइट चल रहा है? [www.orcarouter.ai](https://www.orcarouter.ai) से `ORCAROUTER_API_KEY` को अपने `sk-orca-*` पर सेट करें, और होस्टेड रूटिंग श्रृंखला में एक और प्रदाता बन जाता है - ऐसे मॉडल को कवर करना जो आपकी स्थानीय कुंजियाँ नहीं करतीं:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

उपयोग के मामले:
- **खरीदने से पहले प्रयास करें** - किसी स्थानीय प्रदाता कुंजी की आवश्यकता नहीं है
- **स्थानीय लॉगिंग** - होस्टेड हैंडल रूटिंग, लाइट डैशबोर्ड के लिए रिक्वेस्टलॉग पंक्तियों को संग्रहीत करता है
- **फ़ेलओवर** - स्थानीय प्रदाता विफल, होस्ट किया गया सुरक्षा जाल है

## स्ट्रीमिंग

मानक `डेटा: ... \n\n` फ़्रेमिंग और एक टर्मिनल `[DONE]` प्रहरी के साथ ओपनएआई-संगत एसएसई प्रारूप - किसी भी एसडीके के लिए ड्रॉप-इन जो पहले से ही ओपनएआई से स्ट्रीम होता है।

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## मॉडल सूची

[लाइटएलएलएम के समुदाय-रखरखाव मूल्य निर्धारण डेटाबेस] (https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) से स्टार्टअप पर 100+ चैट मॉडल लोड किए जाते हैं - मैन्युअल रूप से बनाए रखने के लिए कोई मॉडल सूची नहीं है। प्रत्येक प्रविष्टि उजागर करती है:

- `आईडी` (जैसे `जीपीटी-4ओ`, `क्लाउड-3-5-सॉनेट-नवीनतम`)
- `प्रदाता` (आपकी कॉन्फ़िगर की गई कुंजियों पर मैप किया गया)
- क्षमता झंडे: `support_tools`, `support_vision`, `support_json_mode`
- प्रति-टोकन इनपुट/आउटपुट लागत (बचत विजेट + `मॉडल='ऑटो'` चलाता है)

`GET /v1/models` OpenAI-प्रारूप कैटलॉग लौटाता है।

## कहीं और तैनात करना

| प्लेटफार्म | एक क्लिक |
|---|---|
| रेलवे | [![रेलवे पर तैनाती](https://railway.app/button.svg)](https://railway.app/new/template) |
| फ्लाई.आईओ | `फ्लाई लॉन्च--डॉकरफाइल डॉकरफाइल` |
| प्रस्तुत करना | रेपो कनेक्ट करें, रूट डीआईआर = `.` |
| नंगे डोकर | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (छवि जल्द ही आ रही है) |

## बॉक्स में क्या है

- `POST /v1/chat/completions` - प्रॉक्सी + स्ट्रीमिंग + `मॉडल = "ऑटो"` + क्रॉस-प्रोवाइडर प्रॉम्प्ट कैश
- `GET /v1/models` - खोजने योग्य मॉडल कैटलॉग (`litellm.model_cost` से 100+ मॉडल)
- `प्राप्त/पुट/हटाएं /v1/प्रदाता/{प्रदाता}` - एन्क्रिप्टेड प्रदाता कुंजी सेट करें / सूचीबद्ध करें / निरस्त करें
- `प्राप्त/पुट /v1/रूटिंग` - रणनीति बदलें (`संतुलित` / `सबसे सस्ता` / `सबसे तेज` / `गुणवत्ता`)
- `प्राप्त करें /v1/एनालिटिक्स/{हाल ही में, खर्च, विलंबता, बचत, पहुंच योग्य नहीं}` - स्थानीय एनालिटिक्स, कोई टेलीमेट्री बॉक्स नहीं छोड़ती है
- `GET /v1/hosted` - होस्टेड-फ़ॉलबैक स्थिति (डैशबोर्ड के "$5 मुफ़्त क्रेडिट प्राप्त करें" कार्ड चलाती है)
- `प्राप्त करें/पोस्ट करें/हटाएं /v1/कुंजियाँ/...` - एपीआई कुंजियों को सूचीबद्ध करें / घुमाएँ / निरस्त करें
- `/` पर सिंगल-पेज डैशबोर्ड
- डिफ़ॉल्ट रूप से SQLite; `DATABASE_URL` के माध्यम से पोस्टग्रेज ऑप्ट-इन; रेडिस वैकल्पिक

### क्रॉस-प्रदाता शीघ्र कैश

नियतात्मक अनुरोध (`तापमान = 0` या पिन किए गए `बीज`) को बार-बार कैश से परोसा जाता है - केवल एंथ्रोपिक ही नहीं, **प्रत्येक** प्रदाता पर काम करता है। जब `REDIS_URL` सेट होता है तो बैकएंड रेडिस होता है, अन्यथा इन-प्रोसेस LRU होता है। कैश हिट तुरंत `x-orca-cache: HIT` के साथ लौटता है और लागत $0 होती है।

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### बचत विजेट

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` रिपोर्ट करता है कि आपके ट्रैफ़िक की हमेशा-GPT-4 पर लागत क्या होगी बनाम वास्तव में इसकी लागत क्या होगी। डैशबोर्ड इसे एक टाइल के रूप में दिखाता है।

### एकीकरण

[जारी रखें.dev](./integrations/dependent.json), [Aider](./integrations/aider.md), [कर्सर](./integrations/cursor.md), [LangChain](./integrations/langचेन_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), के लिए ड्रॉप-इन कॉन्फ़िगरेशन [Vercel AI SDK](./integrations/vercel_ai.ts), और कोई भी टूल जो OpenAI चैट कंप्लीशन प्रोटोकॉल बोलता है। [`एकीकरण/`](./एकीकरण/) देखें।

## जानबूझकर क्या नहीं है

यह **एकल-कार्यक्षेत्र** संस्करण है। डिज़ाइन के अनुसार, नहीं:
- मल्टी-टेनेंसी, आरबीएसी, एसएसओ
- बिलिंग, वॉलेट, पॉइंट, पार्टनर प्रोग्राम
- एडमिन कंसोल, ऑडिट लॉग, विश्वास और सुरक्षा
- मल्टी-पॉड परिनियोजन / कुबेरनेट्स
- अलर्ट के लिए ईमेल / स्लैक / वेबहुक

उनके लिए, होस्ट किए गए उत्पाद या (आगामी) टीम संस्करण देखें।

## परीक्षण

निर्मित परीक्षण-प्रथम. यहां भेजे गए प्रत्येक व्यवहार का पहले एक असफल परीक्षण होता था।

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| टुकड़ा | टेस्ट | क्या |
|---|---|---|
| 1. कॉन्फिग | 5 | env लोडिंग, डिफ़ॉल्ट, `env_provider_keys()` |
| 2. बीज | 3 | बूटस्ट्रैप कार्यक्षेत्र + एपीआई कुंजी + रूटिंग कॉन्फिग, इडेम्पोटेंट |
| 3. प्रामाणिक मिडलवेयर | 4 | बियरर-टोकन सत्यापन, 401 गुम/अमान्य पर |
| 4. ऐप फैक्ट्री | 3 | /स्वास्थ्य, त्रुटि लिफाफा, /v1/* गेटिंग |
| 5. प्रदाता कुंजी CRUD | 5 | आराम से एन्क्रिप्टेड, प्लेनटेक्स्ट कभी राउंड-ट्रिप नहीं करता है |
| 6. राउटर कैश | 13 | env+DB+ने प्राथमिकता के साथ परिनियोजन असेंबली की मेजबानी की |
| 7. चैट पूर्ण होना | 5 | OpenAI प्रारूप, RequestLog, सत्यापन |
| 8. विश्लेषिकी | 4 | हालिया/व्यय/विलंबता p50/p99 |
| 9. /v1/{मॉडल,कुंजियाँ,रूटिंग} | 8 | सूची/बनाएं/निरस्त करें + रणनीति अद्यतन |
| 10. स्ट्रीमिंग | 4 | एसएसई प्रारूप, `[संपन्न]` प्रहरी, लॉग राइटबैक |
| 11. कैटलॉग | 7 | 100+ मॉडल, क्षमता झंडे, मूल्य निर्धारण |
| 12. `मॉडल='ऑटो' | 21 | क्षमता का पता लगाना, सबसे सस्ती-आवश्यकताओं को पूरा करना (इकाई + एकीकरण) |
| 13. लागत बचत | 9 | बचत बनाम हमेशा-जीपीटी-4 बेसलाइन + होस्टेड-ऑटो तुलना |
| 14. शीघ्र कैश | 15 | क्रॉस-प्रदाता सटीक-मिलान कैश + चैट एकीकरण |
| 15. बेंचमार्क | 4 | सारांश() + रेंडर_मार्कडाउन() एकत्रीकरण |
| 16. होस्ट स्थिति | 7 | `/v1/होस्टेड` कॉन्फिग-स्रोत + साइनअप-यूआरएल सतह |
| 17. होस्टेड-ऑटो बचत | 3 | सिंथेटिक कैटलॉग पर `_hosted_auto_savings` एज केस |
| 18. अगम्य मॉडल | 7 | होस्ट चालू होने पर "मॉडल जिन तक आप नहीं पहुंच सकते" टाइल साफ़ हो जाती है |
| **कुल** | **127** | |

## वास्तुकला

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

- [x] ओपनएआई-संगत चैट पूर्णताएं
- [x] स्ट्रीमिंग (एसएसई)
- [x] `मॉडल='ऑटो'` सबसे सस्ता-सक्षम रूटिंग
- [x] होस्ट-एज़-अपस्ट्रीम
- [x] आराम पर एन्क्रिप्टेड BYOK
- [x] स्थानीय विश्लेषण डैशबोर्ड
- [x] सीआई (गिटहब क्रियाएँ)
- [x] क्रॉस-प्रदाता शीघ्र कैशिंग
- [x] कंटिन्यू.डेव / एडर / लैंगचेन / कर्सर / वर्सेल एआई एसडीके एकीकरण
- [x] सार्वजनिक बेंचमार्क + बचत दावा
- [ ] एंबेडिंग्स + इमेज-जेन प्रॉक्सी

फ़ेलओवर डेमो के लिए [DEMO.md](./DEMO.md) देखें।

## लाइसेंस

एमआईटी. [लाइसेंस](./लाइसेंस) देखें।
