# plan.md（必ず書く：最新版）

# current
- [x] `docs/OVERVIEW.md` を確認し、Phase 2（v0.2）完了 / Phase 3（v0.3 opt-in）着手に現在地を更新する（`docs/OVERVIEW.md`）
- [x] Phase 3（v0.3 opt-in）：API key 認証と tenant attribution の仕様を追記する（HTTPは既定で無認証、opt-inで有効化）（`docs/spec.md`）
- [x] Phase 3（v0.3 opt-in）：API key を NATS KV に保存する方針・キー構造・ローテーション/失効・秘匿（平文非保存/ログ非出力）を設計に追記する（`docs/architecture.md`）
- [x] Phase 3（v0.3 opt-in）：設定（env vars / `.env`）を追記する（Auth用KV bucket、Authモード、ヘッダ名）（`docs/config.md` / `docs/spec.md` 付録I）
- [x] Phase 3（v0.3 opt-in）：HTTP API 契約（`X-API-Key`、401/403、run snapshotへの `tenant_id`/`key_id` 露出）を追記する（`docs/library_api.md`）
- [x] チュートリアル/Quickstartに「認証opt-in」手順を追記する（`docs/quickstart.md` / `docs/tutorial_multi_worker.md`）

- [x] v0.2.0 の区切り：全テストを実行してグリーンを確認する（`uv run pytest`）
- [x] v0.2.0 の区切り：現状実装が Phase 2 までを満たしている前提で version を更新する（`pyproject.toml` / `README.md` / `docs/OVERVIEW.md`）

- [x] Auth用の env vars と設定項目を追加する（例：`PYOCO_HTTP_AUTH_MODE` / `PYOCO_AUTH_KV_BUCKET`）（`src/pyoco_server/config.py`）
- [x] 追加した env vars の単体テストを更新する（`tests/test_config_from_env.py`）
- [x] JetStream resources に Auth用KV bucket を追加する（`src/pyoco_server/resources.py`）
- [x] E2E（現物）：Gateway起動時に Auth KV bucket が自動作成されることを検証する（`tests/test_nats_e2e.py`）

- [x] API key レコード（`tenant_id`/`key_id`/hash/salt/失効など）と検証ロジックを実装する（平文非保存、ログ非出力）（`src/pyoco_server/auth.py`）
- [x] API key の単体テストを追加する（hash/verify、失効判定、入力バリデーション）（`tests/test_auth.py`）
- [x] API key 管理コマンド（create/list/revoke）を実装する（保存先は NATS KV、平文キーは生成時の1回のみ出力）（`src/pyoco_server/admin_cli.py` など）
- [x] E2E（現物）：API key 管理コマンドでキーを発行し、KVに保存できることを検証する（`tests/test_nats_e2e.py`）

- [x] HTTP Gateway に API key 認証（opt-in）を実装する（ヘッダ `X-API-Key`、失敗は 401/403）（`src/pyoco_server/http_api.py`）
- [x] E2E（現物）：既定（無認証）のまま `POST /runs` がヘッダ無しで成功することを検証する（後方互換）（`tests/test_nats_e2e.py`）
- [x] E2E（現物）：Auth有効時に API key なし/不正/失効で `POST /runs` が 401/403 になることを検証する（`tests/test_nats_e2e.py`）

- [x] 認証成功時に `tenant_id`/`key_id` を run snapshot と job payload に刻む（workerは検証しない）（`src/pyoco_server/http_api.py` / `src/pyoco_server/models.py` / `src/pyoco_server/worker.py`）
- [x] E2E（現物）：正しい API key で `POST /runs` が成功し、`GET /runs/{run_id}` に `tenant_id`/`key_id` が出ることを検証する（`tests/test_nats_e2e.py`）

