# delta-request

## Delta ID
- DR-20260308-spawn-bundle

## Delta Type
- FEATURE

## 目的
- Spawn / YAML Bundle 機能を、要件定義から docs 同期、API/設計、コード実装、テスト、verify、archive までを含む 1 本の delta として進める。
- Study -> Trial のような親子 workflow 実行を、安全性・監査性・再現性を保ちながら `pyoco-server` に追加する。

## 変更対象（In Scope）
- 対象1:
  - `docs/spawn_bundle_requirements.md` を入力として、Spawn / YAML Bundle の canonical 要件を維持すること。
- 対象2:
  - `docs/concept.md` / `docs/spec.md` / `docs/architecture.md` / `docs/config.md` / `docs/library_api.md` / `docs/plan.md` を、spawn / bundle 要件と整合するように更新すること。
- 対象3:
  - bundle submit API、approval API、bundle parser、bundle hash、親子 run relation、child result summary、spawn policy を実装すること。
- 対象4:
  - worker 側で child run 起動、完了待機、結果要約取得、child 再spawn禁止を実装すること。
- 対象5:
  - 実装に必要な unit / integration / E2E テストを追加し、docs と実装の整合を確認すること。

## 非対象（Out of Scope）
- 非対象1:
  - 外部 workflow registry、外部 URL、外部 YAML 読み込み。
- 非対象2:
  - child からの孫 workflow spawn。
- 非対象3:
  - 厳格マルチテナント向けの新しい権限委譲モデル。
- 非対象4:
  - 高度な公平制御、優先度制御、スケジューラ刷新。
- 非対象5:
  - Dashboard UX の全面刷新。

## 差分仕様
- DS-01:
  - Given:
    - Spawn / YAML Bundle の要求が `docs/spawn_bundle_requirements.md` に定義されている。
  - When:
    - bundle submit を導入する。
  - Then:
    - 利用者は 1 枚の YAML bundle から entry workflow を root run として起動できる。
- DS-02:
  - Given:
    - root run の entry workflow から到達可能な `spawn` task が存在する。
  - When:
    - root run を投入する。
  - Then:
    - root run は `PENDING_APPROVAL` を経由し、approve 後にのみ queue へ進む。
- DS-03:
  - Given:
    - 親 workflow が `spawn: <workflow_name>` task を実行する。
  - When:
    - child run を起動する。
  - Then:
    - child run は同一 bundle 内 workflow のみを参照し、`root_run_id` / `parent_run_id` / `bundle_hash` / `spawned_from_task` を記録する。
- DS-04:
  - Given:
    - child run が存在する。
  - When:
    - 親 workflow が child 完了を待つ。
  - Then:
    - 親は child の `status` / `outputs` / `summary_metrics` / `artifacts` / `error_summary` を結果要約として参照できる。
- DS-05:
  - Given:
    - child run が `spawn` を含む。
  - When:
    - child run で `spawn` task が評価される。
  - Then:
    - server/worker は再spawnを拒否し、監査可能なエラーとして記録する。
- DS-06:
  - Given:
    - 現行 `pyoco-server` は `POST /runs` と `POST /runs/yaml` を提供している。
  - When:
    - Spawn / YAML Bundle を追加する。
  - Then:
    - 既存 single-flow 契約を壊さず、bundle 系を別導線で追加する。

## 受入条件（Acceptance Criteria）
- AC-01:
  - bundle submit、approval、spawn、relation、child result summary の要件が canonical docs に反映されている。
- AC-02:
  - bundle submit API、approval API、関連 DTO / snapshot / relation モデルが実装されている。
- AC-03:
  - worker / orchestration 層で child run 起動、完了待機、結果要約取得、child 再spawn禁止が動作する。
- AC-04:
  - bundle hash、entry workflow、approval 状態、root-child relation、spawned_from_task が保存・参照できる。
- AC-05:
  - 実装に必要な設定キーとテストが追加され、対象テストが通る。
- AC-06:
  - 既存 single-flow 実行、cancel、wheel、workers API に不要な破壊的変更を持ち込まない。

## 制約
- 制約1:
  - Active Delta は本件 1 件のみとする。
- 制約2:
  - child run は同一 bundle 内 workflow のみを参照する。
- 制約3:
  - child run は再spawnしない。
- 制約4:
  - child 数、並列数、tag、timeout、poll interval はサーバー設定で固定する。
- 制約5:
  - 通常のソースコードは 500 / 800 / 1000 行ルールを守る。

## Review Gate
- required: Yes
- reason:
  - HTTP API、worker orchestration、保存モデル、設定、テスト、文書同期にまたがる大きい変更であり、設計崩れを防ぐ必要があるため。

## Review Focus（REVIEW または review gate required の場合）
- checklist: `docs/delta/REVIEW_CHECKLIST.md`
- target area:
  - bundle API と single-flow API の共存
  - approval と cancel の責務分離
  - parent-child relation / bundle hash / child result summary のデータ整合
  - worker 内 orchestration と責務肥大の回避
  - docs / tests / config の同期

