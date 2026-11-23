# OrcaRouter Lite

**Đặt ngân sách cho mọi coding agent.**
Xem và giới hạn chi tiêu của Claude Code, Codex, Gemini CLI, OpenCode và các ứng dụng của riêng bạn trên mọi
nhà cung cấp mô hình, mà prompt không rời khỏi máy của bạn. Một ứng dụng trên thanh menu cho từng
lập trình viên, và một router tự lưu trữ cho cả đội. Giấy phép MIT.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="Bảng điều khiển trên thanh menu của OrcaRouter Lite: chi tiêu hôm nay so với ngân sách hằng ngày, các coding agent đã kết nối và tình trạng provider" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Thiết lập lần đầu: các coding agent được phát hiện, nơi request được gửi đến và ngân sách hằng ngày" width="420">
</p>

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

**Tìm chúng tôi:** [Tất cả API mô hình](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite là phiên bản mã nguồn mở của [OrcaRouter](https://www.orcarouter.ai). Nó chạy trên máy tính hoặc server của bạn, hỗ trợ API của OpenAI, Anthropic và Gemini, và có thể dùng `api.orcarouter.ai` được host làm lưới an toàn khi có sự cố và cho các mô hình mà bạn không có khoá.

## Ứng dụng desktop

Ứng dụng Orca nằm trên thanh menu. Nó chạy router tại `127.0.0.1`, kết nối các coding agent
của bạn vào đó và cho bạn thấy chúng tiêu bao nhiêu.

- **Chi tiêu hôm nay, theo từng agent.** Tổng hôm nay hiển thị cạnh đồng hồ; bảng điều khiển chia nhỏ theo agent, và mỗi thứ Hai một thông báo tóm tắt cả tuần.
- **Ngân sách hằng ngày.** Thông báo khi đạt 80% và 100% số tiền bạn đặt. Mặc định chỉ cảnh báo; đánh dấu một ô là Orca sẽ tạm dừng các coding agent của bạn khi chạm mức đó.
- **Kết nối một cú nhấp.** Orca sửa cấu hình riêng của agent, giữ một bản sao lưu và khôi phục lại khi bạn ngắt kết nối.
- **Không bao giờ sập.** Khi một provider gặp lỗi hoặc giới hạn rate của bạn, request sẽ fallback sang provider khác hoặc sang OrcaRouter hosted, và ứng dụng đếm số request mà nó đã cứu được. Liên kết tài khoản bằng `orca link --key sk-orca-…` hoặc trong màn hình thiết lập.
- **Riêng tư theo mặc định.** Prompt đi thẳng từ agent của bạn tới provider bạn chọn. Không có telemetry.
- **Dùng được với gateway của đội.** `orca login https://ai-gw.example.com --key …` (hoặc "Join my company's gateway" trong phần thiết lập) trỏ các agent của bạn tới gateway do đội platform vận hành; `orca logout` khôi phục lại như cũ.

**Cài đặt.** Bộ cài (`.dmg`, `.deb`, `.AppImage`, `.msi`) được build bởi
[`desktop.yml`](./.github/workflows/desktop.yml) và đính kèm vào mỗi bản phát hành, bắt đầu từ
phiên bản được gắn tag tiếp theo. Cho đến lúc đó, cùng engine và CLI ấy chỉ cách bạn một lệnh:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` phục vụ bảng điều khiển tại `http://127.0.0.1:8765/desktop/panel.html`; để tự build
ứng dụng thanh menu, xem [`desktop/`](./desktop/README.md). Khi bản phát hành đầu tiên ra mắt,
người dùng macOS cũng có thể `brew install --cask continuum-ai-corp/tap/orcarouter-lite`.

Chi tiêu hôm nay trên thanh trạng thái của Claude Code: thêm dòng này vào `~/.claude/settings.json`.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` in ra số liệu của tuần dưới dạng Markdown (hoặc `--format csv`) để dán vào chat hay bảng tính.

| Agent | Cách kết nối |
|---|---|
| Claude Code | Tự động: đặt `ANTHROPIC_BASE_URL` và một khoá riêng trong `~/.claude/settings.json` |
| Codex | Tự động: thêm một provider `orca` (Responses API) vào `~/.codex/config.toml` và chọn nó bằng `model = "auto"` |
| Gemini CLI | Tự động: đặt `GOOGLE_GEMINI_BASE_URL` và một khoá riêng trong `~/.gemini/.env`, cùng chế độ đăng nhập qua gateway của Gemini CLI trong `~/.gemini/settings.json` |
| OpenCode | Tự động: thêm một provider `orca` vào `~/.config/opencode/opencode.json` và chọn `orca/auto`; khoá nằm trong một tệp riêng tư mà OpenCode đọc |
| Command Code | Tự động: thêm một provider `orca` vào `~/.commandcode/providers.json` với khoá lấy từ một tệp riêng tư (Command Code không chấp nhận khoá ghi trực tiếp ở đó) |
| Cline | Một bước dán: chọn API Provider → OpenAI Compatible trong Cline rồi dán URL gốc và khoá mà ứng dụng hiển thị |
| Aider | Tự động: đặt `openai-api-base`, một khoá riêng và `model: openai/auto` trong `~/.aider.conf.yml` |
| Cursor | Một bước dán: ứng dụng hiển thị URL gốc và khoá để dán vào phần cài đặt mô hình của Cursor |

Mỗi agent được kết nối có khoá riêng: đó là cách chi tiêu được chia theo agent, và cũng là lý do
ngắt kết nối sẽ thu hồi quyền truy cập ngay lập tức. Những gì ứng dụng được phép động tới trên máy tính
của bạn được nêu rõ trong [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

<a id="free-and-open-for-good"></a>
## Miễn phí và mở, mãi mãi

- **MIT, vĩnh viễn.** Mọi thứ mà một lập trình viên hay một đội cần đều nằm trong repository này theo giấy phép MIT: định tuyến, `model="auto"`, ngân sách, dashboard, ứng dụng desktop. Chúng tôi sẽ không chuyển tính năng nào từ Lite sang gói trả phí.
- **Trả phí là dành cho tổ chức.** Việc quản trị nhiều đội (SSO/SCIM, phân quyền theo vai trò, ngân sách và chính sách trên toàn tổ chức, lưu giữ audit log, cảnh báo qua Slack và email) nằm ở [OrcaRouter hosted](https://www.orcarouter.ai).
- **Có thể kiểm chứng.** Các bản phát hành được ký và đi kèm provenance cùng SBOM. Xem [SECURITY.md](./SECURITY.md).

## So sánh

| | Phù hợp nhất cho | Cách chạy |
|---|---|---|
| **OrcaRouter Lite** | Từ một lập trình viên đến cả đội muốn có chi tiêu theo agent, ngân sách và failover mà không cần thêm hạ tầng | Ứng dụng desktop, `uvx`/`pip` hoặc Docker; mặc định SQLite |
| LiteLLM proxy | Các đội muốn nhiều tuỳ chọn cấu hình và một Python SDK | Server tự lưu trữ; Postgres để theo dõi chi tiêu |
| OpenRouter | Một khoá API cho nhiều mô hình, do họ tính phí | Chỉ hosted; prompt đi qua dịch vụ của họ |
| Hỗ trợ gateway sẵn có của Claude Code | Công ty chỉ dùng Claude | Trỏ Claude Code tới một gateway do bạn tự chạy; chỉ mô hình Claude |

## Chạy như một server (60 giây)

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

## `model="auto"`

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

| Nền tảng | Cách làm |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (phát hành từ bản gắn tag tiếp theo; kiểm chứng bằng các lệnh trong [SECURITY.md](./SECURITY.md)) |
| Render | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Continuum-AI-Corp/OrcaRouter-Lite): dùng [`render.yaml`](./render.yaml), tự tạo các secret, lưu cơ sở dữ liệu trên một ổ đĩa |
| Fly.io | `fly launch --no-deploy`, sau đó làm các bước tạo volume và `fly secrets set` ở đầu [`fly.toml`](./fly.toml), rồi `fly deploy` |
| Railway | `railway init`, `railway volume add --mount-path /data`, `railway variables --set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) --set API_KEY_PEPPER=$(openssl rand -hex 32) --set DATABASE_URL=sqlite+aiosqlite:////data/orca.db`, rồi `railway up` (build theo [`railway.json`](./railway.json)) |

## Có gì trong hộp

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache prompt liên-provider
- `POST /v1/messages` — **ngõ vào Anthropic Messages API** (Claude Code / các Anthropic SDK kết nối trực tiếp; `+ /count_tokens`)
- `POST /v1/responses` — **ngõ vào OpenAI Responses API** (Codex và các client dùng Responses SDK; streaming, function tool và custom tool)
- `POST /v1beta/models/{model}:generateContent` — **ngõ vào Gemini API** (google-genai SDK kết nối trực tiếp; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — danh mục mô hình có thể khám phá (100+ mô hình từ `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — đặt / liệt kê / thu hồi khoá provider được mã hoá
- `GET/PUT /v1/routing` — đổi chiến lược (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics local, không có telemetry rời khỏi hộp
- `GET  /v1/hosted` — trạng thái hosted-fallback (chạy thẻ "Get $5 free credit" trên dashboard)
- `GET/POST/DELETE /v1/keys/...` — liệt kê / xoay vòng / thu hồi khoá API
- `/v1/app/*` — agent, tổng hợp chi tiêu và ngân sách cho ứng dụng desktop (chỉ khi khởi động bằng `orca up`; xem [SECURITY.md](./SECURITY.md))
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

Đó là các tính năng dành cho tổ chức và nằm ở [OrcaRouter hosted](https://www.orcarouter.ai); xem [Miễn phí và mở, mãi mãi](#free-and-open-for-good).

## Kiểm thử

Xây dựng theo test-first: mỗi hành vi giao ở đây đều có một test fail trước.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

## Lộ trình

- [x] Chat completions tương thích OpenAI, streaming, `model="auto"`
- [x] Endpoint native cho Anthropic và Gemini
- [x] Fallback hosted-làm-upstream, BYOK mã hoá, dashboard local
- [x] Cache prompt liên-provider
- [x] Ứng dụng desktop: chi tiêu trên thanh menu, cảnh báo ngân sách hằng ngày, kết nối agent một cú nhấp
- [x] Bản phát hành được ký kèm provenance và SBOM; dependency được khoá bằng hash
- [x] Ngân sách hằng ngày có thể cảnh báo, hoặc tạm dừng các coding agent khi chạm giới hạn
- [x] `orca login` / "Join my company's gateway": dùng gateway của đội từ ứng dụng
- [x] `/v1/responses`, để Codex kết nối được; cả Gemini CLI, OpenCode, Command Code và Cline
- [x] Khoá mã hoá nằm trong keychain của hệ điều hành; kiểm tra cập nhật mỗi ngày một lần
- [ ] Ngân sách theo từng lập trình viên được áp dụng trên gateway dùng chung của đội
- [ ] Embeddings, provider Ollama/vLLM, chuỗi fallback tuỳ chỉnh

Xem [DEMO.md](./DEMO.md) để xem demo failover.

<a id="license"></a>
## Giấy phép

MIT. Xem [LICENSE](./LICENSE).