- [x] v0.3.0 の区切り：全テストを実行してグリーンを確認する（`uv run pytest`）
- [x] v0.3.0 の区切り：version を更新する（`pyproject.toml` / `README.md` / `docs/OVERVIEW.md`）
- [x] Phase 4（v0.4）：pyoco 0.6.1 の「flow単体（`flow:`）」に合わせ、YAML投入（`POST /runs/yaml`）の仕様・設計・実装・テストを追加する（`docs/*` / `src/*` / `tests/*`）
- [x] Phase 4（v0.4）：`docs/OVERVIEW.md` の現在地を更新する（Phase 4 / v0.4.0、pyoco 0.6.1 single-flow）（`docs/OVERVIEW.md`）
- [x] Phase 4（v0.4）：仕様（REQ/ERR/MSG）に「YAML（flow.yaml）でrun投入」を追加する（サイズ上限/不明キー拒否、paramsは `flow.defaults` を正本）（`docs/spec.md`）
- [x] Phase 4（v0.4）：設定に「YAML投入のサイズ上限」を追加する（`PYOCO_WORKFLOW_YAML_MAX_BYTES`）（`docs/config.md` / `src/pyoco_server/config.py`）
- [x] Phase 4（v0.4）：実装：HTTP Gateway に `POST /runs/yaml`（multipart）を追加し、YAMLをメッセージに埋めてpublishする（`src/pyoco_server/http_api.py`）
- [x] Phase 4（v0.4）：実装：RunJob に `workflow_yaml` を追加し、worker が YAML から Flow を構築して実行できるようにする（`src/pyoco_server/models.py` / `src/pyoco_server/worker.py`）
- [x] Phase 4（v0.4）：実装：Python library API に YAML投入メソッドを追加する（`src/pyoco_server/http_client.py` / `docs/library_api.md`）
- [x] Phase 4（v0.4）：単体テスト：YAMLの不明キー拒否/禁止キー/defaults抽出を検証する（`tests/test_workflow_yaml.py`）
- [x] Phase 4（v0.4）：E2E（現物）：実 `nats-server` + 実 `uvicorn` で `POST /runs/yaml`→worker実行→COMPLETED を検証する（`tests/test_nats_e2e.py`）
- [x] Phase 4（v0.4）：ドキュメントを更新する（Quickstart / tutorial に YAML投入手順、pyoco 0.6.1 single-flow 前提を追記）（`docs/quickstart.md` / `docs/tutorial_multi_worker.md` / `docs/spec.md` / `docs/config.md`）
- [x] v0.4.0 の区切り：全テストを実行してグリーンを確認する（`uv run pytest`）
- [x] v0.4.0 の区切り：version を更新する（`pyproject.toml` / `README.md` / `docs/OVERVIEW.md` / `src/pyoco_server/http_api.py`）
- [ ] 最終整合チェック（docs相互リンク、UC/REQ/ERR/MSG、設定キー、実装/テストの対応）を行い、ユーザー確認で合意を取る（レビューゲート）（`docs/OVERVIEW.md` 起点）

# future
（現状スナップショット：実装/テスト/デモの所在 は `docs/OVERVIEW.md` に移動）

- Phase 4（将来）：運用I/Fの拡張
  - runs一覧の追加改善（必要なら）
    - filters: `updated_after`（最近だけ） / `cursor`（ページング） / `workflow_yaml_sha256` filter
  - 状態ストリーミング（SSE）
    - `/runs/{run_id}/watch`（KV watch backed）
  - 取消（best-effort）
    - `POST /runs/{run_id}/cancel`（flagをKVへ、workerがheartbeatで確認）
  - event stream（履歴/ログ）
    - KV肥大化回避のための append-only stream（例：`pyoco.events.>`）

- Phase 5（将来）：分離/公平性が必要になった場合の拡張（ハイブリッド）
  - tenant分離モード（namespace分割）
    - subjects: `pyoco.<tenant>.work.<tag>`
    - （必要なら）KV buckets per tenant
  - 公平性（best-effortからの段階的強化）
    - tenantごとの同時実行上限 / 優先度（追加インフラなしの範囲で）

- リリースチェックリスト（v0.x）
  - `uv run pytest` がCI/ローカルでグリーン
  - `docs/quickstart.md` が隠し前提なく通る
  - `docs/spec.md` と `docs/library_api.md` が実装と一致
    - endpoints
    - include挙動
    - 失敗ディスポジション
    - env vars

