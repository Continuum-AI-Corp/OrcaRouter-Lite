# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | [日本語](./README.ja.md) | **한국어** | [Deutsch](./README.de.md) | [Italiano](./README.it.md) | [Français](./README.fr.md) | [Español](./README.es.md) | [العربية](./README.ar.md)

**관리형 안전망을 갖춘 자체 호스팅 LLM 라우터.**
OpenAI 호환. BYOK. 단일 워크스페이스. 스트리밍. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#테스트)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#모델-카탈로그)
[![license](https://img.shields.io/badge/license-MIT-blue)](#라이선스)

OrcaRouter Lite는 [OrcaRouter](https://www.orcarouter.ai)의 오픈 소스 단일 워크스페이스 에디션입니다. 노트북에서 실행하거나, 제품에 탑재하거나, 직접 키를 관리하고 싶지 않은 롱테일 모델을 위해 호스팅 `api.orcarouter.ai`를 직접 사용할 수 있습니다.

> **왜 우리인가요?** LiteLLM은 라이브러리이고, OpenRouter는 폐쇄형 호스팅, Ollama는 로컬 전용입니다. 우리는 **관리형 폴백을 갖춘 자체 호스팅 서버**입니다 — 그들 중 누구도 할 수 없는 한 문장입니다.

## 60초 빠른 시작

OrcaRouter를 사용하는 두 가지 방법:

### 경로 A — 자체 호스팅(BYOK)

자신의 머신에서 Lite를 실행하고 자신의 공급자 키를 가져옵니다.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# 최소 하나 추가: OPENAI_API_KEY=sk-...  (또는 ORCAROUTER_API_KEY=...)

docker compose up
# 로그: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

기본 URL: `http://localhost:8000/v1`. 시작 시 출력된 `sk-orca-*` 키를 사용하세요.

### 경로 B — 호스팅(계정 필요)

복제 없음, docker 없음. 등록하고, 키를 받고, 어떤 OpenAI SDK든 호스팅을 가리키면 됩니다.

```bash
# 1. https://www.orcarouter.ai에 등록하고 sk-orca-* 키를 복사
# 2. https://api.orcarouter.ai/v1을 기본 URL로 사용
```

**계정이 필요합니다.** 호스팅은 라우팅, 청구, 롱테일 공급자를 처리합니다 — OrcaRouter 계정에서 토큰당 청구됩니다. [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction)을 참조하세요.

### 그런 다음 모든 OpenAI SDK에서 호출

아래 예제는 경로 A의 localhost 기본 URL을 사용합니다 — 경로 B를 사용하는 경우 `https://api.orcarouter.ai/v1`로 바꾸세요.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # 또는 "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "안녕하세요!"}],
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
  messages: [{ role: "user", content: "안녕하세요!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"안녕하세요!"}]}'
```
</details>

대시보드를 보려면 `http://localhost:8000/`을 여세요 — 공급자, 라우팅, 분석, 키(경로 A 전용).

## 왜?

| | Lite | LiteLLM 라이브러리 | OpenRouter | Ollama |
|---|---|---|---|---|
| 자체 호스팅 서버 | ✓ | 라이브러리로 | ✗ | ✓ |
| OpenAI 호환 | ✓ | ✓ | ✓ | ✓ |
| 다중 공급자(OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| 내장 대시보드 | ✓ | ✗ | ✓ | ✗ |
| `model="auto"`(요구 사항을 충족하는 가장 저렴한) | ✓ | ✗ | ✗ | 해당 없음 |
| 스트리밍 | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | 해당 없음 |
| 폴백으로서의 호스팅 | ✓ | ✗ | 해당 없음 | ✗ |
| Postgres / Redis 불필요 | ✓ | 해당 없음 | 해당 없음 | ✓ |

## `model="auto"` — 핵심 기능

`model="auto"`를 보내면 OrcaRouter는 구성된 공급자에서 요청의 기능 요구 사항(도구, 비전, JSON 모드)을 충족하는 **가장 저렴한** 모델을 선택합니다. 수동 라우팅 규칙 없음, 속도 제한 묘기 없음, 코드의 `if x: ...` 비용 최적화 없음.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "이 이미지에 무엇이 있나요?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → 키가 커버하는 가장 저렴한 비전 지원 모델로 라우팅
```

해결된 모델은 `x-orca-resolved-model` 응답 헤더를 통해 호출자에게 노출되므로 실제 사용된 모델을 기록/표시할 수 있습니다.

## 업스트림으로서의 호스팅(Lite + 호스팅)

이미 Lite를 실행 중인가요? `ORCAROUTER_API_KEY`를 [www.orcarouter.ai](https://www.orcarouter.ai)의 `sk-orca-*`로 설정하면 호스팅이 라우팅 체인의 또 다른 공급자가 됩니다 — 로컬 키가 커버하지 않는 모델을 커버합니다:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

사용 사례:
- **시도 후 구매** — 로컬 공급자 키 불필요
- **로컬 로깅** — 호스팅이 라우팅을 처리하고 Lite가 대시보드용 RequestLog 행을 저장
- **장애 조치** — 로컬 공급자 실패 시 호스팅이 안전망

## 스트리밍

OpenAI 호환 SSE 형식, 표준 `data: ... \n\n` 프레임과 종료 `[DONE]` 센티넬 — OpenAI에서 이미 스트리밍하는 모든 SDK에 드롭인.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "이야기 하나 해줘"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## 모델 카탈로그

100개 이상의 채팅 모델이 시작 시 [LiteLLM의 커뮤니티 관리 가격 데이터베이스](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)에서 로드됩니다 — 수동으로 유지할 모델 목록 없음. 각 항목은 다음을 노출합니다:

- `id`(예: `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider`(구성된 키에 매핑됨)
- 기능 플래그: `supports_tools`, `supports_vision`, `supports_json_mode`
- 토큰당 입력/출력 비용(절감 위젯 + `model="auto"` 구동)

`GET /v1/models`는 OpenAI 형식 카탈로그를 반환합니다.

## 다른 곳에 배포

| 플랫폼 | 원클릭 |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | 저장소 연결, 루트 디렉토리 = `.` |
| 베어 Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...`(이미지 곧 제공) |

## 무엇이 들어 있나요

- `POST /v1/chat/completions` — 프록시 + 스트리밍 + `model="auto"` + 크로스 공급자 프롬프트 캐시
- `GET  /v1/models` — 검색 가능한 모델 카탈로그(`litellm.model_cost`의 100개 이상 모델)
- `GET/PUT/DELETE /v1/providers/{provider}` — 암호화된 공급자 키 설정 / 목록 / 취소
- `GET/PUT /v1/routing` — 전략 변경(`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — 로컬 분석, 텔레메트리는 박스를 떠나지 않음
- `GET  /v1/hosted` — 호스팅 폴백 상태(대시보드의 "$5 무료 크레딧 받기" 카드 구동)
- `GET/POST/DELETE /v1/keys/...` — API 키 목록 / 회전 / 취소
- `/`의 단일 페이지 대시보드
- 기본적으로 SQLite, `DATABASE_URL`을 통한 Postgres 옵트인, Redis 옵션

### 크로스 공급자 프롬프트 캐시

결정론적 요청(`temperature=0` 또는 고정된 `seed`)은 반복 시 캐시에서 제공됩니다 — Anthropic뿐만 아니라 **모든** 공급자에서 작동합니다. `REDIS_URL`이 설정되면 백엔드는 Redis이고, 그렇지 않으면 인-프로세스 LRU입니다. 캐시 히트는 `x-orca-cache: HIT`와 함께 즉시 반환되며 비용은 $0입니다.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # 동일한 페이로드를 다시
HTTP/1.1 200 OK
x-orca-cache: HIT          ← 캐시에서 제공, 업스트림 호출 없음
```

### 절감 위젯

`GET /v1/analytics/savings?baseline=gpt-4o&days=7`은 트래픽이 항상 GPT-4였을 때의 비용 대비 실제 비용을 보고합니다. 대시보드는 이를 타일로 표시합니다.

### 통합

[Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) 및 OpenAI Chat Completions 프로토콜을 사용하는 모든 도구를 위한 드롭인 구성. [`integrations/`](./integrations/)를 참조하세요.

## 의도적으로 포함하지 않은 것

이것은 **단일 워크스페이스** 에디션입니다. 설계상 다음은 없습니다:
- 멀티 테넌시, RBAC, SSO
- 청구, 지갑, 포인트, 파트너 프로그램
- 관리 콘솔, 감사 로그, 신뢰 및 안전
- 멀티 포드 배포 / Kubernetes
- 알림용 이메일 / Slack / Webhook

이러한 기능을 원한다면 호스팅 제품 또는 (출시 예정인) Teams 에디션을 참조하세요.

## 테스트

테스트 우선으로 빌드되었습니다. 여기에 출시된 모든 동작에는 먼저 실패하는 테스트가 있었습니다.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| 슬라이스 | 테스트 | 내용 |
|---|---|---|
| 1. 구성 | 5 | env 로딩, 기본값, `env_provider_keys()` |
| 2. 시드 | 3 | 워크스페이스 + API 키 + RoutingConfig 부트스트랩, 멱등 |
| 3. 인증 미들웨어 | 4 | bearer-token 검증, 누락/유효하지 않을 때 401 |
| 4. 앱 팩토리 | 3 | /health, 오류 봉투, /v1/* 게이팅 |
| 5. 공급자 키 CRUD | 5 | 정적 암호화, 평문이 왕복되지 않음 |
| 6. 라우터 캐시 | 13 | 우선순위가 있는 env+DB+호스트 배포 어셈블리 |
| 7. 채팅 완료 | 5 | OpenAI 형식, RequestLog, 검증 |
| 8. 분석 | 4 | 최근 / 지출 / 레이턴시 p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | 목록/생성/취소 + 전략 업데이트 |
| 10. 스트리밍 | 4 | SSE 형식, `[DONE]` 센티넬, 로그 쓰기 백 |
| 11. 카탈로그 | 7 | 100개 이상 모델, 기능 플래그, 가격 |
| 12. `model="auto"` | 21 | 기능 감지, 요구 사항을 충족하는 가장 저렴한(단위 + 통합) |
| 13. 비용 절감 | 9 | 항상 GPT-4 기준 대비 절감 + 호스트 자동 비교 |
| 14. 프롬프트 캐시 | 15 | 크로스 공급자 정확 일치 캐시 + 채팅 통합 |
| 15. 벤치마크 | 4 | summarize() + render_markdown() 집계 |
| 16. 호스팅 상태 | 7 | `/v1/hosted` 구성 소스 + 가입 URL 표면 |
| 17. 호스팅 자동 절감 | 3 | 합성 카탈로그의 `_hosted_auto_savings` 엣지 케이스 |
| 18. 도달할 수 없는 모델 | 7 | 호스팅이 켜져 있을 때 "도달할 수 없는 모델" 타일이 지워짐 |
| **총계** | **127** | |

## 아키텍처

```
app/
├── main.py             FastAPI 팩토리 + 라이프스팬 + SPA 마운트
├── config.py           설정(~15 필드)
├── deps.py             DI 헬퍼
├── seed.py             첫 실행 부트스트랩
├── auto_routing.py     model="auto" 기능 + 비용 점수
├── router_cache.py     단일 워크스페이스 라우터
├── prompt_cache.py     크로스 공급자 정확 일치 캐시(Redis 또는 인메모리 LRU)
├── schemas.py          OpenAI 호환 요청 스키마
├── middleware/auth.py  sk-orca-* 검증
└── routes/
    ├── chat.py         /v1/chat/completions  (블로킹 + 스트리밍)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      전략 구성
    ├── analytics.py    최근 / 지출 / 레이턴시 / 절감 / 도달할 수 없음
    ├── keys.py         API 키 목록 / 회전 / 취소
    ├── hosted.py       /v1/hosted — 대시보드용 호스팅 폴백 상태
    └── health.py

packages/
├── litellm_adapter/    라우터 래퍼 + 100개 이상 모델 카탈로그
├── auth/               해싱 + AES-256-GCM
└── db/                 모델 + 엔진 + 세션
```

## 로드맵

- [x] OpenAI 호환 채팅 완료
- [x] 스트리밍(SSE)
- [x] `model="auto"` 요구 사항을 충족하는 가장 저렴한 라우팅
- [x] 업스트림으로서의 호스팅
- [x] 정적 암호화된 BYOK
- [x] 로컬 분석 대시보드
- [x] CI(GitHub Actions)
- [x] 크로스 공급자 프롬프트 캐싱
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK 통합
- [x] 공개 벤치마크 + 절감 주장
- [ ] 임베딩 + 이미지 생성 프록시

장애 조치 데모는 [DEMO.md](./DEMO.md)를 참조하세요.

## 라이선스

MIT. [LICENSE](./LICENSE)를 참조하세요.
