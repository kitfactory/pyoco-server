# delta-request

## Delta ID
- DR-20260401-test-fixes

## Delta Type
- REPAIR

## 目的
- `uv run pytest` で失敗している 6 件を、最小差分で green に戻す。
- 既存機能追加は行わず、Windows 実行互換と E2E の安定化に閉じて修正する。

## 変更対象（In Scope）
- `src/pyoco_server/worker_cli.py` の `--flow-resolver` 解釈を Windows 絶対パスに対応させる。
- `tests/test_wheel_registry.py` の uvicorn 起動方法を Windows / POSIX 両対応にする。
- cancel / dashboard E2E の失敗原因を特定し、既存仕様を変えずにテストまたは実装を最小修正する。
- 今回の修正を delta 記録と plan に反映する。

## 非対象（Out of Scope）
- schedule 機能、bundle 機能、wheel 配布仕様自体の追加変更。
- cancel の仕様拡張、Dashboard UI の新機能追加。
- 既存の巨大ファイル分割や広範囲リファクタ。

## 差分仕様
- DS-01:
  - Given: `pyoco-worker --flow-resolver <absolute_windows_path>:resolve_flow` の形式で resolver 指定する。
  - When: worker CLI が resolver を読み込む。
  - Then: Windows drive letter を module 名と誤認せず、対象ファイルから callable をロードできる。
- DS-02:
  - Given: wheel registry E2E が HTTP API を別プロセスで起動する。
  - When: Windows 上で full test を実行する。
  - Then: Python 実行ファイルパスが環境依存で壊れず、テストが起動できる。
- DS-03:
  - Given: dashboard / cancel の現物 E2E を full test で実行する。
  - When: worker registry 更新や cancel 収束を観測する。
  - Then: 既存仕様どおりに `uv run pytest` が安定して通る。

## 受入条件（Acceptance Criteria）
- AC-01: `uv run pytest -q tests/test_worker_cli.py` が PASS する。
- AC-02: `uv run pytest -q tests/test_wheel_registry.py -k "upload_list_download_delete or strict_version_bump"` が PASS する。
- AC-03: full suite で失敗していた dashboard / cancel 系テストが PASS する。
- AC-04: `uv run pytest` 全体が PASS する。

## 制約
- 変更は失敗 6 件の修復に必要なファイルへ限定する。
- public API / CLI 仕様は変更しない。

## Review Gate
- required: No
- reason: 既存仕様の repair に限定し、互換性のある最小差分で閉じるため。

## 未確定事項
- Q-01: dashboard / cancel 失敗が実装不備かテストのタイミング依存かは再現確認後に確定する。

## Step 2: delta-apply
- status: APPLIED
- changed files:
  - `src/pyoco_server/worker.py`
  - `src/pyoco_server/worker_cli.py`
  - `src/pyoco_server/http_api.py`
  - `tests/test_wheel_registry.py`
  - `tests/test_nats_e2e.py`
  - `tests/test_dashboard_playwright_e2e.py`
  - `docs/plan.md`
- applied AC:
  - AC-01:
    - `worker_cli` の resolver 解析を `rsplit(":", 1)` に変更し、Windows 絶対パスを `module:function` と誤解釈しないように修正。
  - AC-02:
    - wheel registry E2E の uvicorn 起動に `sys.executable` を使用し、Windows / POSIX 両対応に修正。
  - AC-03:
    - worker が既存 snapshot の cancel request を初期継承し、pre-start cancel を落とさないよう修正。
    - `GET /runs/{run_id}`、`GET /workers`、`GET /metrics` の best-effort 部分を harden し、個別 KV key 異常で 500 を返さないよう修正。
    - dashboard E2E は worker list refresh を明示的に発火して安定化。
    - cancel E2E は immediate `CANCELLED` を許容するよう観測条件を最小修正。
- non-scope check:
  - Out of Scope への変更なし: Yes
- code split health:
  - file over 500 lines: Yes
  - file over 800 lines: Yes
  - file over 1000 lines: Yes
  - note: 既存の長大ファイル（`http_api.py` / `worker.py` / `tests/test_nats_e2e.py`）への最小差分のみで、新規の責務拡張は行っていない。

## Step 3: delta-verify
- verify profile:
  - static check: `python -m compileall src tests`
  - targeted unit:
    - `uv run pytest -q tests/test_worker_cli.py tests/test_wheel_registry.py -k "load_flow_resolver or upload_list_download_delete or strict_version_bump"`
  - targeted integration / E2E:
    - `uv run pytest -q tests/test_nats_e2e.py::test_http_gateway_cancel_run_transitions_to_cancelled_and_idempotent tests/test_dashboard_playwright_e2e.py::test_dashboard_playwright_e2e_with_auth_and_watch`
    - `uv run pytest -q tests/test_nats_e2e.py::test_http_gateway_metrics_and_workers_endpoints -vv`
  - full suite:
    - `uv run pytest -vv`
- AC result table:
  - AC-01: PASS
    - `tests/test_worker_cli.py` の Windows path 失敗 2 件が解消。
  - AC-02: PASS
    - `tests/test_wheel_registry.py` の subprocess 起動失敗 2 件が解消。
  - AC-03: PASS
    - cancel / dashboard / metrics-workers の full-suite 起因失敗が再現しなくなり、対象 E2E が green。
  - AC-04: PASS
    - `uv run pytest -vv` で 87 passed。
- scope deviation:
  - Out of Scope 変更の有無: No
- review findings:
  - review gate required: No
  - layer integrity: PASS
  - docs sync: PASS
  - data size: PASS
  - code split health: PASS
- overall: PASS

## Step 4: delta-archive
- verify result: PASS
- review gate: NOT REQUIRED
- archive status: archived
- unresolved items:
  - なし
- follow-up delta seeds:
  - なし

## Canonical Sync
- synced docs:
  - concept: No change
  - spec: No change
  - architecture: No change
  - plan: `docs/plan.md`
