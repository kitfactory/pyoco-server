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

`nats-bootstrap` でNATS同時起動したい場合（単体NATS）：

```bash
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000
```

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
uv run pyoco-server up --host 127.0.0.1 --port 8000
```

補足：
- `--with-nats-bootstrap` は `nats-bootstrap` コマンドが見つからない場合エラーになります。
- `--with-nats-bootstrap` は単体NATS起動のみを扱います（クラスタ運用は従来どおり手動起動）。

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
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1
```

YAMLジョブ（`submit-yaml`）を主に使う場合、`--flow-resolver` は不要です。  
`submit`（flow_name投入）も使う場合は `--flow-resolver examples/hello_flow.py:resolve_flow` を付けて起動してください。

### 3b) （任意）wheel同期を有効化する
workerごとの手動インストールを減らしたい場合は、wheel同期を有効化します。

```bash
export PYOCO_WHEEL_SYNC_ENABLED="1"
export PYOCO_WHEEL_SYNC_DIR=".pyoco/wheels"
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1 --wheel-sync
```

wheel登録例（別ターミナル）：

```bash
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/my_task_ext-0.1.0-py3-none-any.whl --tags hello,linux
uv run pyoco-client --server http://127.0.0.1:8000 wheels
uv run pyoco-client --server http://127.0.0.1:8000 wheel-history --limit 20
```

補足：
- worker は「起動時」と「次回poll前」に同期します。
- 実行中runの途中では wheel 更新を開始しません。
- wheel tags が空の場合は、全workerが同期対象です。
- 同一パッケージに複数バージョンがある場合、worker は最新版のみ同期します。
- 同一パッケージを再配布する場合は、wheelバージョンを必ず上げてください（同一/過去バージョンは409）。

## 4) YAML（flow.yaml）で run を投入する（推奨）

別ターミナルで実行します。

```bash
cat > flow.yaml <<'YAML'
version: 1
flow:
  graph: |
    add_one >> to_text
  defaults:
    x: 1
tasks:
  add_one:
    callable: pyoco_server._workflow_test_tasks:add_one
  to_text:
    callable: pyoco_server._workflow_test_tasks:to_text
YAML
```

```bash
uv run pyoco-client --server http://127.0.0.1:8000 submit-yaml --workflow-file flow.yaml --flow-name main --tag hello
```

（2b を有効にした場合は、API key を付与して投入します）

```bash
uv run pyoco-client --server http://127.0.0.1:8000 --api-key "<your_api_key>" submit-yaml --workflow-file flow.yaml --flow-name main --tag hello
```

確認できること：
- worker がジョブを受け取り、実行する
- `GET /runs/{run_id}` が `COMPLETED` とタスク状態を返す

補助コマンド（例）：
```bash
uv run pyoco-client --server http://127.0.0.1:8000 list --tag hello --limit 20 --output table
uv run pyoco-client --server http://127.0.0.1:8000 get <run_id>
uv run pyoco-client --server http://127.0.0.1:8000 watch <run_id> --until-terminal --output status
```

## 4b) （任意）flow_name で run を投入する（互換ルート）
既存の `flow_name` ベース投入を使う場合は `submit` を利用します。

```bash
uv run pyoco-client --server http://127.0.0.1:8000 submit --flow-name main --tag hello --tags hello --param ts=1 --param name=demo
```

（2b を有効にした場合）
```bash
uv run pyoco-client --server http://127.0.0.1:8000 --api-key "<your_api_key>" submit --flow-name main --tag hello --tags hello --param ts=1 --param name=demo
```

`submit` の params 指定は次の3形式を併用できます（後勝ち）：
- `--params-file params.yaml`（JSON/YAML object）
- `--params '{"x":1}'`（JSON object）
- `--param key=value`（複数回指定可）

## 5) （任意）運用向けエンドポイントを確認する

別ターミナルで実行します。

Dashboard UI（read-only）：ブラウザで `http://127.0.0.1:8000/` を開きます。  
Auth有効時は、画面右上に `X-API-Key` を入力して適用します。

```bash
curl -sS http://127.0.0.1:8000/metrics | head
curl -sS http://127.0.0.1:8000/workers
```

## 6) Workers運用状態を確認する（vNext）

`/workers` は運用向けに、状態と表示制御（hidden）を扱えます。

- state:
  - `RUNNING`（実行中）
  - `IDLE`（待機中）
  - `STOPPED_GRACEFUL`（正常停止）
  - `DISCONNECTED`（heartbeat途絶）
- 既定値:
  - `scope=active`（`RUNNING|IDLE`）
  - `include_hidden=false`

例（全workerを表示し、hiddenも含める）：

```bash
curl -sS "http://127.0.0.1:8000/workers?scope=all&include_hidden=true"
```

例（状態で絞り込む）：

```bash
curl -sS "http://127.0.0.1:8000/workers?scope=all&state=DISCONNECTED"
```

例（workerを一覧から非表示にする）：

```bash
curl -sS -X PATCH "http://127.0.0.1:8000/workers/w1" \
  -H "Content-Type: application/json" \
  -d '{"hidden": true}'
```

再表示（unhide）：

```bash
curl -sS -X PATCH "http://127.0.0.1:8000/workers/w1" \
  -H "Content-Type: application/json" \
  -d '{"hidden": false}'
```

補足：
- `DISCONNECTED` 判定の閾値は `PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC`（既定 20 秒）です。
- `pyoco-client workers` は現状、既定条件（active + 非hidden）での取得を想定しています。運用時の詳細条件指定は HTTP API（`/workers` クエリ）を利用します。
