# plan.md（必ず書く：最新版）

# current
- [x] 追加要望対応：wheelアップロード時に複数タグを保持し、workerタグ一致時のみ同期する仕様を反映する（`src/pyoco_server/http_api.py` / `src/pyoco_server/worker.py` / `src/pyoco_server/client_cli.py`）
- [x] 現状確認：workerの依存配布運用を調査し、wheelレジストリ（server管理 + worker同期）の実装方針を確定する（`src/pyoco_server/http_api.py` / `src/pyoco_server/worker.py` / `src/pyoco_server/resources.py`）
- [x] 実装1（リソース/設定）：JetStream Object Store を wheel レジストリとして追加し、env/CLI設定を拡張する（`src/pyoco_server/config.py` / `src/pyoco_server/resources.py` / `src/pyoco_server/worker_cli.py`）
- [x] 実装2（HTTP/CLI）：`/wheels` API（list/upload/download/delete）と `pyoco-client` の wheel 管理コマンドを追加する（`src/pyoco_server/http_api.py` / `src/pyoco_server/http_client.py` / `src/pyoco_server/client_cli.py`）
- [x] 実装3（worker）：wheel同期（差分検知・ローカル保存・差分インストール）を追加する（`src/pyoco_server/worker.py`）
- [x] テスト：config/CLI/wheel registry/worker同期のテストを追加し、全テストを実行してグリーンを確認する（`tests/test_config_from_env.py` / `tests/test_wheel_registry.py` / `uv run pytest -q`）
- [x] 文書化：OVERVIEW/config に wheel レジストリ運用を反映する（`docs/OVERVIEW.md` / `docs/config.md`）
- [x] 文書化（全面更新）：wheelタグ付き配布仕様を concept/spec/architecture/library_api/quickstart/tutorial/README に反映する（`docs/concept.md` / `docs/spec.md` / `docs/architecture.md` / `docs/library_api.md` / `docs/quickstart.md` / `docs/tutorial_multi_worker.md` / `README.md`）
- [x] 追加要望対応：wheel配布履歴（upload/delete）とアップロード元情報（source/actor）を記録・参照できるようにする（`src/pyoco_server/http_api.py` / `src/pyoco_server/resources.py` / `src/pyoco_server/http_client.py` / `src/pyoco_server/client_cli.py`）
- [x] 追加要望対応：wheel配布ポリシーを「同一パッケージは必ずバージョンアップ」に固定し、同一/過去バージョンを409で拒否する。workerはタグ一致候補の最新版のみ同期する（`src/pyoco_server/http_api.py` / `src/pyoco_server/worker.py` / `tests/test_wheel_registry.py` / `docs/spec.md`）
- [x] 追加要望対応：worker側でwheel互換性（Python/ABI/Platformタグ）を判定し、互換外をskipする。同期結果を `wheel_sync` として worker registry / `GET /workers` で可視化する（`src/pyoco_server/worker.py` / `tests/test_wheel_registry.py` / `docs/spec.md` / `docs/architecture.md`）
- [x] 現状確認：pyoco 0.6.2 の cancel API（`Engine.cancel(run_id)`）と現行 server/worker の実装差分を確認し、cancel導入方針を固定する（`src/pyoco_server/worker.py` / `src/pyoco_server/http_api.py`）
- [x] 文書化1（concept/spec/architecture）：cancel（`POST /runs/{run_id}/cancel`、`CANCELLING -> CANCELLED`、best-effort、`PYOCO_CANCEL_GRACE_PERIOD_SEC`）を反映する（`docs/concept.md` / `docs/spec.md` / `docs/architecture.md`）
- [x] 実装1（HTTP）：`POST /runs/{run_id}/cancel` を追加し、非terminal run を `CANCELLING` へ遷移させる（`src/pyoco_server/http_api.py`）
- [x] テスト1（HTTP）：cancel API の正常系/冪等/不存在/認証系を検証する（`tests/test_nats_e2e.py`）
- [x] 実装2（worker）：cancel要求の検知と `Engine.cancel(run_id)` 連携を実装し、`CANCELLED` terminal 化を追加する（`src/pyoco_server/worker.py` / `src/pyoco_server/models.py`）
- [x] テスト2（worker）：`RUNNING -> CANCELLING -> CANCELLED` と cancel timeout（best-effort）を検証する（`tests/test_nats_e2e.py`）
- [x] 実装3（client/CLI）：`PyocoHttpClient.cancel_run()` と `pyoco-client cancel --run-id ... [--wait --timeout-sec]` を追加する（`src/pyoco_server/http_client.py` / `src/pyoco_server/client_cli.py`）
- [x] テスト3（client/CLI）：cancelサブコマンドの入力/終了コード/待機動作を検証する（`tests/test_client_cli.py`）
- [x] 実装4（Dashboard）：Run一覧/詳細に cancel 操作と `CANCELLING` 表示を追加する（`src/pyoco_server/static/index.html` / `src/pyoco_server/static/app.js` / `src/pyoco_server/static/styles.css`）
- [x] テスト4（Dashboard E2E）：実行中runのcancel操作と状態遷移表示を検証する（`tests/test_dashboard_playwright_e2e.py`）
- [x] 実装5（運用文書）：README/quickstart/tutorial/library_api/config を cancel導線に更新する（`README.md` / `docs/quickstart.md` / `docs/tutorial_multi_worker.md` / `docs/library_api.md` / `docs/config.md`）
- [x] テスト5（総合E2E）：cancelを含む代表シナリオでE2Eを実行する（`uv run pytest -q tests/test_nats_e2e.py -k cancel`、`uv run pytest -q tests/test_dashboard_playwright_e2e.py -k cancel`、`uv run pytest -q`）
- [x] スクリーン・スナップショット作成：cancel操作前後（RUNNING/CANCELLING/CANCELLED）の画面を撮影し成果物化する（例：`/tmp/*.png` と `/mnt/c/Users/kitad/`）
- [x] 最終確認：docs実装整合（concept/spec/architecture/quickstart）とレビューゲート（ユーザー合意）を実施する

# future
（現状スナップショット：実装/テスト/デモの所在 は `docs/OVERVIEW.md` に移動）

- Phase 4（将来）：運用I/Fの追加改善
  - runs一覧の追加改善（必要なら）
    - sort指定 / 継続ページングの安定化（KV scan前提での best-effort 改善）
  - 状態ストリーミング（SSE）の追加改善
    - `Last-Event-ID` / replay window / backpressure 対応
  - 取消（高度化）
    - cancel reason / requested_by の可視化、`--wait` 収束戦略の改善、timeout後の運用導線整備
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
