# OrcaRouter Lite

**具有托管安全网的自托管 LLM 路由器。**
兼容 OpenAI。自带。单一工作区。流媒体。 `型号=“汽车”`。

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![测试](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![模型](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![许可证](https://img.shields.io/badge/license-MIT-blue)](#license)

## 语言

- [英文](./README.md)
- [日本语](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [德语](./README.de.md)
- [法语](./README.fr.md)
- [西班牙语](./README.es.md)
- [意大利语](./README.it.md)
- [Русский](./README.ru.md)
- [葡萄牙语](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite 是 [OrcaRouter](https://www.orcarouter.ai) 的开源单工作区版本。在您的笔记本电脑上运行它，将其运送到您的产品中，或者直接使用托管的“api.orcarouter.ai”来处理您不想管理密钥的长尾模型。

> **为什么选择我们？** LiteLLM 是一个图书馆； OpenRouter 是闭源托管的；奥拉马仅限本地。我们是**具有托管回退功能的自托管服务器**——这句话没有人可以说。

## 60 秒快速入门

OrcaRouter的两种使用方法：

### 路径 A — 自托管 (BYOK)

在您自己的机器上运行 Lite；带上您自己的提供商密钥。

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

基本 URL：“http://localhost:8000/v1”。使用启动时打印的“sk-orca-*”密钥。

### 路径 B — 托管（需要帐户）

没有克隆，没有码头工人。注册、获取密钥、将任何 OpenAI SDK 指向托管的。

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**需要帐户。** Hosted 处理路由、计费和提供商的长尾 - 在您的 OrcaRouter 帐户上按令牌计费。请参阅[docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction)。

### 然后从任何 OpenAI SDK 调用它

下面的示例使用路径 A 的本地主机基本 URL — 如果您位于路径 B，则交换为“https://api.orcarouter.ai/v1”。

<详情>
<摘要><b>Python</b></摘要>

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

<详情>
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

<详情>
<摘要><b>卷曲</b></摘要>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

打开仪表板的“http://localhost:8000/” — 提供程序、路由、分析、密钥（仅限路径 A）。

＃＃ 为什么？

| |精简版 | LiteLLM 库 |开放路由器|奥拉玛 |
|---|---|---|---|---|
|自托管服务器| ✓ |作为图书馆| ✗ | ✓ |
|兼容 OpenAI | ✓ | ✓ | ✓ | ✓ |
|多提供商（OpenAI/Anthropic/Google/...）| ✓ | ✓ | ✓ | ✗ |
|内置仪表板| ✓ | ✗ | ✓ | ✗ |
| `model="auto"`（最便宜的功能）| ✓ | ✗ | ✗ |不适用 |
|流媒体 | ✓ | ✓ | ✓ | ✓ |
|自带 | ✓ | ✓ | ✗ |不适用 |
|托管作为后备| ✓ | ✗ |不适用 | ✗ |
|无需 Postgres/无需 Redis | ✓ |不适用 |不适用 | ✓ |

## `model="auto"` — 标题功能

发送 `model="auto"` ，OrcaRouter 会在您配置的提供程序中选择最便宜的模型，以满足请求的功能要求（工具、愿景、JSON 模式）。无需手动路由规则；没有速度限制的体操；代码中没有“if x: ...”成本优化。

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

解析后的模型通过“x-orca-resolved-model”响应标头暴露给调用者，以便您可以记录/显示实际使用的内容。

## 作为上游托管（Lite + 托管）

已经运行 Lite 了？将“ORCAROUTER_API_KEY”设置为来自 [www.orcarouter.ai](https://www.orcarouter.ai) 的“sk-orca-*”，托管成为路由链中的又一个提供商 - 涵盖本地密钥不具备的模型：

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

使用案例：
- **先试后买** — 无需本地提供商密钥
- **本地日志记录** — 托管处理路由，Lite 存储仪表板的 RequestLog 行
- **故障转移** — 本地提供商失败，托管是安全网

## 流媒体

与 OpenAI 兼容的 SSE 格式，具有标准的“data: ... \n\n” 框架和终端“[DONE]”哨兵 — 适用于已从 OpenAI 流式传输的任何 SDK。

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## 型号目录

启动时从 [LiteLLM 社区维护的定价数据库](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) 加载 100 多个聊天模型 - 无需手动维护模型列表。每个条目都公开：

- `id`（例如`gpt-4o`、`claude-3-5-sonnet-latest`）
- `provider`（映射到您配置的键）
- 功能标志：`supports_tools`、`supports_vision`、`supports_json_mode`
- 每个代币的输入/输出成本（驱动储蓄小部件 + `model="auto"`）

`GET /v1/models` returns the OpenAI-format catalogue.

## 部署到其他地方

|平台|一键|
|---|---|
|铁路| [![在铁路上部署](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
|渲染 |连接存储库，根目录 = `.` |
|裸 Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...`（图片即将推出）|

## 盒子里有什么

- `POST /v1/chat/completions` — 代理 + 流 + `model="auto"` + 跨提供商提示缓存
- `GET /v1/models` — 可发现的模型目录（来自 `litellm.model_cost` 的 100 多个模型）
- `GET/PUT/DELETE /v1/providers/{provider}` — 设置/列出/撤销加密的提供者密钥
- `GET/PUT /v1/routing` — 更改策略（`平衡`/`最便宜`/`最快`/`质量`）
- `GET /v1/analytics/{recent,spend,latency, savings,unreachable}` — 本地分析，没有遥测功能
- `GET /v1/hosted` — 托管回退状态（驱动仪表板的“获取 5 美元免费信用卡”卡）
- `GET/POST/DELETE /v1/keys/...` — 列出/旋转/撤销 API 密钥
- 单页仪表板位于`/`
- 默认情况下使用 SQLite； Postgres 通过“DATABASE_URL”选择加入； Redis 可选

### 跨提供商提示缓存

确定性请求（“温度 = 0”或固定的“种子”）由缓存重复提供 - 适用于**每个**提供者，而不仅仅是 Anthropic。当设置“REDIS_URL”时，后端是 Redis，否则是进程内 LRU。缓存命中会立即返回“x-orca-cache: HIT”，成本为 0 美元。

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### 储蓄小部件

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` reports what your traffic would have cost on always-GPT-4 vs what it actually cost. The dashboard shows it as a tile.

### 集成

[Continue.dev](./integrations/continue.json)、[Aider](./integrations/aider.md)、[Cursor](./integrations/cursor.md)、[LangChain](./integrations/langchain_orcarouter.py)、[LlamaIndex](./integrations/llamaindex_orcarouter.py)、[Vercel]的直接配置AI SDK](./integrations/vercel_ai.ts)，以及任何使用 OpenAI 聊天完成协议的工具。请参阅[`integrations/`](./integrations/)。

## 故意不做的事情

这是**单工作区**版本。根据设计，不：
- 多租户、RBAC、SSO
- 计费、钱包、积分、合作伙伴计划
- 管理控制台、审核日志、信任和安全
- 多pod部署/Kubernetes
- 用于警报的电子邮件/Slack/Webhooks

对于这些，请参阅托管产品或（即将推出的）Teams 版本。

## 测试

构建测试优先。这里发布的每个行为都首先经过失败的测试。

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

|切片 |测试 |什么 |
|---|---|---|
| 1. 配置 | 5 | env 加载，默认值，`env_provider_keys()` |
| 2. 种子 | 3 |引导工作区 + API 密钥 + RoutingConfig，幂等 |
| 3. Auth中间件| 4 |不记名令牌验证，丢失/无效时返回 401 |
| 4.应用工厂| 3 | /health，错误信封，/v1/* 门控 |
| 5. 提供者密钥 CRUD | 5 |静态加密，明文永不往返 |
| 6.路由器缓存| 13 | env+DB+托管部署程序集优先 |
| 7.聊天完成| 5 | OpenAI 格式、RequestLog、验证 |
| 8. 分析 | 4 |最近/支出/延迟 p50/p99 |
| 9. /v1/{模型、按键、路由} | 8 |列表/创建/撤销+策略更新 |
| 10. 流媒体 | 4 | SSE 格式，`[DONE]` 哨兵，日志写回 |
| 11.目录| 7 | 100 多种型号、功能标志、定价 |
| 12. `模型=“自动”` | 21 | 21能力检测，最便宜的满足需求（单元+集成）|
| 13. 节省成本| 9 |节省与始终 GPT-4 基线 + 托管自动比较 |
| 14.提示缓存| 15 | 15跨提供商精确匹配缓存+聊天集成|
| 15. 基准 | 4 | Summary() + render_markdown() 聚合 |
| 16. 托管状态 | 7 | `/v1/hosted` 配置源 + 注册 URL 表面 |
| 17. 托管自动储蓄 | 3 |综合目录上的“_hosted_auto_ savings”边缘情况 |
| 18. 无法到达的模型 | 7 |当托管打开时，“您无法访问的模型”磁贴会清除 |
| **总计** | **127** | |

＃＃ 建筑学

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

- [x] OpenAI 兼容的聊天完成
- [x] 流媒体 (SSE)
- [x] `model="auto"` 最便宜的路由
- [x] 托管为上游
- [x] 静态加密 BYOK
- [x] 本地分析仪表板
- [x] CI（GitHub 操作）
- [x] 跨提供商提示缓存
- [x]Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK集成
- [x] 公共基准 + 储蓄索赔
- [ ] 嵌入 + 图像生成代理

请参阅 [DEMO.md](./DEMO.md) 了解故障转移演示。

＃＃ 执照

麻省理工学院。请参阅[许可证](./许可证)。
