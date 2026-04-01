# delta-request

## Delta ID
- DR-20260401-yaml-schedule

## Delta Type
- FEATURE

## 目的
- YAML ワークフローを server 側で時刻指定または一定間隔で自動投入できるようにする。
- 既存の `/runs/yaml` 契約を流用し、YAML 検証と worker 実行経路を変えずに定期実行を追加する。

## 変更対象（In Scope）
- 対象1: YAML スケジュール定義の保存、一覧、削除 API を追加する。
- 対象2: 保存済みスケジュールを server 起動中に監視し、due 時刻で run 作成と JetStream publish を行う。
- 対象3: HTTP client / CLI からスケジュール作成と参照と削除ができるようにする。
- 対象4: 設定値と運用文書を最小限同期する。

## 非対象（Out of Scope）
- cron 式や曜日指定などの高度なスケジューリング。
- Dashboard UI への schedule 操作追加。
- schedule の pause/resume、更新 API、catch-up 複数回再実行ポリシーの高度化。
- 複数 gateway 間の厳密な分散排他保証。

## Candidate Files/Artifacts
- docs/delta/DR-20260401-yaml-schedule.md
- docs/OVERVIEW.md
- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/library_api.md
- docs/config.md
- src/pyoco_server/config.py
- src/pyoco_server/resources.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/client_cli.py
- src/pyoco_server/schedules.py
- tests/test_config_from_env.py
- tests/test_client_cli.py
- tests/test_nats_e2e.py

## 差分仕様
- DS-01:
  - Given: 利用者が `flow.yaml` と `flow_name` と tag、および `run_at` または `interval_seconds` を指定する。
  - When: `POST /schedules/yaml` を呼ぶ。
  - Then: server は YAML を検証して schedule 定義を保存し、次回実行時刻を返す。
- DS-02:
  - Given: 保存済み schedule の `next_run_at` が現在時刻以下である。
  - When: server の scheduler loop が due schedule を処理する。
  - Then: 既存 YAML run と同等の snapshot と job payload で run が 1 件作成され、schedule は次回時刻または完了状態へ更新される。
- DS-03:
  - Given: 利用者が schedule 一覧または削除を要求する。
  - When: `GET /schedules` または `DELETE /schedules/{schedule_id}` を呼ぶ。
  - Then: 保存済み schedule の状態を参照でき、削除後は新しい dispatch 対象から外れる。

## 受入条件（Acceptance Criteria）
- AC-01: `POST /schedules/yaml` で one-shot (`run_at`) と interval (`interval_seconds` + 任意 `start_at`) を作成でき、レスポンスに `schedule_id` と `next_run_at` が含まれる。
- AC-02: one-shot schedule は指定時刻到達後に 1 回だけ YAML run を生成し、schedule 状態は `COMPLETED` になる。
- AC-03: interval schedule は一定間隔ごとに YAML run を継続生成し、削除後は新しい run を生成しない。
- AC-04: `pyoco-client` から schedule 作成・一覧・削除を操作できる。

## Verify Profile
- static check: Not Required
- targeted unit: Required
- targeted integration / E2E: Required
- delta-project-validator: Not Required

## Canonical Sync Mode
- mode: direct canonical update
- reason: 新規 API / 設定 / 運用導線を追加するため、実装と同時に正本 docs を同期する。

## 制約
- 制約1: YAML 検証、サイズ上限、`flow.defaults` を params 正本とする方針は `/runs/yaml` と一致させる。
- 制約2: 変更は schedule feature に閉じ、既存 run/bundle/wheel/cancel 契約は変更しない。

## Review Gate
- required: Yes
- reason: HTTP API、永続化、起動時バックグラウンド処理、CLI、docs を横断するため。

## Review Focus（REVIEW または review gate required の場合）
- checklist: `docs/delta/REVIEW_CHECKLIST.md`
- target area: schedule dispatch の重複防止、既存 YAML run との契約一致、長大ファイル悪化の抑制

## 未確定事項
- なし（interval の初回実行は `start_at` 指定時はその時刻、未指定時は `created_at + interval_seconds` とした）

# delta-apply

## Delta ID
- DR-20260401-yaml-schedule

## Delta Type
- FEATURE

## 実行ステータス
- APPLIED

## 確認済み Candidate Files/Artifacts
- docs/delta/DR-20260401-yaml-schedule.md
- docs/OVERVIEW.md
- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/library_api.md
- docs/config.md
- src/pyoco_server/config.py
- src/pyoco_server/resources.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/client_cli.py
- src/pyoco_server/schedules.py
- tests/test_config_from_env.py
- tests/test_client_cli.py
- tests/test_nats_e2e.py

