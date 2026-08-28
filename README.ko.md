# 오르카라우터 라이트

**관리형 안전망을 갖춘 자체 호스팅 LLM 라우터.**
OpenAI 호환. BYOK. 단일 작업 공간. 스트리밍. `모델="자동"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![테스트](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![모델](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![라이센스](https://img.shields.io/badge/license-MIT-blue)](#license)

![OrcaRouter Lite 장애 조치 데모](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"`가 프로바이더 장애를 실시간으로 흡수 — 코드 변경 없음. 녹화 방법: [DEMO.md](./DEMO.md).*

## 언어

- [한국어](./README.md)
- [일본어](./README.ja.md)
- [중국어](./README.zh.md)
- [한국어](./README.ko.md)
- [독일어](./README.de.md)
- [프랑스어](./README.fr.md)
- [스페인어](./README.es.md)
- [이탈리아어](./README.it.md)
- [Русский](./README.ru.md)
- [포르투갈어](./README.pt.md)
- [Tiếng Viet](./README.vi.md)
- [힌디어](./README.hi.md)

OrcaRouter Lite는 [OrcaRouter](https://www.orcarouter.ai)의 오픈 소스 단일 작업 공간 버전입니다. 랩톱에서 실행하거나, 제품에 포함하여 배송하거나, 키를 관리하고 싶지 않은 모델의 롱테일에 직접 호스팅된 `api.orcarouter.ai`를 사용하세요.

> **왜 우리인가요?** LiteLLM은 도서관입니다. OpenRouter는 비공개 소스로 호스팅됩니다. Ollama는 로컬 전용입니다. 우리는 **관리형 대체 기능을 갖춘 자체 호스팅 서버**입니다. 누구도 말할 수 없는 문장입니다.

## 60초 빠른 시작

OrcaRouter를 사용하는 두 가지 방법:

### 경로 A — 자체 호스팅(BYOK)

자신의 컴퓨터에서 Lite를 실행하세요. 자신의 공급자 키를 가져오세요.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

기본 URL: `http://localhost:8000/v1`. 시작 시 인쇄된 `sk-orca-*` 키를 사용하세요.

### 경로 B — 호스팅(계정 필요)

클론도 없고 도커도 없습니다. 등록하고, 키를 받고, 호스팅된 OpenAI SDK를 지정하세요.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**계정이 필요합니다.** Hosted는 라우팅, 청구 및 공급자의 롱테일을 처리하며 OrcaRouter 계정에서 토큰별로 청구됩니다. [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction)을 참조하세요.

### 그런 다음 OpenAI SDK에서 호출하세요.

아래 예에서는 경로 A의 로컬 호스트 기본 URL을 사용합니다. 경로 B에 있는 경우 `https://api.orcarouter.ai/v1`로 바꿉니다.

<상세>
<summary><b>파이썬</b></summary>

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
</details>

<상세>
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

<상세>
<summary><b>컬</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

대시보드(공급자, 라우팅, 분석, 키)에 대해 `http://localhost:8000/`를 엽니다(경로 A만 해당).

## 왜?

| | 라이트 | LiteLLM 라이브러리 | 오픈라우터 | 올라마 |
|---|---|---|---|---|
| 자체 호스팅 서버 | ✓ | 도서관으로 | ✗ | ✓ |
| OpenAI 호환 | ✓ | ✓ | ✓ | ✓ |
| 다중 제공자(OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| 내장 대시보드 | ✓ | ✗ | ✓ | ✗ |
| `model="auto"`(가장 저렴함) | ✓ | ✗ | ✗ | 해당 없음 |
| 스트리밍 | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | 해당 없음 |
| 대체 호스팅 | ✓ | ✗ | 해당 없음 | ✗ |
| Postgres 없음/Redis 필요 없음 | ✓ | 해당 없음 | 해당 없음 | ✓ |

## `model="auto"` — 헤드라인 기능

`model="auto"`를 보내면 OrcaRouter는 요청의 기능 요구 사항(도구, 비전, JSON 모드)을 충족하는 구성된 공급자에서 **가장 저렴한** 모델을 선택합니다. 수동 라우팅 규칙이 없습니다. 속도 제한이 없는 체조; 코드에서 `if x: ...` 비용 최적화가 없습니다.

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

해결된 모델은 'x-orca-resolved-model' 응답 헤더를 통해 호출자에게 다시 노출되므로 실제로 사용된 내용을 기록/표시할 수 있습니다.

## 업스트림으로 호스팅됨(Lite + 호스팅됨)

이미 Lite를 실행 중이신가요? [www.orcarouter.ai](https://www.orcarouter.ai)에서 `ORCAROUTER_API_KEY`를 `sk-orca-*`로 설정하면 호스팅된 라우팅 체인에서 로컬 키가 지원하지 않는 모델을 다루는 공급자가 하나 더 추가됩니다.

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

사용 사례:
- **구매 전 체험** — 로컬 공급자 키가 필요하지 않습니다.
- **로컬 로깅** — 호스팅된 라우팅 처리, Lite는 대시보드에 대한 RequestLog 행 저장
- **장애 조치** — 로컬 공급자가 실패하면 호스팅이 안전망입니다.

## 스트리밍

표준 `data: ... \n\n` 프레이밍 및 터미널 `[DONE]` 센티널을 갖춘 OpenAI 호환 SSE 형식 — 이미 OpenAI에서 스트리밍하는 모든 SDK에 대한 드롭인입니다.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## 네이티브 프로토콜 엔드포인트(Anthropic + Gemini)

Lite는 하나의 라우팅 파이프라인에 대해 세 가지 수신 프로토콜을 말합니다. Anthropic 또는 Gemini 와이어 형식만 말하는 클라이언트도 직접 연결됩니다. OpenAI SDK가 필요하지 않습니다:

```bash
# Claude Code, pointed at Lite (no /v1 suffix in the base URL)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK, pointed at Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

요청은 에지에서 동일한 내부 파이프라인으로 변환되므로 `model="auto"`, 교차 제공자 프롬프트 캐시(프로토콜 간 공유), 라우팅 전략, 분석 대시보드가 모두 동일하게 작동합니다. 가이드: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md)를 참조하세요.

## 모델 카탈로그

시작 시 [LiteLLM의 커뮤니티에서 유지 관리하는 가격 데이터베이스](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)에서 100개 이상의 채팅 모델이 로드됩니다. 수동으로 유지 관리할 모델 목록이 없습니다. 각 항목은 다음을 노출합니다.

- `id`(예: `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider`(구성된 키에 매핑됨)
- 기능 플래그: `supports_tools`, `supports_vision`, `supports_json_mode`
- 토큰당 입/출력 비용(절감 위젯 + `model="auto"` 구동)

`GET /v1/models` returns the OpenAI-format catalogue.

## 다른 곳에 배포

| 플랫폼 | 원클릭 |
|---|---|
| 철도 | [![철도에 배포](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| 렌더링 | 저장소 연결, 루트 디렉토리 = `.` |
| 베어 도커 | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (이미지 제공 예정) |

## 상자 안에 무엇이 들어있나요?

- `POST /v1/chat/completions` — 프록시 + 스트리밍 + `model="auto"` + 교차 제공자 프롬프트 캐시
- `POST /v1/messages` — **Anthropic Messages API 인그레스**(Claude Code / Anthropic SDK가 직접 연결, `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **Gemini API 인그레스**(google-genai SDK가 직접 연결, `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET /v1/models` — 검색 가능한 모델 카탈로그(`litellm.model_cost`의 100개 이상의 모델)
- `GET/PUT/DELETE /v1/providers/{provider}` — 암호화된 공급자 키 설정/목록/해지
- `GET/PUT /v1/routing` — 전략 변경(`균형` / `가장 저렴함` / `가장 빠름` / `품질`)
- `GET /v1/analytics/{recent,spend,latency,savings,unreachable}` — 로컬 분석, 원격 분석 없음
- `GET /v1/hosted` — 호스팅 대체 상태(대시보드의 "5달러 무료 크레딧 받기" 카드 구동)
- `GET/POST/DELETE /v1/keys/...` — API 키 나열 / 회전 / 취소
- `/`의 단일 페이지 대시보드
- 기본적으로 SQLite; Postgres는 `DATABASE_URL`을 통해 선택합니다. Redis 선택 사항

### 교차 제공자 프롬프트 캐시

결정적 요청('온도=0' 또는 고정된 '시드')은 캐시에서 반복적으로 제공됩니다. Anthropic뿐만 아니라 **모든** 제공자에서 작동합니다. 'REDIS_URL'이 설정된 경우 백엔드는 Redis이고, 그렇지 않은 경우에는 in-process LRU입니다. 캐시 적중은 `x-orca-cache: HIT`로 즉시 반환되며 비용은 $0입니다.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### 저축 위젯

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` reports what your traffic would have cost on always-GPT-4 vs what it actually cost. The dashboard shows it as a tile.

### 통합

[Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI에 대한 드롭인 구성 SDK](./integrations/vercel_ai.ts) 및 OpenAI Chat Completions 프로토콜을 말하는 모든 도구입니다 — 여기에 네이티브 Anthropic 및 Gemini 와이어 형식도 추가됩니다. [`통합/`](./integrations/)을 참조하세요.

## 고의로 하지 않은 것

이것은 **단일 작업 공간** 버전입니다. 설계상 다음은 허용되지 않습니다.
- 멀티 테넌시, RBAC, SSO
- 청구, 지갑, 포인트, 파트너 프로그램
- 관리 콘솔, 감사 로그, 신뢰 및 안전
- 다중 포드 배포 / Kubernetes
- 알림을 위한 이메일/Slack/웹후크

이에 대해서는 호스팅된 제품 또는 (향후) Teams 버전을 참조하세요.

## 테스트

테스트 우선으로 구축되었습니다. 여기에 제공된 모든 동작에는 먼저 실패한 테스트가 있었습니다.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| 슬라이스 | 테스트 | 무엇 |
|---|---|---|
| 1. 구성 | 5 | 환경 로딩, 기본값, `env_provider_keys()` |
| 2. 씨앗 | 3 | 부트스트랩 작업공간 + API 키 + RoutingConfig, 멱등성 |
| 3. 인증 미들웨어 | 4 | 누락/잘못된 베어러 토큰 검증, 401 |
| 4. 앱 팩토리 | 3 | /health, 오류 봉투, /v1/* 게이팅 |
| 5. 공급자 키 CRUD | 5 | 저장 시 암호화됨, 일반 텍스트는 왕복되지 않음 |
| 6. 라우터 캐시 | 13 | env+DB+hosted 배포 어셈블리 우선 순위 |
| 7. 채팅 완료 | 5 | OpenAI 형식, RequestLog, 검증 |
| 8. 분석 | 4 | 최근 / 지출 / 대기 시간 p50/p99 |
| 9. /v1/{모델,키,라우팅} | 8 | 목록/생성/취소 + 전략 업데이트 |
| 10. 스트리밍 | 4 | SSE 형식, `[DONE]` 센티널, 로그 쓰기 저장 |
| 11. 카탈로그 | 7 | 100개 이상의 모델, 기능 플래그, 가격 |
| 12. `모델="자동"` | 21 | 기능 감지, 가장 저렴한 요구 사항 충족(단위 + 통합) |
| 13. 비용 절감 | 9 | 절감액 대 Always-GPT-4 기준 + 호스팅-자동 비교 |
| 14. 프롬프트 캐시 | 15 | 제공자 간 완전 일치 캐시 + 채팅 통합 |
| 15. 벤치마크 | 4 | summary() + render_markdown() 집계 |
| 16. 호스팅 상태 | 7 | `/v1/hosted` config-source + signup-URL 표면 |
| 17. 호스팅 자동 절약 | 3 | 합성 카탈로그의 `_hosted_auto_savings` 극단적인 경우 |
| 18. 연결할 수 없는 모델 | 7 | 호스팅이 켜져 있으면 "접근할 수 없는 모델" 타일이 지워집니다 |
| 19. 다중 프로토콜 인증 | 6 | x-api-key / x-goog-api-key / ?key= 범위 지정, /v1beta 가드, 프로토콜별 401 봉투 |
| 20. Anthropic `/v1/messages` | 53 | 요청/응답/스트림 변환 + 인그레스 통합 |
| 21. Gemini `/v1beta` | 40 | schema-enum 정규화를 포함한 변환 + generateContent/스트림 인그레스 |
| **합계** | **403** | |

슬라이스 행은 각 슬라이스가 출시될 때 추가된 테스트를 보여줍니다. 합계는 현재 전체 테스트 스위트입니다.

## 건축학

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

## 로드맵

- [x] OpenAI 호환 채팅 완료
- [x] 스트리밍(SSE)
- [x] `model="auto"` 가장 저렴한 라우팅 가능
- [x] 업스트림으로 호스팅됨
- [x] 암호화된 미사용 BYOK
- [x] 로컬 분석 대시보드
- [x] CI(GitHub 작업)
- [x] 공급자 간 프롬프트 캐싱
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK 통합
- [x] 공개 벤치마크 + 절감액 청구
- [ ] 임베딩 + 이미지 생성 프록시

장애 조치 데모는 [DEMO.md](./DEMO.md)를 참조하세요.

## 라이센스

MIT. [라이센스](./LICENSE)를 참조하세요.
