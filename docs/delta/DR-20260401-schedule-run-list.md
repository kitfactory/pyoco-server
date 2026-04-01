# delta-request

## Delta ID
- DR-20260401-schedule-run-list

## Delta Type
- FEATURE

## 目的
- 繰り返し実行される YAML schedule ごとの run 結果一覧をまとめて取得できるようにする。
- 既存 run 契約を維持しつつ、schedule 由来 run に `schedule_id` を刻んで参照可能にする。

## 変更対象（In Scope）
- 対象1: schedule 由来 run の snapshot / job metadata に `schedule_id` を保存する。
- 対象2: `GET /schedules/{schedule_id}/runs` を追加し、schedule 単位で run 一覧を返す。
- 対象3: HTTP client / CLI に schedule run 一覧取得を追加する。
- 対象4: 最小限の docs / delta / plan を同期する。

## 非対象（Out of Scope）
- 実行結果の集計サマリ保存。
- schedule ごとの専用インデックスや別 KV/Stream の追加。
- Dashboard UI への schedule run 一覧追加。
- run 一覧 API 全体の再設計。

## Candidate Files/Artifacts
- docs/delta/DR-20260401-schedule-run-list.md
- docs/OVERVIEW.md
- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/library_api.md
- src/pyoco_server/models.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/client_cli.py
- src/pyoco_server/worker.py
- tests/test_client_cli.py
- tests/test_nats_e2e.py

## 差分仕様
- DS-01:
  - Given: schedule loop から run が起動される。
  - When: server が run 初期 snapshot と job payload を作る。
  - Then: run に `schedule_id` が保存される。
- DS-02:
  - Given: 利用者が schedule_id を指定する。
  - When: `GET /schedules/{schedule_id}/runs` を呼ぶ。
  - Then: その schedule 由来 run の一覧を newest-first で返す。
- DS-03:
  - Given: CLI/HTTP client 利用者が schedule run 一覧を見たい。
  - When: client / CLI を呼ぶ。
  - Then: server の schedule run 一覧 API をそのまま利用できる。

## 受入条件（Acceptance Criteria）
- AC-01: schedule 由来 run の `GET /runs/{run_id}` に `schedule_id` が含まれる。
- AC-02: `GET /schedules/{schedule_id}/runs` で当該 schedule の run だけを複数件取得できる。
- AC-03: `pyoco-client schedule-runs --schedule-id ...` で同一覧を取得できる。

## Verify Profile
- static check: Required
- targeted unit: Required
- targeted integration / E2E: Required
- delta-project-validator: Not Required

## Canonical Sync Mode
- mode: direct canonical update
- reason: 新規 API と公開利用導線を追加するため。

## 制約
- 制約1: schedule run 一覧は既存 run snapshot の走査ベースで実装し、専用ストレージは追加しない。
- 制約2: non-schedule run の契約は変更しない。

## Review Gate
- required: Yes
- reason: HTTP API / metadata / CLI / docs を横断するため。

## Review Focus（REVIEW または review gate required の場合）
- checklist: `docs/delta/REVIEW_CHECKLIST.md`
- target area: schedule_id 伝播漏れ、tenant 境界、既存 run 一覧との非干渉

## 未確定事項
- なし

# delta-apply

## Delta ID
- DR-20260401-schedule-run-list

## Delta Type
- FEATURE

## 実行ステータス
- APPLIED

## 確認済み Candidate Files/Artifacts
- docs/delta/DR-20260401-schedule-run-list.md
- docs/OVERVIEW.md
- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/library_api.md
- src/pyoco_server/models.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/client_cli.py
- src/pyoco_server/worker.py
- tests/test_client_cli.py
- tests/test_nats_e2e.py

## 変更ファイル/成果物
- docs/delta/DR-20260401-schedule-run-list.md
- docs/OVERVIEW.md
- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/library_api.md
- src/pyoco_server/models.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/client_cli.py
- src/pyoco_server/worker.py
- tests/test_client_cli.py
- tests/test_nats_e2e.py

## 適用内容（AC対応）
- AC-01:
  - 変更:
    - schedule dispatch で生成する run snapshot / job payload に `schedule_id` を保存し、worker 側で run metadata に引き継ぐようにした。
  - 根拠:
    - `src/pyoco_server/http_api.py`
    - `src/pyoco_server/models.py`
    - `src/pyoco_server/worker.py`
- AC-02:
  - 変更:
    - `GET /schedules/{schedule_id}/runs` を追加し、既存 run snapshot 走査から schedule 単位で newest-first の一覧を返すようにした。
  - 根拠:
    - `src/pyoco_server/http_api.py`
    - `tests/test_nats_e2e.py`
- AC-03:
  - 変更:
    - `PyocoHttpClient.list_schedule_runs()` と `pyoco-client schedule-runs` を追加した。
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
  - `OVERVIEW/spec/architecture/library_api/plan` に schedule run 一覧 API を反映した。
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
  - `schedule_id` 伝播
  - schedule 単位 run 一覧 API / CLI
  - 既存 schedule 実行の非破壊性