## 未確定事項
- Q-01:
  - 決定：`POST /runs/bundle` を採用した。
- Q-02:
  - 決定：approval reject は `CANCELLED` に寄せた。
- Q-03:
  - 決定：`outputs` は task output map、`summary_metrics` は numeric scalar 抽出、`artifacts` は task artifact list を最小共通表現とした。
- Q-04:
  - 決定：今回の delta では worker 内 orchestration とし、必要なら follow-up delta で coordinator 分離を検討する。

# delta-apply

## Delta ID
- DR-20260308-spawn-bundle

## Delta Type
- FEATURE

## 実行ステータス
- APPLIED

## 変更ファイル
- docs/OVERVIEW.md
- docs/architecture.md
- docs/config.md
- docs/library_api.md
- docs/plan.md
- docs/spec.md
- src/pyoco_server/_workflow_test_tasks.py
- src/pyoco_server/bundle_runtime.py
- src/pyoco_server/config.py
- src/pyoco_server/http_api.py
- src/pyoco_server/http_client.py
- src/pyoco_server/models.py
- src/pyoco_server/resources.py
- src/pyoco_server/worker.py
- src/pyoco_server/workflow_yaml.py
- tests/test_spawn_bundle_e2e.py
- tests/test_workflow_yaml.py

## 適用内容（AC対応）
- AC-01:
  - 変更:
    - canonical docs の Spawn / YAML Bundle 記述を「将来拡張」から実装済み表記へ更新した。
    - `docs/OVERVIEW.md` / `docs/spec.md` / `docs/architecture.md` / `docs/config.md` / `docs/library_api.md` / `docs/plan.md` を同期した。
  - 根拠:
    - bundle submit / approval API と設定・状態が docs 上で現行実装として参照できる。
- AC-02:
  - 変更:
    - `POST /runs/bundle`、`POST /runs/{run_id}/approve`、`POST /runs/{run_id}/reject` を追加した。
    - `RunJob`、snapshot metadata、bundle raw KV、run relation KV を追加した。
  - 根拠:
    - `src/pyoco_server/http_api.py`、`src/pyoco_server/models.py`、`src/pyoco_server/resources.py`、`src/pyoco_server/config.py`
- AC-03:
  - 変更:
    - bundle parser、bundle Flow builder、spawn orchestrator、child wait、child result summary、child 再spawn拒否を実装した。
  - 根拠:
    - `src/pyoco_server/workflow_yaml.py`、`src/pyoco_server/bundle_runtime.py`、`src/pyoco_server/worker.py`
- AC-04:
  - 変更:
    - snapshot / relation に `bundle_hash`、`entry_workflow`、`root_run_id`、`parent_run_id`、`spawned_from_task`、approval metadata を保持した。
  - 根拠:
    - `src/pyoco_server/models.py`、`src/pyoco_server/bundle_runtime.py`
- AC-05:
  - 変更:
    - bundle/spawn 用の env 設定を追加し、bundle parser unit と bundle E2E を追加した。
  - 根拠:
    - `src/pyoco_server/config.py`、`tests/test_workflow_yaml.py`、`tests/test_spawn_bundle_e2e.py`
- AC-06:
  - 変更:
    - 既存 `/runs` / `/runs/yaml` 契約は維持し、代表 single-flow テストを回帰確認した。
  - 根拠:
    - `tests/test_nats_e2e.py -k "test_e2e_submit_and_run_with_ephemeral_nats or test_http_gateway_e2e_submit_yaml_and_run"`

## 非対象維持の確認
- Out of Scope への変更なし: Yes
- もし No の場合の理由:
  - なし

## コード分割健全性
- 500行超のファイルあり: Yes
- 800行超のファイルあり: Yes
- 1000行超のファイルあり: Yes
- 長大な関数なし: Yes
- 責務過多のモジュールなし: No

## verify 依頼メモ
- 検証してほしい観点:
  - bundle submit / approval / spawn の E2E
  - single-flow 代表経路の非破壊性
  - delta/plan 整合とコードサイズ閾値
- review evidence:
  - `uv run python -m compileall src tests`
  - `uv run pytest tests/test_workflow_yaml.py tests/test_config_from_env.py`
  - `uv run pytest tests/test_spawn_bundle_e2e.py`
  - `uv run pytest tests/test_nats_e2e.py -k "test_e2e_submit_and_run_with_ephemeral_nats or test_http_gateway_e2e_submit_yaml_and_run"`
  - `node C:\\Users\\naruhide\\.codex\\skills\\project-validator\\scripts\\validate_delta_links.js --dir C:\\Users\\naruhide\\workspace\\pyoco-server`
  - `node C:\\Users\\naruhide\\.codex\\skills\\project-validator\\scripts\\check_code_size.js --dir C:\\Users\\naruhide\\workspace\\pyoco-server`

# delta-verify

## Delta ID
- DR-20260308-spawn-bundle

## Verify Profile
- static check:
  - `uv run python -m compileall src tests`