# archive
- [x] docs（concept/spec/architecture/plan/library_api/quickstart/config）を skills テンプレ寄りに整形し、相互整合を担保する
- [x] `docs/plan.md` を正本にし、ルート `plan.md` を参照互換stub化する
- [x] server/worker 共通の env 設定（`.env`運用含む）を仕様化する（`docs/spec.md` 付録I / `docs/config.md`）
- [x] ログ仕様（特にエラー時の元例外/発生箇所の記録）を仕様化する（`docs/spec.md` REQ-0013 / `docs/architecture.md`）
- [x] `NatsBackendConfig.from_env()` を実装し、server/worker が共通に env 設定を利用できるようにする（`src/pyoco_server/config.py`）
- [x] ログ設定（`PYOCO_LOG_*`）を実装し、JSON Linesで例外/発生箇所を記録できるようにする（`src/pyoco_server/logging_config.py`）
- [x] HTTP Gateway でログ設定を有効化し、エラー時に `err_id/msg_id` + `exc_info` を記録する（`src/pyoco_server/http_api.py`）
- [x] worker でエラー時ログ（`err_id/msg_id` + `exc_info`）を記録する（ログ設定は呼び出し側で有効化）（`src/pyoco_server/worker.py`）
- [x] サンプル worker 起動にログ設定を追加する（`examples/run_worker.py`）
- [x] Quickstart の手順が隠し前提なく動くことを確認する（NATS→Gateway→Worker→Submit）（`tests/test_nats_e2e.py::test_http_gateway_e2e_submit_list_and_task_status` で現物E2E）
- [x] `NatsBackendConfig.from_env()` の単体テストを追加する（`tests/test_config_from_env.py`）
- [x] `tests/test_config_from_env.py` を実行してテストする（`uv run pytest -q tests/test_config_from_env.py`）
- [x] ログフォーマッタの単体テストを追加する（例外時に `exc_type/exc_message/exc_traceback/exc_origin` が出る）（`tests/test_logging_config.py`）
- [x] `tests/test_logging_config.py` を実行してテストする（`uv run pytest -q tests/test_logging_config.py`）
- [x] 全テストを実行してグリーンであることを確認する（`uv run pytest`）
- [x] 最終整合チェック（docs相互リンク、UC/REQ/ERR/MSG、設定キー、実装の対応）を行う（`docs/OVERVIEW.md` 起点）

- [x] テスト方針を「極力現物（実 `nats-server` / 実 `uvicorn` / 実 JetStream）で検証する」に統一する（原則：E2E/統合優先、単体は補助）
- [x] E2E（現物）：JetStream consumer契約の担保を確認する（既存consumerがある場合は環境設定を尊重する方針の確認）（`tests/test_nats_e2e.py`）
- [x] E2E（現物）：失敗ディスポジションの仕様と実装の一致を検証する（invalid_job/flow_not_found/execution_error/transient NATS）（`tests/test_nats_e2e.py`）
- [x] E2E（現物）：flow not found（KeyError）が FAILED + DLQ(reason=flow_not_found) になることを追加検証する（`tests/test_nats_e2e.py`）
- [x] E2E（現物）：長時間runで in_progress ACK により再配送しないことを追加検証する（`tests/test_nats_e2e.py`）
- [x] E2E（現物）：terminal snapshot write 失敗時に NAK(delay) し、再試行できることを検証する（`tests/test_nats_e2e.py`）
- [x] E2E（現物）：`POST /runs` の原子性（KV put 後に publish 失敗）で 503 かつ KV に孤児runが残らないことを検証する（`tests/test_nats_e2e.py`）
- [x] Quickstart手順に `.env` + ログ設定例（`PYOCO_LOG_*`）を追記する（`docs/quickstart.md`）
- [x] ドキュメント整合（spec/library_api/config/overview）を最終チェックし、v0.1のリリース条件を満たす

- [x] `GET /metrics` をHTTP Gatewayに実装する（Prometheus想定、追加依存なし）（`src/pyoco_server/http_api.py`）
- [x] E2E（現物）：`GET /metrics` のテストを追加する（実 `nats-server` + 実 `uvicorn` 起動→200→期待するカウンタを含む）（`tests/test_nats_e2e.py`）
- [x] `GET /workers` をHTTP Gatewayに実装する（TTL-KVから一覧）（`src/pyoco_server/http_api.py`）
- [x] E2E（現物）：`GET /workers` のテストを追加する（実 `nats-server` + 実 `uvicorn` 起動→active worker_id と tags/heartbeat が出る）（`tests/test_nats_e2e.py`）

- [x] （記録）ルート `plan.md` の計画内容を `docs/plan.md` に統合し、`docs/` を正本として運用する
- [x] ルート `plan.md` を削除し、`docs/plan.md` のみを正本として運用する
