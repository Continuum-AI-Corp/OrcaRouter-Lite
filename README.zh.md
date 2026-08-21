# OrcaRouter Lite

**带托管安全网的自托管 LLM 路由器。**
兼容 OpenAI。BYOK。单工作区。流式传输。`model="auto"`。

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

## 语言

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

OrcaRouter Lite 是 [OrcaRouter](https://www.orcarouter.ai) 的开源单工作区版本。在你的笔记本上运行它，把它打包进你的产品里，或者直接使用托管的 `api.orcarouter.ai` 来覆盖那些你不想自己管理密钥的长尾模型。

> **为什么选我们？** LiteLLM 是一个库；OpenRouter 是闭源的托管服务；Ollama 仅限本地。我们是**带托管 fallback 的自托管服务器**——这句话其他人都说不出来。

## 60 秒快速开始

使用 OrcaRouter 的两种方式：

### 路径 A —— 自托管 (BYOK)

在你自己的机器上运行 Lite；自带 provider 密钥。

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# 至少添加一个: OPENAI_API_KEY=sk-...  (或 ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

Base URL：`http://localhost:8000/v1`。使用启动时打印出来的 `sk-orca-*` 密钥。

### 路径 B —— 托管（需要账号）

无需 clone，无需 docker。注册、获取密钥，将任意 OpenAI SDK 指向托管服务。

```bash
# 1. 在 https://www.orcarouter.ai 注册并复制你的 sk-orca-* 密钥
# 2. 使用 https://api.orcarouter.ai/v1 作为 base URL
```

**需要账号。** 托管服务负责路由、计费以及 provider 长尾——按 token 在你的 OrcaRouter 账户上计费。详见 [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction)。

### 然后从任意 OpenAI SDK 调用

下面的示例使用路径 A 的 localhost base URL —— 如果你在路径 B，请替换为 `https://api.orcarouter.ai/v1`。

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # 或 "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
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

打开 `http://localhost:8000/` 进入仪表板 —— providers、路由、分析、密钥（仅路径 A）。

## 为什么？

| | OrcaRouter Lite | LiteLLM 库 | OpenRouter | Ollama |
|---|---|---|---|---|
| 自托管服务器 | ✓ | 作为库 | ✗ | ✓ |
| 兼容 OpenAI | ✓ | ✓ | ✓ | ✓ |
| 多 provider（OpenAI/Anthropic/Google/…）| ✓ | ✓ | ✓ | ✗ |
| 内置仪表板 | ✓ | ✗ | ✓ | ✗ |
| `model="auto"`（最便宜的合适模型）| ✓ | ✗ | ✗ | n/a |
| 流式传输 | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| 托管作为 fallback | ✓ | ✗ | n/a | ✗ |
| 不需要 Postgres / 不需要 Redis | ✓ | n/a | n/a | ✓ |

## `model="auto"` —— 招牌特性

发送 `model="auto"`，OrcaRouter 会在你已配置的 providers 中挑选**最便宜**且能满足请求能力要求（tools、vision、JSON 模式）的模型。无需手写路由规则；无需折腾速率限制；代码里也无需 `if x: ...` 的成本优化。

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → 路由到你的密钥所覆盖的、最便宜的支持 VISION 的模型
```

被选中的模型会通过 `x-orca-resolved-model` 响应头回传给调用方，方便你记录或展示实际使用的模型。

## 托管作为上游（Lite + 托管）

已经在跑 Lite 了？把 `ORCAROUTER_API_KEY` 设为来自 [www.orcarouter.ai](https://www.orcarouter.ai) 的 `sk-orca-*`，托管就成了路由链中的另一个 provider —— 覆盖那些你的本地密钥拿不到的模型：

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

使用场景：
- **先试后买** —— 不需要本地 provider 密钥
- **本地日志** —— 托管负责路由，Lite 把 RequestLog 写入数据库供仪表板使用
- **故障转移** —— 本地 provider 失败时，托管作为安全网兜底

## 流式传输

兼容 OpenAI 的 SSE 格式，使用标准的 `data: ... \n\n` 帧格式以及结尾的 `[DONE]` 标记 —— 任何已经从 OpenAI 流式读取的 SDK 都可以即插即用。

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## 原生协议端点（Anthropic + Gemini）

Lite 用同一条路由流水线对外支持三种入站协议。只使用 Anthropic 或 Gemini 传输格式的客户端可以直接连接 —— 无需 OpenAI SDK：

```bash
# Claude Code 指向 Lite（base URL 不带 /v1 后缀）
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK 指向 Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

请求在边缘层被转换进同一条内部流水线，因此 `model="auto"`、跨 provider 提示缓存（跨协议共享）、路由策略和分析仪表板全都以完全相同的方式工作。指南：[integrations/claude-code.md](./integrations/claude-code.md)、[integrations/gemini-sdk.md](./integrations/gemini-sdk.md)。

## 模型目录

启动时会从 [LiteLLM 社区维护的定价数据库](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) 加载 100+ 个聊天模型 —— 没有需要手动维护的模型清单。每条记录都包含：

- `id`（如 `gpt-4o`、`claude-3-5-sonnet-latest`）
- `provider`（映射到你已配置的密钥）
- 能力标志：`supports_tools`、`supports_vision`、`supports_json_mode`
- 每 token 的输入/输出成本（驱动节省组件 + `model="auto"`）

`GET /v1/models` 返回 OpenAI 格式的目录。

## 部署到其他平台

| 平台 | 一键部署 |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | 连接代码仓库，根目录 = `.` |
| 裸 Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...`（镜像即将发布）|

## 盒子里都有什么

- `POST /v1/chat/completions` —— 代理 + 流式传输 + `model="auto"` + 跨 provider 提示缓存
- `POST /v1/messages` —— **Anthropic Messages API 入口**（Claude Code / Anthropic SDK 可直接连接；`+ /count_tokens`）
- `POST /v1beta/models/{model}:generateContent` —— **Gemini API 入口**（google-genai SDK 可直接连接；`+ :streamGenerateContent`、`GET /v1beta/models`）
- `GET  /v1/models` —— 可发现的模型目录（来自 `litellm.model_cost` 的 100+ 模型）
- `GET/PUT/DELETE /v1/providers/{provider}` —— 设置 / 列出 / 撤销加密的 provider 密钥
- `GET/PUT /v1/routing` —— 切换策略（`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` —— 本地分析数据，没有任何遥测离开容器
- `GET  /v1/hosted` —— 托管 fallback 状态（驱动仪表板上的 "Get $5 free credit" 卡片）
- `GET/POST/DELETE /v1/keys/...` —— 列出 / 轮换 / 撤销 API 密钥
- 单页仪表板挂在 `/`
- 默认 SQLite；可通过 `DATABASE_URL` 切换 Postgres；Redis 可选

### 跨 provider 提示缓存

确定性请求（`temperature=0` 或固定 `seed`）在重复调用时由缓存返回 —— 适用于**所有** provider，不只是 Anthropic。设置了 `REDIS_URL` 时后端是 Redis，否则使用进程内 LRU。命中缓存会即时返回 `x-orca-cache: HIT`，且费用为 $0。

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # 同样的 payload 再来一次
HTTP/1.1 200 OK
x-orca-cache: HIT          ← 来自缓存，无上游调用
```

### 节省组件

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` 报告你的流量在「永远走 GPT-4」时会花多少钱，对比实际花费多少。仪表板会以一张磁贴的形式展示。

### 集成

为 [Claude Code](./integrations/claude-code.md)、[Gemini SDK](./integrations/gemini-sdk.md)、[Continue.dev](./integrations/continue.json)、[Aider](./integrations/aider.md)、[Cursor](./integrations/cursor.md)、[LangChain](./integrations/langchain_orcarouter.py)、[LlamaIndex](./integrations/llamaindex_orcarouter.py)、[Vercel AI SDK](./integrations/vercel_ai.ts) 以及任何使用 OpenAI Chat Completions 协议的工具提供即插即用的配置 —— 外加原生的 Anthropic 和 Gemini 传输格式。详见 [`integrations/`](./integrations/)。

## 刻意不做的事情

这是**单工作区**版本。按设计不包含：
- 多租户、RBAC、SSO
- 计费、钱包、积分、合作伙伴计划
- 管理控制台、审计日志、信任与安全
- 多 pod 部署 / Kubernetes
- 用于告警的邮件 / Slack / webhook

如需这些，请看托管产品或（即将推出的）Teams 版本。

## 测试

测试先行构建。这里发布的每一个行为都先有一个失败的测试。

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

| 切片 | 测试数 | 内容 |
|---|---|---|
| 1. 配置 | 5 | env 加载、默认值、`env_provider_keys()` |
| 2. Seed | 3 | 引导工作区 + API 密钥 + RoutingConfig，幂等 |
| 3. 鉴权中间件 | 4 | bearer-token 校验，缺失/无效返回 401 |
| 4. 应用工厂 | 3 | /health、错误信封、/v1/* 网关 |
| 5. Provider 密钥 CRUD | 5 | 静态加密，明文不会往返 |
| 6. 路由器缓存 | 13 | env+DB+托管 deployment 装配，按优先级 |
| 7. 聊天补全 | 5 | OpenAI 格式、RequestLog、校验 |
| 8. 分析 | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | 列出/创建/撤销 + 策略更新 |
| 10. 流式传输 | 4 | SSE 格式、`[DONE]` 标记、日志回写 |
| 11. 目录 | 7 | 100+ 模型、能力标志、定价 |
| 12. `model="auto"` | 21 | 能力检测、最便宜且满足需求（单元 + 集成）|
| 13. 成本节省 | 9 | 节省 vs 永远 GPT-4 基线 + 托管自动对比 |
| 14. 提示缓存 | 15 | 跨 provider 精确匹配缓存 + 聊天集成 |
| 15. 基准测试 | 4 | summarize() + render_markdown() 聚合 |
| 16. 托管状态 | 7 | `/v1/hosted` 配置来源 + 注册 URL |
| 17. 托管自动节省 | 3 | 合成目录上的 `_hosted_auto_savings` 边界用例 |
| 18. 不可达模型 | 7 | 当托管开启时，「你够不到的模型」磁贴会清空 |
| 19. 多协议鉴权 | 6 | x-api-key / x-goog-api-key / ?key= 作用域、/v1beta 守卫、按协议的 401 信封 |
| 20. Anthropic `/v1/messages` | 53 | 请求/响应/流的转换 + 入口集成 |
| 21. Gemini `/v1beta` | 40 | 转换（含 schema-enum 归一化）+ generateContent/流式入口 |
| **合计** | **403** | |

切片行显示的是各切片交付时新增的测试；合计是当前的完整测试套件。

## 架构

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

## 路线图

- [x] 兼容 OpenAI 的聊天补全
- [x] 流式传输 (SSE)
- [x] `model="auto"` 最便宜且合适的路由
- [x] 托管作为上游
- [x] 静态加密的 BYOK
- [x] 本地分析仪表板
- [x] CI（GitHub Actions）
- [x] 跨 provider 提示缓存
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK 集成
- [x] 公开基准 + 节省说明
- [ ] Embeddings + 图像生成代理

故障转移演示请见 [DEMO.md](./DEMO.md)。

## 许可证

MIT。详见 [LICENSE](./LICENSE)。