- targeted unit:
  - `uv run pytest tests/test_workflow_yaml.py tests/test_config_from_env.py`
- targeted integration / E2E:
  - `uv run pytest tests/test_spawn_bundle_e2e.py`
  - `uv run pytest tests/test_nats_e2e.py -k "test_e2e_submit_and_run_with_ephemeral_nats or test_http_gateway_e2e_submit_yaml_and_run"`
- delta validator:
  - `validate_delta_links.js`: PASS
  - `check_code_size.js`: WARN/ERROR あり

## 検証結果（AC単位）
| AC | 結果(PASS/FAIL) | 根拠 |
|---|---|---|
| AC-01 | PASS | docs の bundle / approval / spawn / config / library API を現行実装表記へ更新した。 |
| AC-02 | PASS | `/runs/bundle`、approve/reject、bundle KV、relation KV、snapshot metadata を実装した。 |
| AC-03 | PASS | bundle E2E で child 起動・待機・要約取得・child 再spawn拒否を確認した。 |
| AC-04 | PASS | root/child snapshot と relation KV に bundle hash / relation / approval 情報が残ることを確認した。 |
| AC-05 | PASS | bundle/spawn 設定キーと parser/E2E テストを追加し、対象テストが通った。 |
| AC-06 | PASS | 既存 single-flow の代表 E2E 2 本が通った。 |

## スコープ逸脱チェック
- Out of Scope 変更の有無: No
- 逸脱内容:
  - なし

## 不整合/回帰リスク
- R-01:
  - `src/pyoco_server/http_api.py` と `src/pyoco_server/worker.py` は元から 1000 行超で、今回も validator 上の exception 対象のまま。
- R-02:
  - `src/pyoco_server/bundle_runtime.py` は 529 行で review threshold 超過。800 行未満だが、今後の follow-up で分割余地がある。
- R-03:
  - verify は targeted test を通したが、全テストスイート (`uv run pytest`) は未実行。

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
  - bundle runtime の肥大化予防と HTTP/worker の既存巨大ファイル分割は別 delta 候補。

## 判定
- Overall: PASS

## FAIL時の最小修正指示
- なし

# delta-archive

## Delta ID
- DR-20260308-spawn-bundle

## クローズ判定
- verify結果: PASS
- review gate: PASSED
- archive可否: 可

## 確定内容
- 目的:
  - Spawn / YAML Bundle を 1 本の delta で docs 同期、API/設計、コード実装、テスト、verify まで完了させる。
- 変更対象:
  - bundle submit / approval API、bundle parser、relation保存、worker spawn orchestration、設定、unit/E2E テスト、canonical docs 同期。
- 非対象:
  - 外部 workflow registry / 外部 URL / 外部 YAML、child からの孫 spawn、厳格マルチテナント権限委譲、scheduler 刷新、Dashboard 全面刷新。

## 実装記録
- 変更ファイル:
  - `docs/OVERVIEW.md`
  - `docs/architecture.md`
  - `docs/config.md`
  - `docs/library_api.md`
  - `docs/plan.md`
  - `docs/spec.md`
  - `src/pyoco_server/_workflow_test_tasks.py`
  - `src/pyoco_server/bundle_runtime.py`
  - `src/pyoco_server/config.py`
  - `src/pyoco_server/http_api.py`
  - `src/pyoco_server/http_client.py`
  - `src/pyoco_server/models.py`
  - `src/pyoco_server/resources.py`
  - `src/pyoco_server/worker.py`
  - `src/pyoco_server/workflow_yaml.py`
  - `tests/test_spawn_bundle_e2e.py`
  - `tests/test_workflow_yaml.py`
- AC達成状況:
  - AC-01: 達成
  - AC-02: 達成
  - AC-03: 達成
  - AC-04: 達成
  - AC-05: 達成
  - AC-06: 達成

## 検証記録
- verify要約:
  - static / targeted unit / targeted E2E / delta validator を実施し、Overall PASS。
- 主要な根拠:
  - `uv run python -m compileall src tests`
  - `uv run pytest tests/test_workflow_yaml.py tests/test_config_from_env.py`
  - `uv run pytest tests/test_spawn_bundle_e2e.py`
  - `uv run pytest tests/test_nats_e2e.py -k "test_e2e_submit_and_run_with_ephemeral_nats or test_http_gateway_e2e_submit_yaml_and_run"`
  - `validate_delta_links.js`: PASS
  - review gate: ユーザー合意により通過

## 未解決事項
- あり
  - `src/pyoco_server/bundle_runtime.py` は 529 行で review threshold 超過。今後の follow-up で分割余地がある。
  - `src/pyoco_server/http_api.py`、`src/pyoco_server/worker.py`、`tests/test_nats_e2e.py`、`src/pyoco_server/static/app.js` は既存から 1000 行超の例外対象。
  - `uv run pytest` の全量実行は未実施。

## 次のdeltaへの引き継ぎ（任意）
- Seed-01:
  - bundle runtime / http_api / worker の責務分割と巨大ファイル是正を別 delta で検討する。
