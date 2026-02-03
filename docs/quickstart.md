# Quickstart（5分）：run分散実行

このガイドは、想定するユーザー体験（MVP）を5分で確認するための手順です。

- Client は HTTP だけを使う
- Server は NATS JetStream と通信する
- Worker が NATS から run を pull して Pyoco を実行する

## 0) 依存関係を入れる

```bash
uv sync
```

## 1) NATSを起動する（単体）

別ターミナルで実行します。

```bash
uv run nats-server -js -a 127.0.0.1 -p 4222 -m 8222
```

`nats-bootstrap` をラッパとして使うこともできます。

```bash
uv run nats-bootstrap up -- -js -a 127.0.0.1 -p 4222 -m 8222
```

## 1b) NATSを起動する（クラスタ：任意）

ローカル3ノードクラスタを使いたい場合、3つのターミナルでそれぞれ実行します。

ターミナルA：

```bash
uv run nats-bootstrap up --cluster pyoco --listen 127.0.0.1 --client-port 4222 --http-port 8222 --cluster-port 6222 --datafolder artifacts/nats/n1
```

ターミナルB：

```bash
uv run nats-bootstrap join --cluster pyoco --seed 127.0.0.1:6222 --listen 127.0.0.1 --client-port 4223 --http-port 8223 --cluster-port 6223 --datafolder artifacts/nats/n2
```

ターミナルC：

```bash
uv run nats-bootstrap join --cluster pyoco --seed 127.0.0.1:6222 --listen 127.0.0.1 --client-port 4224 --http-port 8224 --cluster-port 6224 --datafolder artifacts/nats/n3
```

以降の手順では、Aノードを `nats://127.0.0.1:4222` として利用します。

## 2) HTTP Gateway を起動する

別ターミナルで実行します。

（任意）`.env` を使う場合：

```bash
set -a
source .env
set +a
```

（任意）ログ設定例：

```bash
export PYOCO_LOG_LEVEL="INFO"
export PYOCO_LOG_FORMAT="json"
export PYOCO_LOG_INCLUDE_TRACEBACK="true"
```

```bash
export PYOCO_NATS_URL="nats://127.0.0.1:4222"
uv run uvicorn pyoco_server.http_api:create_app --factory --host 127.0.0.1 --port 8000
```

## 2b) （任意）HTTP認証（API key）を有効化する
「簡単に始める」ため、既定では無認証です。運用で保護したい場合だけ有効化します。

HTTP Gateway を起動する前に設定します：

```bash
export PYOCO_HTTP_AUTH_MODE="api_key"
export PYOCO_AUTH_KV_BUCKET="pyoco_auth"
export PYOCO_HTTP_API_KEY_HEADER="X-API-Key"
```

API key を発行します（平文キーはこの時だけ表示されます）：

```bash
uv run python -m pyoco_server.admin_cli api-key create --tenant demo
```

出力された API key を控えて、以降のリクエストに `X-API-Key` として付与してください。

## 3) Worker を起動する（サンプルflow）

別ターミナルで実行します。

```bash
uv run python examples/run_worker.py --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1
```

## 4) run を投入する（HTTP client）

別ターミナルで実行します。

```bash
uv run python examples/submit_run.py --server http://127.0.0.1:8000 --tag hello
```

（2b を有効にした場合は、API key を付与して投入します）

```bash
uv run python examples/submit_run.py --server http://127.0.0.1:8000 --tag hello --api-key "<your_api_key>"
```

確認できること：
- worker がジョブを受け取り、実行する
- `GET /runs/{run_id}` が `COMPLETED` とタスク状態を返す

## 4b) （任意）YAML（flow.yaml）で run を投入する（Phase 4）
信頼できる社内チーム向けの投入I/Fとして、`flow.yaml`（YAML）をそのまま投入できます。

前提：
- pyoco 0.6.1 の `flow.yaml` は **単体flow** です（top-level は `flow:`）。
- `flow.yaml` に `discovery` は書けません（禁止）。利用可能なタスクは worker 側の環境（インストール済みパッケージや `PYOCO_DISCOVERY_MODULES` 等）で決まります。

例（`flow.yaml`）：
```yaml
version: 1
flow:
  graph: |
    task_a >> task_b
  defaults:
    x: 1
tasks:
  task_a:
    callable: your_pkg.tasks:task_a
  task_b:
    callable: your_pkg.tasks:task_b
```

投入（例：curl / multipart）：
```bash
curl -sS \\
  -F "flow_name=main" \\
  -F "tag=hello" \\
  -F "workflow=@flow.yaml;type=application/x-yaml" \\
  http://127.0.0.1:8000/runs/yaml
```

（2b を有効にした場合は、`X-API-Key` を付与します）
```bash
curl -sS \\
  -H "X-API-Key: <your_api_key>" \\
  -F "flow_name=main" \\
  -F "tag=hello" \\
  -F "workflow=@flow.yaml;type=application/x-yaml" \\
  http://127.0.0.1:8000/runs/yaml
```

## 5) （任意）運用向けエンドポイントを確認する

別ターミナルで実行します。

```bash
curl -sS http://127.0.0.1:8000/metrics | head
curl -sS http://127.0.0.1:8000/workers
```