## 変更ファイル/成果物
- docs/delta/DR-20260401-yaml-schedule.md
- docs/OVERVIEW.md
- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/library_api.md
- docs/config.md
- src/pyoco_server/config.py
- src/pyoco_server/resources.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/client_cli.py
- src/pyoco_server/schedules.py
- tests/test_config_from_env.py
- tests/test_client_cli.py
- tests/test_nats_e2e.py

## 適用内容（AC対応）
- AC-01:
  - 変更:
    - `POST /schedules/yaml` を追加し、one-shot (`run_at`) / interval (`interval_seconds` + 任意 `start_at`) の作成を実装した。
    - schedule record の正規化と初回 `next_run_at` 算出を `src/pyoco_server/schedules.py` に追加した。
  - 根拠:
    - `src/pyoco_server/http_api.py`
    - `src/pyoco_server/schedules.py`
    - `src/pyoco_server/config.py`
    - `src/pyoco_server/resources.py`
- AC-02:
  - 変更:
    - server 起動時に YAML schedule loop を開始し、due な one-shot schedule を run 化後 `COMPLETED` に更新する実装を追加した。
  - 根拠:
    - `src/pyoco_server/http_api.py`
    - `src/pyoco_server/schedules.py`
    - `tests/test_nats_e2e.py`
- AC-03:
  - 変更:
    - interval schedule の `next_run_at` 更新、lease による重複抑止、`DELETE /schedules/{schedule_id}` による停止を追加した。
  - 根拠:
    - `src/pyoco_server/http_api.py`
    - `src/pyoco_server/schedules.py`
    - `tests/test_nats_e2e.py`
- AC-04:
  - 変更:
    - `PyocoHttpClient` に schedule create/list/delete を追加し、`pyoco-client schedule-yaml/schedules/schedule-delete` を追加した。
  - 根拠:
    - `src/pyoco_server/http_client.py`
    - `src/pyoco_server/client_cli.py`
    - `tests/test_client_cli.py`

## 非対象維持の確認
- Out of Scope への変更なし: Yes
- もし No の場合の理由:
  - なし

## Canonical Sync
- mode:
  - direct canonical update
- action:
  - `OVERVIEW/spec/architecture/library_api/config/plan` を実装と同時に同期した。
- status:
  - DONE

## コード分割健全性
- 500行超のファイルあり: Yes
- 800行超のファイルあり: Yes
- 1000行超のファイルあり: Yes
- 長大な関数なし: Yes
- 責務過多のモジュールなし: Yes

## verify 依頼メモ
- request profile:
  - static check:
    - Required
  - targeted unit:
    - Required
  - targeted integration / E2E:
    - Required
  - delta-project-validator:
    - Not Required
- 検証してほしい観点:
  - schedule create/list/delete の契約
  - one-shot / interval dispatch の実挙動
  - `/runs/yaml` 代表経路の非破壊性
- review evidence:
  - `python -m compileall src tests`
  - `uv run pytest -q tests/test_config_from_env.py tests/test_client_cli.py`
  - `uv run pytest -q tests/test_nats_e2e.py -k "submit_yaml_and_run or schedule_yaml"`

# delta-verify

## Delta ID
- DR-20260401-yaml-schedule

## Requested Verify Profile
- static check:
  - Required
- targeted unit:
  - Required
- targeted integration / E2E:
  - Required
- delta-project-validator:
  - Not Required

## Executed Verify
- static check:
  - `python -m compileall src tests`
- targeted unit:
  - `uv run pytest -q tests/test_config_from_env.py tests/test_client_cli.py`
- targeted integration / E2E:
  - `uv run pytest -q tests/test_nats_e2e.py -k "submit_yaml_and_run or schedule_yaml"`
- delta-project-validator:
  - Not executed（request 通り）

## 検証結果（AC単位）
| AC | 結果(PASS/FAIL) | 根拠 |
|---|---|---|
| AC-01 | PASS | schedule create API と record 計算を実装し、config/CLI/E2E で作成成功を確認した。 |
| AC-02 | PASS | one-shot E2E で due 後に 1 回だけ run が生成され、schedule が `COMPLETED` へ遷移することを確認した。 |
| AC-03 | PASS | interval E2E で 2 回の run 生成と delete 後の停止を確認した。 |
| AC-04 | PASS | `pyoco-client` の schedule create/list/delete コマンドを CLI テストで確認した。 |

## スコープ逸脱チェック
- Out of Scope 変更の有無: No
- 逸脱内容:
  - なし

## Canonical Sync Check
- mode:
  - direct canonical update
- status:
  - docs 同期済み
- result:
  - PASS

