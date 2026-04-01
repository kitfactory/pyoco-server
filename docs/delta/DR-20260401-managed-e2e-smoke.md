# delta-request

## Delta ID
- DR-20260401-managed-e2e-smoke

## Delta Type
- OPS

## 目的
- `pyoco-server up --with-nats-bootstrap --with-worker` の実運用経路で、NATS と worker を同時に使って flow 実行まで到達することを確認する。

## 変更対象（In Scope）
- managed NATS + managed worker + HTTP Gateway の起動。
- YAML flow の submit と terminal 収束確認。
- 結果の記録。

## 非対象（Out of Scope）
- 実装変更。
- full suite の再実行。
- 新規 API / CLI 追加。

## 差分仕様
- DS-01:
  - Given: `pyoco-server up --with-nats-bootstrap --with-worker` が使える。
  - When: YAML flow を `POST /runs/yaml` 相当で投入する。
  - Then: run が worker により処理され terminal status に到達する。

## 受入条件（Acceptance Criteria）
- AC-01: managed server が health check に応答する。
- AC-02: `submit-yaml` 後に run が terminal (`COMPLETED` / `FAILED` / `CANCELLED`) に到達する。
- AC-03: 結果として run status と worker 観測結果を記録する。

## 制約
- この delta では原則としてテスト実行と記録のみを行う。

## Review Gate
- required: No
- reason: OPS の実行確認のみのため。

## 未確定事項
- なし

## Step 2: delta-apply
- status: APPLIED
- executed steps:
  - `pyoco-server up --with-nats-bootstrap --with-worker --worker-id smoke-w1 --worker-tags smoke --host 127.0.0.1 --port <free_port>` を実プロセスで起動。
  - YAML flow を `submit-yaml` で投入。
  - `GET /runs/{run_id}` を poll して terminal 収束を確認。
  - `GET /workers?scope=all` で managed worker の観測結果を確認。

## Step 3: delta-verify
- verify profile:
  - smoke E2E:
    - managed NATS + managed worker + HTTP Gateway を 1 プロセス起動で確認
- AC result table:
  - AC-01: PASS
    - `GET /health` が 200 を返した。
  - AC-02: PASS
    - run_id `c4380998-95bc-4f85-9a99-4e0fc88ba4a4` が `COMPLETED` に到達した。
    - task status は `add_one=SUCCEEDED`, `to_text=SUCCEEDED`。
  - AC-03: PASS
    - `GET /workers?scope=all` で `worker_id=smoke-w1`, `state=IDLE`, `last_run_id=<run_id>`, `last_run_status=COMPLETED` を観測した。
- observed artifacts:
  - base_url: `http://127.0.0.1:51631`
  - server_log: `C:\Users\kitad\AppData\Local\Temp\pyoco_server_managed_e2e_1775054792.log`
- scope deviation:
  - Out of Scope 変更の有無: No
- overall: PASS

## Step 4: delta-archive
- verify result: PASS
- review gate: NOT REQUIRED
- archive status: archived
- unresolved items:
  - `GET /runs/{run_id}` の最終 snapshot では `worker_id` が `null` だったが、worker registry 側では `last_run_id` / `last_run_status` により実行完了を観測できた。
  - 今回は smoke 実行のみで、追加修正は行っていない。
- follow-up delta seeds:
  - 必要なら `run snapshot` に最終 `worker_id` を確実に残す follow-up repair を分離する。
