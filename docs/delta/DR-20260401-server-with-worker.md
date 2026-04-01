# delta-request

## Delta ID
- DR-20260401-server-with-worker

## Delta Type
- FEATURE

## 目的
- `pyoco-server up` から HTTP Gateway と worker を同時起動できるようにし、単機運用の起動手順を短縮する。
- 既存の `pyoco-worker` 単独起動は維持しつつ、server 側には最小限の co-launch option だけ追加する。

## 変更対象（In Scope）
- `pyoco-server up --with-worker` を追加する。
- 管理 worker 用の最小 CLI 引数を `pyoco-server up` に追加する。
- server 終了時や uvicorn 失敗時に managed worker を停止する。
- `tests/test_server_cli.py` に managed worker の起動・停止・引数伝播のテストを追加する。
- `docs/OVERVIEW.md` / `docs/config.md` / `docs/quickstart.md` / `docs/plan.md` に最小限の運用導線を反映する。

## 非対象（Out of Scope）
- 複数 worker の同時起動。
- worker の全 CLI オプションを `pyoco-server up` に透過転送すること。
- supervisor / restart policy / health monitor の実装。
- dashboard / HTTP API / worker 実行ロジック自体の変更。

## 差分仕様
- DS-01:
  - Given: 利用者が `pyoco-server up --with-worker` を指定する。
  - When: server CLI が起動する。
  - Then: HTTP Gateway に加えて 1 worker subprocess を同時起動する。
- DS-02:
  - Given: 利用者が `--worker-id` / `--worker-tags` / `--worker-flow-resolver` / `--worker-poll-timeout` を指定する。
  - When: managed worker が起動する。
  - Then: `pyoco-worker` 相当の引数として subprocess に渡される。
- DS-03:
  - Given: `--with-nats-bootstrap` と `--with-worker` を併用する。
  - When: server CLI が起動・終了する。
  - Then: managed NATS の URL が worker にも適用され、終了時は worker → NATS の順で停止する。

## 受入条件（Acceptance Criteria）
- AC-01: `pyoco-server up --with-worker` が managed worker subprocess を起動する。
- AC-02: uvicorn 失敗時や通常終了時に managed worker が停止される。
- AC-03: `--with-nats-bootstrap --with-worker` の併用時に `PYOCO_NATS_URL` が一致し、worker 引数が期待どおり組み立てられる。
- AC-04: 対象の server CLI テストが PASS する。

## 制約
- 引数は単機運用の最小セットに限定する。
- 既存の `pyoco-server up` / `pyoco-worker` の互換挙動を壊さない。

## Review Gate
- required: No
- reason: server CLI の additive change に閉じ、既存 API / データモデル変更を伴わないため。

## 未確定事項
- Q-01: managed worker subprocess は `sys.executable -m pyoco_server.worker_cli` で起動する。

## Step 2: delta-apply
- status: APPLIED
- changed files:
  - `src/pyoco_server/server_cli.py`
  - `tests/test_server_cli.py`
  - `docs/OVERVIEW.md`
  - `docs/config.md`
  - `docs/quickstart.md`
  - `docs/plan.md`
- applied AC:
  - AC-01:
    - `pyoco-server up --with-worker` を追加し、managed worker subprocess を起動するようにした。
  - AC-02:
    - server 終了時と uvicorn 例外時に managed worker を `finally` で停止するようにした。
  - AC-03:
    - `--worker-id` / `--worker-tags` / `--worker-flow-resolver` / `--worker-poll-timeout` を server CLI から worker subprocess へ伝播するようにした。
    - `--with-nats-bootstrap` 併用時は managed NATS URL を worker 側にも渡すようにした。
- non-scope check:
  - Out of Scope への変更なし: Yes
- code split health:
  - file over 500 lines: No
  - file over 800 lines: No
  - file over 1000 lines: No

## Step 3: delta-verify
- verify profile:
  - static check:
    - `python -m compileall src tests`
  - targeted unit:
    - `uv run pytest -q tests/test_server_cli.py`
  - targeted integration / E2E:
    - Not required
  - delta validator:
    - Not run
- AC result table:
  - AC-01: PASS
    - server CLI test で managed worker subprocess 起動を確認した。
  - AC-02: PASS
    - uvicorn 例外時の managed worker 停止を確認した。
  - AC-03: PASS
    - `--with-nats-bootstrap --with-worker` 併用時の引数組み立てと NATS URL 伝播を確認した。
  - AC-04: PASS
    - `tests/test_server_cli.py` が全件 PASS した。
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
