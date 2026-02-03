# Library API（v0）：pyoco-server

この文書は、本リポジトリが提供する「Pythonとしてimportして使う公開API（public surface）」を定義します。

注記：
- HTTP / NATS の on-wire 契約は `docs/spec.md` が正本です。
- ここでは「Python側のクラス/関数」としての利用方法・安定境界を定義します。
- v0 は進化しますが、原則は後方互換（追加）を優先します。

## 安定性と互換性（v0）
公開APIの範囲：
- `pyoco_server` が export するシンボルのみを public API とします（下記「公開エクスポート」）。
- export されないモジュール（例：`pyoco_server.worker` の内部詳細）は内部であり、v0でも予告なく変更され得ます。

互換性の方針：
- 追加（新フィールド、新しい任意引数、新メソッド）を優先します。
- 0.x でも破壊的変更は起こり得ますが、可能な限り稀にし、明示します。

Deprecation：
- 変更が必要な場合、可能なら互換な代替を追加し、少なくとも1リリースは旧APIを残します。

## 公開エクスポート
`pyoco_server` の public API は以下です。

- `NatsBackendConfig`
- `ensure_resources`
- `PyocoNatsClient`
- `PyocoHttpClient`
- `PyocoNatsWorker`
- `configure_logging`

HTTP Gateway の app factory は以下です。

- `pyoco_server.http_api.create_app()`

## NatsBackendConfig
パス：`src/pyoco_server/config.py`

目的：
- NATS/JetStream の資源名、heartbeat間隔、consumer既定、DLQ設定、スナップショット上限等を集約します。

主要フィールド（抜粋）：
- `nats_url`
- `work_stream`, `work_subject_prefix`
- `runs_kv_bucket`, `workers_kv_bucket`
- `consumer_ack_wait_sec`, `consumer_max_deliver`, `consumer_max_ack_pending`
- `ack_progress_interval_sec`
- `dlq_stream`, `dlq_subject_prefix`, `dlq_publish_execution_error`
- `max_run_snapshot_bytes`
- `workflow_yaml_max_bytes`

env からの生成：
- `NatsBackendConfig.from_env() -> NatsBackendConfig`
  - `docs/spec.md` 付録I の env vars を読み取って構築します。

## ensure_resources(js, config)
パス：`src/pyoco_server/resources.py`

シグネチャ：
- `async def ensure_resources(js, config: NatsBackendConfig) -> None`

責務：
- JetStream リソースが存在することを保証します。
  - Work stream（`PYOCO_WORK`）
  - runスナップショットKV（`pyoco_runs`）
  - worker生死KV（`pyoco_workers`）
  - DLQ stream（`PYOCO_DLQ`）

## PyocoNatsWorker
パス：`src/pyoco_server/worker.py`

生成：
- `await PyocoNatsWorker.connect(config=..., flow_resolver=..., worker_id=..., tags=[...])`

実行（ループ）：
- `await worker.run_once(timeout=...) -> Optional[str]`
  - ジョブを処理した場合は `run_id` を返します。
  - 指定時間内にメッセージが無い場合は `None` を返します。

終了：
- `await worker.close()`

タグルーティング（OR）：
- `tags=[...]` は、このworkerが実行できる `pyoco.work.<tag>` を表します。
- worker は指定された複数タグから pull し、到着したものを実行します（OR semantics）。

flow_resolver 契約：
- `flow_resolver(flow_name: str) -> pyoco.Flow`
- 解決できない場合は `KeyError(flow_name)` を投げることを推奨します。
  - その場合、workerは run を `FAILED` として terminal 化し、DLQ reason `flow_not_found` を出し、メッセージを ACK します（決定的失敗のためリトライしない）。

補足（Phase 4：YAML投入）：
- `POST /runs/yaml` で投入されたジョブは、メッセージ内の `workflow_yaml` から worker が Flow を構築するため、通常は `flow_resolver` を呼びません。

長時間run：
- worker は処理中に JetStream `in_progress` ACK を定期送信します。
  - `AckWait` よりrunが長い場合の意図しない再配送を防ぎます。

スナップショットサイズ：
- worker は最新スナップショットをKVへ書きます。
- `config.max_run_snapshot_bytes` を超える場合、`task_records` を落として `task_records_truncated=true` を立てることがあります（tasksは保持）。

## PyocoNatsClient
パス：`src/pyoco_server/client.py`

目的：
- NATSネイティブクライアント（主に内部利用/テスト向け）。

生成：
- `client = await PyocoNatsClient.connect(config)`

API：
- `await client.submit_run(flow_name, params, tag=..., tags=...) -> run_id`
- `await client.get_run(run_id) -> dict`
- `await client.close()`

## PyocoHttpClient
パス：`src/pyoco_server/http_client.py`

目的：
- Pyoco利用者向けのHTTPクライアント（NATS不要）。

生成：
- `client = PyocoHttpClient(base_url, api_key=..., api_key_header="X-API-Key")`
  - `api_key` は任意です。HTTP Gateway 側で認証（opt-in）が有効な場合のみ指定します（`docs/spec.md` REQ-0016）。

API：
- `client.submit_run(flow_name, params, tag=..., tags=...) -> dict`
- `client.submit_run_yaml(workflow_yaml, flow_name=..., tag=...) -> dict`
- `client.get_run(run_id) -> dict`
- `client.get_run_with_records(run_id) -> dict`（`include=records`）
- `client.get_tasks(run_id) -> dict`
- `client.list_runs(status=..., flow=..., tag=..., full=False, limit=...) -> list[dict]`
- `client.close()`

## HTTP Gateway app factory
パス：`src/pyoco_server/http_api.py`

- `create_app() -> fastapi.FastAPI`

設定：
- gateway は env vars を読み取り `NatsBackendConfig` を構築します。
- env var 一覧と on-wire 契約は `docs/spec.md` を参照してください。
  - 認証（opt-in）：`PYOCO_HTTP_AUTH_MODE=api_key` の場合、`X-API-Key` を要求します。

ログ：
- HTTP Gateway / worker（呼び出し側）は `PYOCO_LOG_*` の設定を読み取り、stdoutへログを出力できます。
- `configure_logging(service=...)` を呼ぶと、env vars に従って root logger が設定されます。
- エラー時は「元例外（発生箇所/例外クラス/メッセージ/トレースバック）」を記録する方針です（`docs/spec.md` の REQ-0013 / `docs/architecture.md` を参照）。

## 運用CLI（API key 管理）
Phase 3（v0.3 opt-in）では、API key 管理用に `python -m pyoco_server.admin_cli ...` を提供します。  
詳細は `docs/architecture.md` と `docs/spec.md`（REQ-0016/0017）を参照してください。
