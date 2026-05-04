# OrcaRouter Lite

[English](./README.md) | [简体中文](./README.zh.md) | **日本語** | [한국어](./README.ko.md) | [Deutsch](./README.de.md) | [Italiano](./README.it.md) | [Français](./README.fr.md) | [Español](./README.es.md) | [العربية](./README.ar.md)

**マネージドセーフティネット付きのセルフホスト LLM ルーター。**
OpenAI 互換。BYOK。シングルワークスペース。ストリーミング。`model="auto"`。

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#テスト)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#モデルカタログ)
[![license](https://img.shields.io/badge/license-MIT-blue)](#ライセンス)

OrcaRouter Lite は [OrcaRouter](https://www.orcarouter.ai) のオープンソース・シングルワークスペース版です。ノートパソコンで実行したり、製品に組み込んだり、自分で鍵を管理したくないロングテールモデルにはホスト型 `api.orcarouter.ai` を直接利用できます。

> **なぜ私たちか?** LiteLLM はライブラリ、OpenRouter はクローズドソースのホスト型、Ollama はローカル専用。私たちは**マネージドフォールバック付きのセルフホストサーバー** —— どれもこの一文を言うことはできません。

## 60 秒クイックスタート

OrcaRouter を使う 2 つの方法:

### パス A —— セルフホスト(BYOK)

Lite を自分のマシンで実行し、自分のプロバイダー鍵を持ち込みます。

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# 少なくとも 1 つを追加: OPENAI_API_KEY=sk-...  (または ORCAROUTER_API_KEY=...)

docker compose up
# ログ: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

ベース URL: `http://localhost:8000/v1`。起動時に表示される `sk-orca-*` 鍵を使用します。

### パス B —— ホスト型(アカウント必須)

クローン不要、docker 不要。登録、鍵を取得、任意の OpenAI SDK をホスト型に向けます。

```bash
# 1. https://www.orcarouter.ai で登録し、sk-orca-* 鍵をコピー
# 2. https://api.orcarouter.ai/v1 をベース URL として使用
```

**アカウントが必要です。** ホスト型はルーティング、課金、ロングテールプロバイダーを処理 —— OrcaRouter アカウントでトークンごとに課金されます。[docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction) を参照してください。

### 任意の OpenAI SDK から呼び出す

以下の例ではパス A の localhost ベース URL を使用しています —— パス B の場合は `https://api.orcarouter.ai/v1` に置き換えてください。

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # または "gpt-4o-mini"、"claude-3-5-sonnet-latest"、...
    messages=[{"role": "user", "content": "こんにちは!"}],
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
  messages: [{ role: "user", content: "こんにちは!" }],
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
  -d '{"model":"auto","messages":[{"role":"user","content":"こんにちは!"}]}'
```
</details>

`http://localhost:8000/` を開くとダッシュボードが表示されます —— プロバイダー、ルーティング、分析、鍵(パス A のみ)。

## なぜ?

| | Lite | LiteLLM ライブラリ | OpenRouter | Ollama |
|---|---|---|---|---|
| セルフホストサーバー | ✓ | ライブラリとして | ✗ | ✓ |
| OpenAI 互換 | ✓ | ✓ | ✓ | ✓ |
| マルチプロバイダー(OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| 組み込みダッシュボード | ✓ | ✗ | ✓ | ✗ |
| `model="auto"`(必要要件を満たす最安) | ✓ | ✗ | ✗ | 該当なし |
| ストリーミング | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | 該当なし |
| フォールバックとしてのホスト型 | ✓ | ✗ | 該当なし | ✗ |
| Postgres / Redis 不要 | ✓ | 該当なし | 該当なし | ✓ |

## `model="auto"` —— 目玉機能

`model="auto"` を送信すると、OrcaRouter は設定されたプロバイダー内で、リクエストの能力要件(ツール、ビジョン、JSON モード)を満たす**最安**のモデルを選択します。手動ルーティングルールなし、レート制限の調整なし、コード内での `if x: ...` のコスト最適化なし。

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "この画像には何が写っていますか?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → あなたの鍵がカバーする最安のビジョン対応モデルにルーティング
```

解決されたモデルは `x-orca-resolved-model` レスポンスヘッダー経由で呼び出し元に公開されるため、実際に使用されたモデルをログ/表示できます。

## アップストリームとしてのホスト型(Lite + ホスト型)

すでに Lite を実行していますか? [www.orcarouter.ai](https://www.orcarouter.ai) からの `sk-orca-*` を `ORCAROUTER_API_KEY` に設定すると、ホスト型はルーティングチェーンの 1 つのプロバイダーとなります —— ローカル鍵がカバーしないモデルをカバーします:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

ユースケース:
- **試してから購入** —— ローカルプロバイダー鍵不要
- **ローカルロギング** —— ホスト型がルーティングを処理し、Lite はダッシュボード用に RequestLog 行を保存
- **フェイルオーバー** —— ローカルプロバイダーが失敗、ホスト型がセーフティネット

## ストリーミング

OpenAI 互換の SSE 形式、標準の `data: ... \n\n` フレームと終端 `[DONE]` センチネル付き —— OpenAI からすでにストリーミングする任意の SDK にドロップインで使えます。

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "物語を聞かせて"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## モデルカタログ

100+ チャットモデルが起動時に [LiteLLM のコミュニティ管理価格データベース](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) からロードされます —— 手動で管理するモデルリストはありません。各エントリは以下を公開します:

- `id`(例: `gpt-4o`、`claude-3-5-sonnet-latest`)
- `provider`(設定された鍵にマッピング)
- 能力フラグ: `supports_tools`、`supports_vision`、`supports_json_mode`
- トークンあたりの入力/出力コスト(節約ウィジェットと `model="auto"` を駆動)

`GET /v1/models` は OpenAI 形式のカタログを返します。

## 他の場所にデプロイ

| プラットフォーム | ワンクリック |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | リポジトリを接続、ルートディレクトリ = `.` |
| ベア Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...`(イメージ近日公開) |

## 何が含まれているか

- `POST /v1/chat/completions` —— プロキシ + ストリーミング + `model="auto"` + クロスプロバイダープロンプトキャッシュ
- `GET  /v1/models` —— 発見可能なモデルカタログ(`litellm.model_cost` からの 100+ モデル)
- `GET/PUT/DELETE /v1/providers/{provider}` —— 暗号化されたプロバイダー鍵の設定 / 一覧 / 取り消し
- `GET/PUT /v1/routing` —— 戦略の変更(`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` —— ローカル分析、テレメトリーは外部に出ません
- `GET  /v1/hosted` —— ホストフォールバック状態(ダッシュボードの「$5 無料クレジットを取得」カードを駆動)
- `GET/POST/DELETE /v1/keys/...` —— API 鍵の一覧 / ローテーション / 取り消し
- `/` でのシングルページダッシュボード
- デフォルトで SQLite、`DATABASE_URL` で Postgres オプトイン、Redis オプション

### クロスプロバイダープロンプトキャッシュ

決定論的リクエスト(`temperature=0` または固定 `seed`)は繰り返し時にキャッシュから提供されます —— Anthropic だけでなく**すべての**プロバイダーで動作します。`REDIS_URL` が設定されている場合のバックエンドは Redis、それ以外はインプロセス LRU です。キャッシュヒットは `x-orca-cache: HIT` で即座に返り、コストは $0 です。

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # 同じペイロードをもう一度
HTTP/1.1 200 OK
x-orca-cache: HIT          ← キャッシュから提供、アップストリーム呼び出しなし
```

### 節約ウィジェット

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` は、トラフィックを常に GPT-4 で実行した場合のコストと、実際にかかったコストを報告します。ダッシュボードはこれをタイルとして表示します。

### インテグレーション

[Continue.dev](./integrations/continue.json)、[Aider](./integrations/aider.md)、[Cursor](./integrations/cursor.md)、[LangChain](./integrations/langchain_orcarouter.py)、[LlamaIndex](./integrations/llamaindex_orcarouter.py)、[Vercel AI SDK](./integrations/vercel_ai.ts)、および OpenAI Chat Completions プロトコルを話す任意のツール用のドロップイン構成。[`integrations/`](./integrations/) を参照してください。

## 意図的に含まれていないもの

これは**シングルワークスペース**版です。設計により、以下はありません:
- マルチテナンシー、RBAC、SSO
- 課金、ウォレット、ポイント、パートナープログラム
- 管理コンソール、監査ログ、トラスト&セーフティ
- マルチポッドデプロイ / Kubernetes
- アラート用のメール / Slack / Webhook

これらが必要な場合は、ホスト型製品または(今後リリース予定の)Teams 版を参照してください。

## テスト

テストファースト構築。ここで出荷されたすべての動作には、まず失敗するテストがありました。

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| スライス | テスト | 内容 |
|---|---|---|
| 1. 設定 | 5 | env 読み込み、デフォルト、`env_provider_keys()` |
| 2. シード | 3 | ワークスペース + API 鍵 + RoutingConfig のブートストラップ、冪等 |
| 3. 認証ミドルウェア | 4 | ベアラートークン検証、欠落/無効時に 401 |
| 4. アプリファクトリ | 3 | /health、エラーエンベロープ、/v1/* ゲーティング |
| 5. プロバイダー鍵 CRUD | 5 | 静止時暗号化、平文は往復しない |
| 6. ルーターキャッシュ | 13 | 優先度を持つ env+DB+ホストデプロイメントアセンブリ |
| 7. チャット完了 | 5 | OpenAI 形式、RequestLog、検証 |
| 8. 分析 | 4 | 最近 / 支出 / レイテンシ p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | 一覧/作成/取り消し + 戦略更新 |
| 10. ストリーミング | 4 | SSE 形式、`[DONE]` センチネル、ログ書き戻し |
| 11. カタログ | 7 | 100+ モデル、能力フラグ、価格 |
| 12. `model="auto"` | 21 | 能力検出、要件を満たす最安(ユニット + 統合) |
| 13. コスト節約 | 9 | 常に GPT-4 ベースラインに対する節約 + ホストオート比較 |
| 14. プロンプトキャッシュ | 15 | クロスプロバイダー完全一致キャッシュ + チャット統合 |
| 15. ベンチマーク | 4 | summarize() + render_markdown() 集約 |
| 16. ホスト状態 | 7 | `/v1/hosted` 設定ソース + サインアップ URL 表面 |
| 17. ホストオート節約 | 3 | 合成カタログでの `_hosted_auto_savings` エッジケース |
| 18. 到達不能モデル | 7 | ホストがオンの場合に「到達できないモデル」タイルがクリアされる |
| **合計** | **127** | |

## アーキテクチャ

```
app/
├── main.py             FastAPI ファクトリ + ライフスパン + SPA マウント
├── config.py           設定(~15 フィールド)
├── deps.py             DI ヘルパー
├── seed.py             初回実行ブートストラップ
├── auto_routing.py     model="auto" 能力 + コストスコアリング
├── router_cache.py     シングルワークスペースルーター
├── prompt_cache.py     クロスプロバイダー完全一致キャッシュ(Redis またはインメモリ LRU)
├── schemas.py          OpenAI 互換リクエストスキーマ
├── middleware/auth.py  sk-orca-* 検証
└── routes/
    ├── chat.py         /v1/chat/completions  (ブロッキング + ストリーミング)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      戦略構成
    ├── analytics.py    最近 / 支出 / レイテンシ / 節約 / 到達不能
    ├── keys.py         API 鍵の一覧 / ローテーション / 取り消し
    ├── hosted.py       /v1/hosted —— ダッシュボード用のホストフォールバック状態
    └── health.py

packages/
├── litellm_adapter/    ルーターラッパー + 100+ モデルカタログ
├── auth/               ハッシュ + AES-256-GCM
└── db/                 モデル + エンジン + セッション
```

## ロードマップ

- [x] OpenAI 互換チャット完了
- [x] ストリーミング(SSE)
- [x] `model="auto"` 要件を満たす最安ルーティング
- [x] アップストリームとしてのホスト型
- [x] 静止時暗号化された BYOK
- [x] ローカル分析ダッシュボード
- [x] CI(GitHub Actions)
- [x] クロスプロバイダープロンプトキャッシュ
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK インテグレーション
- [x] パブリックベンチマーク + 節約クレーム
- [ ] 埋め込み + 画像生成プロキシ

フェイルオーバーデモについては [DEMO.md](./DEMO.md) を参照してください。

## ライセンス

MIT。[LICENSE](./LICENSE) を参照してください。
