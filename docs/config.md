# config.md（設定：server/worker 共通）

このプロジェクトは、HTTP Gateway / worker の設定を「環境変数」で行います。
`.env` ファイルを使ってもよいです（ただし `.env.sample` は作りません）。

## 1) `.env` の読み込み
`NatsBackendConfig.from_env()` は既定で `.env` を自動読込します（`PYOCO_LOAD_DOTENV=1`）。

- 既定のファイル: `.env`（カレントディレクトリ）
- 読込を無効化: `PYOCO_LOAD_DOTENV=0`
- 別ファイルを指定: `PYOCO_ENV_FILE=/path/to/custom.env`

シェルで明示的に読み込む運用も可能です（従来方式）。

```bash
set -a
source .env
set +a
```

## 2) `.env` 例（必要に応じて作成）
以下は例です。必要なものだけ置いてください。

```bash
# NATS
PYOCO_NATS_URL="nats://127.0.0.1:4222"

# JetStream subject / buckets
PYOCO_WORK_SUBJECT_PREFIX="pyoco.work"
PYOCO_DEFAULT_TAG="default"
PYOCO_RUNS_KV_BUCKET="pyoco_runs"
PYOCO_WORKERS_KV_BUCKET="pyoco_workers"

# Heartbeat
PYOCO_RUN_HEARTBEAT_INTERVAL_SEC="1.0"
PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC="5.0"
PYOCO_WORKERS_KV_TTL_SEC="15.0"
PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC="20.0"

# Consumers
PYOCO_CONSUMER_ACK_WAIT_SEC="30.0"
PYOCO_CONSUMER_MAX_DELIVER="20"
PYOCO_CONSUMER_MAX_ACK_PENDING="200"
PYOCO_ACK_PROGRESS_INTERVAL_SEC="10.0"

# DLQ
PYOCO_DLQ_STREAM="PYOCO_DLQ"
PYOCO_DLQ_SUBJECT_PREFIX="pyoco.dlq"
PYOCO_DLQ_PUBLISH_EXECUTION_ERROR="true"
PYOCO_DLQ_MAX_AGE_SEC="604800"
PYOCO_DLQ_MAX_MSGS="100000"
PYOCO_DLQ_MAX_BYTES="536870912"

# Snapshot size
PYOCO_MAX_RUN_SNAPSHOT_BYTES="262144"

# Wheel registry（JetStream Object Store + worker sync）
PYOCO_WHEEL_OBJECT_STORE_BUCKET="pyoco_wheels"
PYOCO_WHEEL_MAX_BYTES="536870912"
PYOCO_WHEEL_SYNC_ENABLED="0" # 0|1（既定は無効）
PYOCO_WHEEL_SYNC_DIR=".pyoco/wheels"
PYOCO_WHEEL_SYNC_INTERVAL_SEC="10.0"
PYOCO_WHEEL_INSTALL_TIMEOUT_SEC="180.0"
PYOCO_WHEEL_HISTORY_KV_BUCKET="pyoco_wheel_history"
PYOCO_WHEEL_HISTORY_TTL_SEC="7776000" # 90 days

# Workflow YAML（flow.yaml）policy
# `POST /runs/yaml` で受け付ける `flow.yaml` のサイズ上限（bytes）。
PYOCO_WORKFLOW_YAML_MAX_BYTES="262144"

# Dashboard locale（UI文言）
# auto: サーバーロケールから判定 / ja|en: 固定
PYOCO_DASHBOARD_LANG="auto"

# Dotenv loader policy（任意）
# 既定: 自動読込ON / 読込元は ".env"
PYOCO_LOAD_DOTENV="1" # 0|1
# PYOCO_ENV_FILE="/path/to/custom.env"

# Logging（HTTP Gateway / worker 共通）
PYOCO_LOG_LEVEL="INFO"
PYOCO_LOG_FORMAT="json" # json|text
PYOCO_LOG_UTC="true"
PYOCO_LOG_INCLUDE_TRACEBACK="true"

# HTTP auth（opt-in）
# 既定は無認証（none）。有効化する場合は api_key を指定します。
PYOCO_HTTP_AUTH_MODE="none" # none|api_key
PYOCO_HTTP_API_KEY_HEADER="X-API-Key"
PYOCO_AUTH_KV_BUCKET="pyoco_auth"
# 任意（推奨）：API key の照合に pepper を混ぜる。秘密情報として扱う。
# PYOCO_AUTH_PEPPER="..."
```

## 3) HTTP Gateway（server）の設定
HTTP Gateway は env vars を読み取り、起動時に設定を構築します。

- 実装：`src/pyoco_server/http_api.py`
- 設定：`NatsBackendConfig.from_env()`（`src/pyoco_server/config.py`）

