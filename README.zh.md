# OrcaRouter Lite

[English](./README.md) | **简体中文** | [日本語](./README.ja.md) | [한국어](./README.ko.md) | [Deutsch](./README.de.md) | [Italiano](./README.it.md) | [Français](./README.fr.md) | [Español](./README.es.md) | [العربية](./README.ar.md)

**自托管的 LLM 路由器，附带托管安全网。**
兼容 OpenAI。自带密钥(BYOK)。单工作区。流式传输。`model="auto"`。

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#测试)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#模型目录)
[![license](https://img.shields.io/badge/license-MIT-blue)](#许可证)

OrcaRouter Lite 是 [OrcaRouter](https://www.orcarouter.ai) 的开源单工作区版本。在你的笔记本电脑上运行,集成到你的产品中,或直接使用托管的 `api.orcarouter.ai` 来支持那些你不想自己管理密钥的长尾模型。

> **为什么选择我们?** LiteLLM 是一个库;OpenRouter 是闭源托管;Ollama 仅本地运行。我们是**带有托管回退的自托管服务器** —— 一句它们都说不出口的话。

## 60 秒快速开始

使用 OrcaRouter 有两种方式:

### 方案 A —— 自托管(BYOK)

在你自己的机器上运行 Lite;自带提供商密钥。

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# 至少添加一个: OPENAI_API_KEY=sk-...  (或 ORCAROUTER_API_KEY=...)

docker compose up
# 日志: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

基础 URL: `http://localhost:8000/v1`。使用启动时打印的 `sk-orca-*` 密钥。

### 方案 B —— 托管(需要账户)

无需克隆,无需 docker。注册,获取密钥,将任何 OpenAI SDK 指向托管服务。

```bash
# 1. 在 https://www.orcarouter.ai 注册并复制你的 sk-orca-* 密钥
# 2. 使用 https://api.orcarouter.ai/v1 作为基础 URL
```

**需要账户。** 托管服务负责路由、计费和长尾提供商 —— 按 token 在你的 OrcaRouter 账户上计费。详见 [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction)。

### 然后从任意 OpenAI SDK 调用

下面的示例使用方案 A 的本地 URL —— 如果你使用方案 B,请替换为 `https://api.orcarouter.ai/v1`。

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
    messages=[{"role": "user", "content": "你好!"}],
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
  messages: [{ role: "user", content: "你好!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"你好!"}]}'
```
</details>

打开 `http://localhost:8000/` 查看仪表板 —— 提供商、路由、分析、密钥(仅方案 A)。

## 为什么?

| | Lite | LiteLLM 库 | OpenRouter | Ollama |
|---|---|---|---|---|
| 自托管服务器 | ✓ | 作为库 | ✗ | ✓ |
| 兼容 OpenAI | ✓ | ✓ | ✓ | ✓ |
| 多提供商(OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| 内置仪表板 | ✓ | ✗ | ✓ | ✗ |
| `model="auto"`(满足需求中最便宜) | ✓ | ✗ | ✗ | 不适用 |
| 流式传输 | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | 不适用 |
| 托管作为回退 | ✓ | ✗ | 不适用 | ✗ |
| 无需 Postgres / 无需 Redis | ✓ | 不适用 | 不适用 | ✓ |

## `model="auto"` —— 标志性功能

发送 `model="auto"`,OrcaRouter 会在你配置的提供商中挑选**最便宜**且满足请求能力要求(工具、视觉、JSON 模式)的模型。无需手动路由规则;无需速率限制博弈;无需在你的代码中编写 `if x: ...` 的成本优化。

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "这张图片里有什么?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → 路由到你的密钥覆盖范围内最便宜的支持视觉的模型
```

解析后的模型通过 `x-orca-resolved-model` 响应头返回给调用方,让你可以记录/显示实际使用的模型。

## 托管作为上游(Lite + 托管)

已经在运行 Lite?在 [www.orcarouter.ai](https://www.orcarouter.ai) 设置 `ORCAROUTER_API_KEY` 为你的 `sk-orca-*`,托管服务就会成为路由链中的另一个提供商 —— 覆盖你本地密钥未涵盖的模型:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

使用场景:
- **先试后买** —— 无需本地提供商密钥
- **本地日志记录** —— 托管服务负责路由,Lite 为仪表板存储 RequestLog 行
- **故障转移** —— 本地提供商失败时,托管服务作为安全网

## 流式传输

兼容 OpenAI 的 SSE 格式,采用标准 `data: ... \n\n` 帧和终结 `[DONE]` 哨兵 —— 任何已经支持从 OpenAI 流式传输的 SDK 均可即插即用。

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "给我讲个故事"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## 模型目录

启动时从 [LiteLLM 社区维护的定价数据库](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) 加载 100+ 聊天模型 —— 无需手动维护模型列表。每个条目暴露:

- `id`(例如 `gpt-4o`、`claude-3-5-sonnet-latest`)
- `provider`(映射到你配置的密钥)
- 能力标志: `supports_tools`、`supports_vision`、`supports_json_mode`
- 每 token 输入/输出成本(驱动节省小部件 + `model="auto"`)

`GET /v1/models` 返回 OpenAI 格式的目录。

## 部署到其他地方

| 平台 | 一键部署 |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | 连接仓库,根目录 = `.` |
| 裸 Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...`(镜像即将推出) |

## 包含什么

- `POST /v1/chat/completions` —— 代理 + 流式 + `model="auto"` + 跨提供商提示缓存
- `GET  /v1/models` —— 可发现的模型目录(来自 `litellm.model_cost` 的 100+ 模型)
- `GET/PUT/DELETE /v1/providers/{provider}` —— 设置 / 列出 / 撤销加密的提供商密钥
- `GET/PUT /v1/routing` —— 更改策略(`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` —— 本地分析,无遥测离开机器
- `GET  /v1/hosted` —— 托管回退状态(驱动仪表板的"获取 $5 免费额度"卡片)
- `GET/POST/DELETE /v1/keys/...` —— 列出 / 轮换 / 撤销 API 密钥
- 单页仪表板位于 `/`
- 默认 SQLite;通过 `DATABASE_URL` 选择 Postgres;Redis 可选

### 跨提供商提示缓存

确定性请求(`temperature=0` 或固定 `seed`)在重复时从缓存提供 —— 跨**所有**提供商工作,不仅限于 Anthropic。设置 `REDIS_URL` 时后端为 Redis,否则为进程内 LRU。缓存命中即时返回,带 `x-orca-cache: HIT` 且成本 $0。

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # 相同的负载再次发送
HTTP/1.1 200 OK
x-orca-cache: HIT          ← 从缓存提供,无上游调用
```

### 节省小部件

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` 报告你的流量在始终使用 GPT-4 的成本与实际成本的对比。仪表板将其显示为一个磁贴。

### 集成

[Continue.dev](./integrations/continue.json)、[Aider](./integrations/aider.md)、[Cursor](./integrations/cursor.md)、[LangChain](./integrations/langchain_orcarouter.py)、[LlamaIndex](./integrations/llamaindex_orcarouter.py)、[Vercel AI SDK](./integrations/vercel_ai.ts) 以及任何使用 OpenAI Chat Completions 协议的工具的即插即用配置。详见 [`integrations/`](./integrations/)。

## 故意不包含的内容

这是**单工作区**版本。按设计,不包含:
- 多租户、RBAC、SSO
- 计费、钱包、积分、合作伙伴计划
- 管理控制台、审计日志、信任与安全
- 多 Pod 部署 / Kubernetes
- 用于警报的电子邮件 / Slack / webhook

如需这些功能,请参阅托管产品或(即将推出的)Teams 版本。

## 测试

测试驱动开发。这里发布的每一个行为都先有一个失败的测试。

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| 切片 | 测试 | 内容 |
|---|---|---|
| 1. 配置 | 5 | 环境加载、默认值、`env_provider_keys()` |
| 2. 种子 | 3 | 引导工作区 + API 密钥 + RoutingConfig,幂等 |
| 3. 鉴权中间件 | 4 | bearer-token 验证,缺失/无效时返回 401 |
| 4. 应用工厂 | 3 | /health、错误信封、/v1/* 门控 |
| 5. 提供商密钥 CRUD | 5 | 静态加密,明文从不往返传输 |
| 6. 路由器缓存 | 13 | env+DB+托管部署组装,带优先级 |
| 7. 聊天完成 | 5 | OpenAI 格式、RequestLog、验证 |
| 8. 分析 | 4 | 最近 / 支出 / 延迟 p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | 列出/创建/撤销 + 策略更新 |
| 10. 流式传输 | 4 | SSE 格式、`[DONE]` 哨兵、日志写回 |
| 11. 目录 | 7 | 100+ 模型、能力标志、定价 |
| 12. `model="auto"` | 21 | 能力检测、满足需求中最便宜的(单元 + 集成) |
| 13. 成本节省 | 9 | 与始终使用 GPT-4 的基线节省 + 托管自动比较 |
| 14. 提示缓存 | 15 | 跨提供商精确匹配缓存 + 聊天集成 |
| 15. 基准测试 | 4 | summarize() + render_markdown() 聚合 |
| 16. 托管状态 | 7 | `/v1/hosted` 配置源 + 注册 URL 暴露 |
| 17. 托管自动节省 | 3 | `_hosted_auto_savings` 在合成目录上的边缘情况 |
| 18. 不可达模型 | 7 | 当托管开启时"无法到达的模型"磁贴清除 |
| **总计** | **127** | |

## 架构

```
app/
├── main.py             FastAPI 工厂 + 生命周期 + SPA 挂载
├── config.py           设置(~15 个字段)
├── deps.py             DI 助手
├── seed.py             首次运行引导
├── auto_routing.py     model="auto" 能力 + 成本评分
├── router_cache.py     单工作区路由器
├── prompt_cache.py     跨提供商精确匹配缓存(Redis 或内存中 LRU)
├── schemas.py          兼容 OpenAI 的请求模式
├── middleware/auth.py  sk-orca-* 验证
└── routes/
    ├── chat.py         /v1/chat/completions  (阻塞 + 流式)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      策略配置
    ├── analytics.py    最近 / 支出 / 延迟 / 节省 / 不可达
    ├── keys.py         列出 / 轮换 / 撤销 API 密钥
    ├── hosted.py       /v1/hosted —— 仪表板的托管回退状态
    └── health.py

packages/
├── litellm_adapter/    路由器包装器 + 100+ 模型目录
├── auth/               哈希 + AES-256-GCM
└── db/                 模型 + 引擎 + 会话
```

## 路线图

- [x] 兼容 OpenAI 的聊天完成
- [x] 流式传输(SSE)
- [x] `model="auto"` 满足需求中最便宜的路由
- [x] 托管作为上游
- [x] 静态加密的 BYOK
- [x] 本地分析仪表板
- [x] CI(GitHub Actions)
- [x] 跨提供商提示缓存
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK 集成
- [x] 公开基准测试 + 节省声明
- [ ] 嵌入 + 图像生成代理

详见 [DEMO.md](./DEMO.md) 中的故障转移演示。

## 许可证

MIT。详见 [LICENSE](./LICENSE)。
