# OrcaRouter Lite

**Bộ định tuyến LLM tự lưu trữ với lưới an toàn được quản lý.**
Tương thích OpenAI. BYOK. Workspace đơn. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

## Ngôn ngữ

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

OrcaRouter Lite là phiên bản mã nguồn mở single-workspace của [OrcaRouter](https://www.orcarouter.ai). Chạy trên laptop, đóng gói vào sản phẩm của bạn, hoặc dùng trực tiếp `api.orcarouter.ai` được host cho phần đuôi dài các mô hình mà bạn không muốn tự quản lý khoá.

> **Tại sao là chúng tôi?** LiteLLM là một thư viện; OpenRouter là dịch vụ host mã nguồn đóng; Ollama chỉ chạy local. Chúng tôi là **server tự lưu trữ với fallback được quản lý** — một câu mà không ai trong số họ nói được.

## Khởi động nhanh trong 60 giây

Hai cách dùng OrcaRouter:

### Đường A — Tự lưu trữ (BYOK)

Chạy Lite trên máy của bạn; mang theo khoá provider của riêng bạn.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# thêm ít nhất một: OPENAI_API_KEY=sk-...  (hoặc ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL gốc: `http://localhost:8000/v1`. Dùng khoá `sk-orca-*` được in ra khi khởi động.

### Đường B — Hosted (cần tài khoản)

Không clone, không docker. Đăng ký, lấy khoá, trỏ bất kỳ OpenAI SDK nào tới hosted.

```bash
# 1. Đăng ký tại https://www.orcarouter.ai và sao chép khoá sk-orca-* của bạn
# 2. Dùng https://api.orcarouter.ai/v1 làm URL gốc
```

**Cần tài khoản.** Hosted lo định tuyến, tính phí và phần đuôi dài các provider — tính theo token trên tài khoản OrcaRouter của bạn. Xem [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Sau đó gọi từ bất kỳ OpenAI SDK nào

Các ví dụ bên dưới dùng URL gốc localhost của Đường A — đổi sang `https://api.orcarouter.ai/v1` nếu bạn đang ở Đường B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # hoặc "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

Mở `http://localhost:8000/` để vào dashboard — providers, định tuyến, analytics, khoá (chỉ Đường A).

## Tại sao?

| | OrcaRouter Lite | Thư viện LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Server tự lưu trữ | ✓ | dạng thư viện | ✗ | ✓ |
| Tương thích OpenAI | ✓ | ✓ | ✓ | ✓ |
| Đa provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Dashboard tích hợp | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (rẻ nhất đáp ứng) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hosted làm fallback | ✓ | ✗ | n/a | ✗ |
| Không cần Postgres / không cần Redis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — tính năng chủ lực

Gửi `model="auto"` và OrcaRouter sẽ chọn mô hình **rẻ nhất** trong các provider đã cấu hình mà đáp ứng yêu cầu năng lực của request (tools, vision, chế độ JSON). Không cần luật định tuyến thủ công; không cần xoay sở rate-limit; không cần tối ưu chi phí kiểu `if x: ...` trong code của bạn.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → định tuyến đến mô hình hỗ trợ VISION rẻ nhất mà khoá của bạn bao phủ
```

Mô hình được chọn được trả về cho bên gọi qua header phản hồi `x-orca-resolved-model`, để bạn có thể log/hiển thị mô hình thực sự đã dùng.

## Hosted làm upstream (Lite + hosted)

Đã chạy Lite rồi? Đặt `ORCAROUTER_API_KEY` bằng `sk-orca-*` của bạn từ [www.orcarouter.ai](https://www.orcarouter.ai), và hosted trở thành thêm một provider trong chuỗi định tuyến — bao phủ các mô hình mà khoá local của bạn không có:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Trường hợp dùng:
- **Dùng-thử-trước-khi-mua** — không cần khoá provider local
- **Logging local** — hosted lo định tuyến, Lite lưu các dòng RequestLog cho dashboard
- **Failover** — provider local hỏng, hosted là lưới an toàn

## Streaming

Định dạng SSE tương thích OpenAI với framing chuẩn `data: ... \n\n` và sentinel kết thúc `[DONE]` — drop-in cho bất kỳ SDK nào đã stream từ OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Các endpoint giao thức native (Anthropic + Gemini)

Lite nói ba giao thức đầu vào trên cùng một pipeline định tuyến. Các client chỉ nói định dạng wire của Anthropic hoặc Gemini có thể kết nối trực tiếp — không cần OpenAI SDK:

```bash
# Claude Code trỏ vào Lite (URL gốc không có hậu tố /v1)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK trỏ vào Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

Request được chuyển đổi ngay ở biên vào cùng một pipeline nội bộ, nên `model="auto"`, cache prompt liên-provider (dùng chung giữa các giao thức), các chiến lược định tuyến và dashboard analytics đều hoạt động y hệt nhau. Hướng dẫn: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Danh mục mô hình

Hơn 100 mô hình chat được nạp khi khởi động từ [cơ sở dữ liệu giá do cộng đồng duy trì của LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — không có danh sách mô hình nào phải bảo trì thủ công. Mỗi mục cung cấp:

- `id` (ví dụ: `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (ánh xạ tới các khoá đã cấu hình của bạn)
- Cờ năng lực: `supports_tools`, `supports_vision`, `supports_json_mode`
- Chi phí mỗi token đầu vào/đầu ra (chạy widget tiết kiệm + `model="auto"`)

`GET /v1/models` trả về danh mục theo định dạng OpenAI.

## Triển khai ở nơi khác

| Nền tảng | One-click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Kết nối repo, root dir = `.` |
| Docker thuần | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (image sắp ra mắt) |

## Có gì trong hộp

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache prompt liên-provider
- `POST /v1/messages` — **ngõ vào Anthropic Messages API** (Claude Code / các Anthropic SDK kết nối trực tiếp; `+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **ngõ vào Gemini API** (google-genai SDK kết nối trực tiếp; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — danh mục mô hình có thể khám phá (100+ mô hình từ `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — đặt / liệt kê / thu hồi khoá provider được mã hoá
- `GET/PUT /v1/routing` — đổi chiến lược (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics local, không có telemetry rời khỏi hộp
- `GET  /v1/hosted` — trạng thái hosted-fallback (chạy thẻ "Get $5 free credit" trên dashboard)
- `GET/POST/DELETE /v1/keys/...` — liệt kê / xoay vòng / thu hồi khoá API
- Dashboard single-page tại `/`
- SQLite mặc định; Postgres tuỳ chọn qua `DATABASE_URL`; Redis tuỳ chọn

### Cache prompt liên-provider

Các request có tính xác định (`temperature=0` hoặc `seed` cố định) được phục vụ từ cache khi lặp lại — hoạt động trên **mọi** provider, không chỉ Anthropic. Backend là Redis nếu `REDIS_URL` được đặt, ngược lại là LRU in-process. Cache hit trả về tức thì với `x-orca-cache: HIT` và chi phí $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # cùng payload lần nữa
HTTP/1.1 200 OK
x-orca-cache: HIT          ← phục vụ từ cache, không gọi upstream
```

### Widget tiết kiệm

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` báo cáo lưu lượng của bạn sẽ tốn bao nhiêu nếu luôn dùng GPT-4 so với chi phí thực tế. Dashboard hiển thị dưới dạng tile.

### Tích hợp

Cấu hình drop-in cho [Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) và bất kỳ công cụ nào nói giao thức OpenAI Chat Completions — cộng thêm các định dạng wire native của Anthropic và Gemini. Xem [`integrations/`](./integrations/).

## Những gì cố ý không có

Đây là phiên bản **single-workspace**. Theo thiết kế, không có:
- multi-tenancy, RBAC, SSO
- billing, ví, điểm thưởng, chương trình đối tác
- console quản trị, audit log, trust & safety
- triển khai multi-pod / Kubernetes
- email / Slack / webhook cho cảnh báo

Cho những thứ đó, xem sản phẩm hosted hoặc bản Teams (sắp ra).

## Kiểm thử

Xây dựng theo test-first. Mỗi hành vi giao ở đây đều có một test fail trước.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| Slice | Tests | Cái gì |
|---|---|---|
| 1. Config | 5 | nạp env, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + khoá API + RoutingConfig, idempotent |
| 3. Auth middleware | 4 | xác thực bearer-token, 401 khi thiếu/không hợp lệ |
| 4. App factory | 3 | /health, error envelope, gating /v1/* |
| 5. CRUD khoá provider | 5 | mã hoá khi nghỉ, plaintext không bao giờ round-trip |
| 6. Cache router | 13 | lắp ghép deployment env+DB+hosted với thứ tự ưu tiên |
| 7. Chat completion | 5 | định dạng OpenAI, RequestLog, xác thực |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + cập nhật chiến lược |
| 10. Streaming | 4 | định dạng SSE, sentinel `[DONE]`, log writeback |
| 11. Catalog | 7 | 100+ mô hình, cờ năng lực, pricing |
| 12. `model="auto"` | 21 | phát hiện năng lực, rẻ-nhất-đáp-ứng (unit + tích hợp) |
| 13. Tiết kiệm chi phí | 9 | tiết kiệm vs baseline luôn-GPT-4 + so sánh hosted-auto |
| 14. Cache prompt | 15 | cache khớp chính xác liên-provider + tích hợp chat |
| 15. Benchmark | 4 | tổng hợp summarize() + render_markdown() |
| 16. Trạng thái hosted | 7 | `/v1/hosted` config-source + bề mặt URL signup |
| 17. Tiết kiệm hosted-auto | 3 | trường hợp biên `_hosted_auto_savings` trên catalog tổng hợp |
| 18. Mô hình không tới được | 7 | tile "mô hình bạn không tới được" rỗng khi hosted bật |
| 19. Auth đa giao thức | 6 | scoping x-api-key / x-goog-api-key / ?key=, guard /v1beta, envelope 401 theo từng giao thức |
| 20. Anthropic `/v1/messages` | 53 | chuyển đổi request/response/stream + tích hợp ngõ vào |
| 21. Gemini `/v1beta` | 40 | chuyển đổi gồm cả chuẩn hoá schema-enum + ngõ vào generateContent/stream |
| **Tổng** | **403** | |

Các hàng slice hiển thị số test được thêm khi từng slice ra mắt; tổng là bộ test đầy đủ hiện tại.

## Kiến trúc

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

## Lộ trình

- [x] Chat completions tương thích OpenAI
- [x] Streaming (SSE)
- [x] Định tuyến `model="auto"` rẻ-nhất-đáp-ứng
- [x] Hosted-làm-upstream
- [x] BYOK mã hoá khi nghỉ
- [x] Dashboard analytics local
- [x] CI (GitHub Actions)
- [x] Cache prompt liên-provider
- [x] Tích hợp Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark công khai + tuyên bố tiết kiệm
- [ ] Proxy embeddings + tạo ảnh

Xem [DEMO.md](./DEMO.md) để xem demo failover.

## Giấy phép

MIT. Xem [LICENSE](./LICENSE).