## 不整合/回帰リスク
- R-01:
  - `src/pyoco_server/http_api.py`、`tests/test_nats_e2e.py`、`src/pyoco_server/client_cli.py` は既存から review threshold 超過の大型ファイルであり、今回も例外対象のまま。
- R-02:
  - verify は targeted test のみで、`uv run pytest` 全量は未実行。

## Review Gate
- required: Yes
- checklist: `docs/delta/REVIEW_CHECKLIST.md`
- layer integrity: PASS
- docs sync: PASS
- data size: PASS
- code split health: PASS
- file-size threshold: PASS

## Review Delta Outcome
- pass: Yes
- follow-up delta seeds:
  - schedule UI 導線や cron/曜日指定が必要になった場合は別 delta に分離する。
  - `http_api.py` / `tests/test_nats_e2e.py` など既存巨大ファイルの是正は別 delta 候補。

## 参考所見（合否外）
- O-01:
  - schedule の分散排他は lease による best-effort であり、複数 gateway 間の厳密保証は out of scope のままとした。

## 判定
- Overall: PASS

## FAIL時の最小修正指示
- なし

# delta-archive

## Delta ID
- DR-20260401-yaml-schedule

## クローズ判定
- verify結果: PASS
- review gate: PASSED
- canonical sync mode: direct canonical update
- canonical sync status: DONE
- archive可否: 可

## 確定内容
- 目的:
  - YAML ワークフローを one-shot / interval で自動投入できる最小 schedule 機能を追加する。
- 変更対象:
  - YAML schedule API、server dispatch loop、schedule KV、HTTP client / CLI、設定、docs、対象テスト。
- 非対象:
  - cron/曜日指定、Dashboard UI、pause/resume/update API、複数 gateway 間の厳密排他。
- Candidate Files/Artifacts:
  - docs/delta/DR-20260401-yaml-schedule.md
  - docs/OVERVIEW.md
  - docs/plan.md
  - docs/spec.md
  - docs/architecture.md
  - docs/library_api.md
  - docs/config.md
  - src/pyoco_server/config.py
  - src/pyoco_server/resources.py
  - src/pyoco_server/http_api.py
  - src/pyoco_server/http_client.py
  - src/pyoco_server/client_cli.py
  - src/pyoco_server/schedules.py
  - tests/test_config_from_env.py
  - tests/test_client_cli.py
  - tests/test_nats_e2e.py

## 実装記録
- 変更ファイル/成果物:
  - `docs/delta/DR-20260401-yaml-schedule.md`
  - `docs/OVERVIEW.md`
  - `docs/plan.md`
  - `docs/spec.md`
  - `docs/architecture.md`
  - `docs/library_api.md`
  - `docs/config.md`
  - `src/pyoco_server/config.py`
  - `src/pyoco_server/resources.py`
  - `src/pyoco_server/http_api.py`
  - `src/pyoco_server/http_client.py`
  - `src/pyoco_server/client_cli.py`
  - `src/pyoco_server/schedules.py`
  - `tests/test_config_from_env.py`
  - `tests/test_client_cli.py`
  - `tests/test_nats_e2e.py`
- AC達成状況:
  - AC-01: 達成
  - AC-02: 達成
  - AC-03: 達成
  - AC-04: 達成

## 検証記録
- verify要約:
  - compileall、config/CLI の targeted unit、schedule E2E を実施し Overall PASS。
- 主要な根拠:
  - `python -m compileall src tests`
  - `uv run pytest -q tests/test_config_from_env.py tests/test_client_cli.py`
  - `uv run pytest -q tests/test_nats_e2e.py -k "submit_yaml_and_run or schedule_yaml"`

## Canonical Sync
- target:
  - `docs/OVERVIEW.md`
  - `docs/plan.md`
  - `docs/spec.md`
  - `docs/architecture.md`
  - `docs/library_api.md`
  - `docs/config.md`
- action:
  - YAML schedule API / runtime / config / CLI を docs 正本へ反映した。
- reason:
  - direct canonical update 指定のため。

## 未解決事項
- あり
  - `src/pyoco_server/http_api.py`、`tests/test_nats_e2e.py`、`src/pyoco_server/client_cli.py`、`tests/test_client_cli.py` は既存から大型ファイルで、引き続き分割候補。
  - `uv run pytest` の全量実行は未実施。

## 次のdeltaへの引き継ぎ（任意）
- Seed-01:
  - cron/曜日指定や pause/resume が必要なら schedule 拡張 delta を切る。
- Seed-02:
  - 巨大ファイル分割（`http_api.py` / `tests/test_nats_e2e.py` / `client_cli.py`）を別 delta で実施する。