起動例：
```bash
export PYOCO_NATS_URL="nats://127.0.0.1:4222"
uv run uvicorn pyoco_server.http_api:create_app --factory --host 127.0.0.1 --port 8000
```

`pyoco-server` CLI を使う場合は、起動時オプションでも指定できます。

```bash
uv run pyoco-server up --host 127.0.0.1 --port 8000 --dashboard-lang ja
```

単体NATSを同時起動したい場合（`nats-bootstrap` 必須）：

```bash
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000
```

## 4) Worker の設定
worker は `PyocoNatsWorker.connect(config=..., ...)` で `NatsBackendConfig` を受け取ります。
`.env` を使いたい場合は、`NatsBackendConfig.from_env()` を利用します。

例（擬似コード）：
```python
from pyoco_server import NatsBackendConfig, PyocoNatsWorker, configure_logging

configure_logging(service="pyoco-server:worker")
cfg = NatsBackendConfig.from_env()
worker = await PyocoNatsWorker.connect(config=cfg, flow_resolver=..., worker_id="w1", tags=["hello"])
```

worker状態表示（`GET /workers`）に関する補足：
- `PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC` を超えて `last_seen_at` が更新されない worker は、表示上 `DISCONNECTED` として扱われます。
- `STOPPED_GRACEFUL` は明示停止状態として保持され、`DISCONNECTED` とは区別されます。

wheel同期（opt-in）に関する補足：
- `PYOCO_WHEEL_SYNC_ENABLED=1` を指定すると、worker は起動時と定期的に wheel レジストリ（Object Store）を同期します。
- worker は自身の `tags` と wheel の `tags` が1つ以上一致する場合にその wheel を同期します。
- wheel 側の `tags` が空の場合は、全workerが同期対象として扱います。
- 同一パッケージに複数バージョンがある場合、worker は最新版のみを同期/インストールします。
- worker は実行中runの途中で同期を開始しません（次回poll前に同期）。
- 変更検知は Object Store の `nuid` 差分で行い、差分がある wheel のみ `pip install --force-reinstall --no-deps` を実行します。
- 同期先ディレクトリは `PYOCO_WHEEL_SYNC_DIR` で指定します（既定 `.pyoco/wheels`）。
- 配布履歴は `PYOCO_WHEEL_HISTORY_KV_BUCKET` に保存され、`GET /wheels/history` で参照できます。
- workerごとの同期結果（最新成功/失敗、互換外skip件数、反映済みwheel）は `GET /workers` の `wheel_sync` で参照できます。

## 5) ログ（設定とエラー時要件）
ログ仕様は `docs/architecture.md` の「ログ仕様（提案：JSON Lines）」と、
`docs/spec.md` の `REQ-0013` を参照してください。

## 6) HTTP auth（opt-in）
HTTP Gateway は、既定では無認証で `/runs*` を受け付けます（簡単に始めるため）。
運用で保護したい場合は、`PYOCO_HTTP_AUTH_MODE=api_key` を設定して API key 認証を有効化します。

- 保存先：JetStream KV（`PYOCO_AUTH_KV_BUCKET`）
- ヘッダ：`PYOCO_HTTP_API_KEY_HEADER`（既定 `X-API-Key`）
- 仕様：`docs/spec.md`（REQ-0016/0017）
- 設計：`docs/architecture.md`（セキュリティ設計 / CLI）

## 7) ワークフローYAML（flow.yaml）投入（Phase 4）
HTTP Gateway は `POST /runs/yaml` で `flow.yaml`（YAML）を受け取れます。

- サイズ上限：`PYOCO_WORKFLOW_YAML_MAX_BYTES`
- 仕様：`docs/spec.md`（REQ-0018）

補足（pyoco側の仕様）：
- pyoco 0.6.0+ では `flow.yaml` に `discovery` を書けません（禁止）。追加タスクのimportは環境側で行います。
  - 例：環境変数 `PYOCO_DISCOVERY_MODULES`（pyoco本体の設定）

## 8) Wheel レジストリAPI（運用）
HTTP Gateway は wheel 管理 API を提供します（`/wheels`）。

- `GET /wheels`：登録済みwheel一覧
- `POST /wheels`：wheelアップロード（multipart `wheel`, `replace`, `tags`）。同一パッケージは必ずバージョンアップが必要（同一/過去バージョンは409）
- `GET /wheels/{wheel_name}`：wheelダウンロード
- `DELETE /wheels/{wheel_name}`：wheel削除
- `GET /wheels/history`：配布履歴（upload/delete、アップロード元情報を含む）

CLI 例：
```bash
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/my_task_ext-0.1.0-py3-none-any.whl --tags cpu,linux
uv run pyoco-client --server http://127.0.0.1:8000 wheels
uv run pyoco-client --server http://127.0.0.1:8000 wheel-history --limit 20
```
