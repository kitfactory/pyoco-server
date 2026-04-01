# delta-request

## Delta ID
- DR-20260401-server-with-worker-verify

## Delta Type
- OPS

## 目的
- `pyoco-server up --with-worker` 追加後のテストを実施し、現時点の通過状況を確定する。

## 変更対象（In Scope）
- `--with-worker` 追加分の targeted test 実行。
- 必要に応じて full test 実行。
- 結果を delta 記録と plan に反映する。

## 非対象（Out of Scope）
- 新規機能追加。
- テスト失敗時の追加修正。

## 差分仕様
- DS-01:
  - Given: `pyoco-server up --with-worker` が実装済みである。
  - When: server CLI の targeted test と full suite を実行する。
  - Then: 通過/失敗状況を観測できる。

## 受入条件（Acceptance Criteria）
- AC-01: targeted test の実行結果を記録する。
- AC-02: full suite の実行結果を記録する。

## 制約
- この delta では原則としてテスト実行と記録のみを行う。

## Review Gate
- required: No
- reason: 実装変更を伴わない verification / ops 作業のため。

## 未確定事項
- Q-01: full suite の結果が green かどうかは実行後に確定する。

## Step 2: delta-apply
- status: APPLIED
- executed commands:
  - `python -m compileall src tests`
  - `uv run pytest -q tests/test_server_cli.py`
  - `uv run pytest -vv`

## Step 3: delta-verify
- verify profile:
  - static check:
    - `python -m compileall src tests`
  - targeted unit:
    - `uv run pytest -q tests/test_server_cli.py`
  - full suite:
    - `uv run pytest -vv`
- AC result table:
  - AC-01: PASS
    - targeted test は `11 passed`。
  - AC-02: FAIL
    - full suite は `1 failed`。
- scope deviation:
  - Out of Scope 変更の有無: No
- overall: FAIL

## FAIL時の最小修正指示
- Fix-01:
  - `tests/test_nats_e2e.py::test_http_gateway_vnext_list_cursor_filter_and_invalid_cursor` で `GET /runs?tag=vnext&limit=1&updated_after=0.0` が 500 を返すため、`GET /runs` の best-effort scan を harden する。
