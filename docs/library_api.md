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
- `wheel_object_store_bucket`, `wheel_sync_enabled`, `wheel_sync_dir`, `wheel_sync_interval_sec`
- `wheel_install_timeout_sec`, `wheel_max_bytes`
- `wheel_history_kv_bucket`, `wheel_history_ttl_sec`
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
  - 認証KV（`pyoco_auth`）
  - DLQ stream（`PYOCO_DLQ`）
  - wheel Object Store（`pyoco_wheels`）

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

wheel同期（opt-in）：
- `config.wheel_sync_enabled=True` の場合、worker は wheel registry（Object Store）を同期します。
- 同期タイミングは「起動時」と「`run_once` の次回poll前」です。
- 実行中runの途中で wheel 更新は開始しません。
- worker tags と wheel tags が1つ以上一致したものだけ同期し、wheel tags が空なら全worker対象です。
- 同一パッケージに複数バージョンがある場合は、最新版のみ同期/インストールします。

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
- `client.list_runs_vnext(status=..., flow=..., tag=..., full=False, limit=..., updated_after=..., cursor=..., workflow_yaml_sha256=...) -> dict`
  - 差分取得形式（`items` + `next_cursor`）で一覧更新を扱います。
- `client.watch_run(run_id, include_records=False, since=..., timeout_sec=...) -> generator`
  - SSE（`/runs/{run_id}/watch`）を購読し、`{"event": ..., "data": ...}` を順次返します。
- `client.cancel_run(run_id, wait=False, timeout_sec=...) -> dict`
- `client.get_workers(scope=..., state=..., include_hidden=..., limit=...) -> list[dict]`
  - worker運用一覧（`GET /workers`）を取得します。
  - 既定は `scope=active` / `include_hidden=false` です（HTTP側の既定）。
  - `wheel_sync`（enabled/last_result/counts/installed_wheels/skipped_incompatible）を含み、配布結果の可視化に利用できます。
- `client.patch_worker_hidden(worker_id, hidden=...) -> dict`
  - worker表示制御（`PATCH /workers/{worker_id}`）を行います。
- `client.list_wheels() -> list[dict]`
- `client.list_wheel_history(limit=..., wheel_name=..., action=...) -> list[dict]`
- `client.upload_wheel(filename=..., data=..., replace=True, tags=[...]) -> dict`
  - 同一パッケージはバージョンを必ず上げて登録する必要があります（同一/過去バージョンはHTTP 409）。
- `client.delete_wheel(wheel_name) -> dict`
- `client.close()`

## HTTP Gateway app factory
パス：`src/pyoco_server/http_api.py`

- `create_app() -> fastapi.FastAPI`

設定：
- gateway は env vars を読み取り `NatsBackendConfig` を構築します。
- env var 一覧と on-wire 契約は `docs/spec.md` を参照してください。
  - 認証（opt-in）：`PYOCO_HTTP_AUTH_MODE=api_key` の場合、`X-API-Key` を要求します。
- gateway は運用向けDashboard UIを静的配信します（`GET /` / `GET /static/*`）。
- gateway は wheel registry API（`GET/POST /wheels`, `GET/DELETE /wheels/{wheel_name}`）を提供します。
- gateway は wheel配布履歴 API（`GET /wheels/history`）を提供します。

ログ：
- HTTP Gateway / worker（呼び出し側）は `PYOCO_LOG_*` の設定を読み取り、stdoutへログを出力できます。
- `configure_logging(service=...)` を呼ぶと、env vars に従って root logger が設定されます。
- エラー時は「元例外（発生箇所/例外クラス/メッセージ/トレースバック）」を記録する方針です（`docs/spec.md` の REQ-0013 / `docs/architecture.md` を参照）。

## 運用CLI（API key 管理）
Phase 3（v0.3 opt-in）では、API key 管理用に `python -m pyoco_server.admin_cli ...` を提供します。  
詳細は `docs/architecture.md` と `docs/spec.md`（REQ-0016/0017）を参照してください。

## 実行CLI（server/worker/client）
`pyproject.toml` の scripts として次を提供します。

- `pyoco-server`（`pyoco_server.server_cli:main`）
- `pyoco-worker`（`pyoco_server.worker_cli:main`）
- `pyoco-client`（`pyoco_server.client_cli:main`）
- `pyoco-server-admin`（`pyoco_server.admin_cli:main`）

`pyoco-server` のCLI補足（v0.4）：
- 既定サブコマンドは `up`（後方互換で旧フラット引数も受理）。
- `up --with-nats-bootstrap` を指定すると、`nats-bootstrap up -- -js ...` で単体NATSを同時起動できます。
- 同時起動時は `PYOCO_NATS_URL` を `nats://<listen_host>:<client_port>` に固定し、`--nats-url` が不一致ならエラー終了します。

`pyoco-client` のCLI補足（v0.4）：
- `submit` は params 入力を3形式で受け付けます（後勝ち）。
  - `--params-file`（JSON/YAML object）
  - `--params`（JSON object）
  - `--param key=value`（複数回指定可）
- `list` / `list-vnext` は `--output json|table` をサポートします。
- `watch` は `--output json|status` をサポートします。
- wheel配布は `wheels` / `wheel-upload` / `wheel-delete` をサポートします。
- 履歴参照は `wheel-history` をサポートします。
- `wheel-upload --wheel-file <path> [--tags cpu,linux] [--replace|--no-replace]`
- `wheel-upload` は同一パッケージでバージョンを必ず上げてください（同一/過去バージョンは409）。
- 利用者が修正可能な失敗は exit code `1` で終了し、stderr に修正例を表示します。
- `workers` は現状、既定条件での一覧取得（`GET /workers`）を実行します。`scope/state/include_hidden` や hide/unhide は `PyocoHttpClient` または直接HTTP APIを利用してください。

`pyoco-worker` のCLI補足（v0.4）：
- wheel同期設定をCLIで上書きできます。
  - `--wheel-sync` / `--no-wheel-sync`
  - `--wheel-sync-dir`
  - `--wheel-sync-interval-sec`
  - `--wheel-install-timeout-sec`