- review evidence:
  - `python -m compileall src tests`
  - `uv run pytest -q tests/test_client_cli.py -k "schedule"`
  - `uv run pytest -q tests/test_nats_e2e.py -k "schedule_yaml"`

# delta-verify

## Delta ID
- DR-20260401-schedule-run-list

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
  - `uv run pytest -q tests/test_client_cli.py -k "schedule"`
- targeted integration / E2E:
  - `uv run pytest -q tests/test_nats_e2e.py -k "schedule_yaml"`
- delta-project-validator:
  - Not executed（request 通り）

## 検証結果（AC単位）
| AC | 結果(PASS/FAIL) | 根拠 |
|---|---|---|
| AC-01 | PASS | one-shot schedule E2E で `GET /runs/{run_id}` に `schedule_id` が含まれることを確認した。 |
| AC-02 | PASS | interval schedule E2E で `GET /schedules/{schedule_id}/runs` から 2 件の run を newest-first で取得できることを確認した。 |
| AC-03 | PASS | CLI テストで `schedule-runs` が HTTP client 呼び出しへ正しく変換されることを確認した。 |

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
  - `src/pyoco_server/http_api.py`、`tests/test_nats_e2e.py`、`src/pyoco_server/client_cli.py`、`tests/test_client_cli.py` は既存から大型ファイルのまま。
- R-02:
  - targeted test のみ実行しており、`uv run pytest` 全量は未実行。

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
  - schedule run 集計サマリや永続インデックスが必要なら別 delta で追加する。
  - 巨大ファイル分割は別 delta 候補。

## 参考所見（合否外）
- O-01:
  - schedule run 一覧は既存 run snapshot 走査なので、件数が増えると検索コストは `GET /runs` と同じ傾向になる。

## 判定
- Overall: PASS

## FAIL時の最小修正指示
- なし

# delta-archive

## Delta ID
- DR-20260401-schedule-run-list

## クローズ判定
- verify結果: PASS
- review gate: PASSED
- canonical sync mode: direct canonical update
- canonical sync status: DONE
- archive可否: 可

## 確定内容
- 目的:
  - 繰り返し実行される YAML schedule ごとの run 結果一覧をまとめて取得できるようにする。
- 変更対象:
  - run metadata の `schedule_id`、schedule run 一覧 API、HTTP client / CLI、docs、対象テスト。
- 非対象:
  - 集計サマリ保存、専用インデックス、Dashboard UI、run 一覧 API 全体の再設計。
- Candidate Files/Artifacts:
  - docs/delta/DR-20260401-schedule-run-list.md
  - docs/OVERVIEW.md
  - docs/plan.md
  - docs/spec.md
  - docs/architecture.md
  - docs/library_api.md
  - src/pyoco_server/models.py
  - src/pyoco_server/http_api.py
  - src/pyoco_server/http_client.py
  - src/pyoco_server/client_cli.py
  - src/pyoco_server/worker.py
  - tests/test_client_cli.py
  - tests/test_nats_e2e.py

## 実装記録
- 変更ファイル/成果物:
  - `docs/delta/DR-20260401-schedule-run-list.md`
  - `docs/OVERVIEW.md`
  - `docs/plan.md`
  - `docs/spec.md`
  - `docs/architecture.md`
  - `docs/library_api.md`
  - `src/pyoco_server/models.py`
  - `src/pyoco_server/http_api.py`
  - `src/pyoco_server/http_client.py`
  - `src/pyoco_server/client_cli.py`
  - `src/pyoco_server/worker.py`
  - `tests/test_client_cli.py`
  - `tests/test_nats_e2e.py`
- AC達成状況:
  - AC-01: 達成
  - AC-02: 達成
  - AC-03: 達成

## 検証記録
- verify要約:
  - compileall、CLI targeted test、schedule E2E を実施し Overall PASS。
- 主要な根拠:
  - `python -m compileall src tests`
  - `uv run pytest -q tests/test_client_cli.py -k "schedule"`
  - `uv run pytest -q tests/test_nats_e2e.py -k "schedule_yaml"`

## Canonical Sync
- target:
  - `docs/OVERVIEW.md`
  - `docs/plan.md`
  - `docs/spec.md`
  - `docs/architecture.md`
  - `docs/library_api.md`
- action:
  - schedule run 一覧取得 API / CLI と `schedule_id` metadata を docs 正本へ反映した。
- reason:
  - direct canonical update 指定のため。

## 未解決事項
- あり
  - `src/pyoco_server/http_api.py`、`tests/test_nats_e2e.py`、`src/pyoco_server/client_cli.py`、`tests/test_client_cli.py` は既存から大型ファイルのまま。
  - `uv run pytest` の全量実行は未実施。

## 次のdeltaへの引き継ぎ（任意）
- Seed-01:
  - schedule 単位の集計サマリや保管戦略が必要なら別 delta で追加する。
- Seed-02:
  - 巨大ファイル分割を別 delta で進める。
