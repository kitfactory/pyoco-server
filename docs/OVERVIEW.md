# docs/OVERVIEW.md（入口 / 運用の正本）

この文書は **プロジェクト運用の正本**です。`AGENTS.md` は最小ルールのみで、詳細はここに集約します。

---

## 現在地（必ず更新）
- 現在フェーズ: Phase 4（v0.4：YAML（flow.yaml）投入の運用I/F）
- 現在のバージョン（実装の区切り）: v0.4.0
- 今回スコープ（1〜5行）:
  - pyoco 0.6.1（single-flow: `flow:`）に合わせ、`flow.yaml`（YAML）を multipart で投入できるようにする（`POST /runs/yaml`）
  - params は `flow.defaults` を正本とし、HTTP側の上書きI/Fは初期は提供しない
  - policy（最小）：ファイルサイズ上限（`PYOCO_WORKFLOW_YAML_MAX_BYTES`）、YAMLスキーマの不明キー拒否、禁止キー（`flows`/`discovery`）拒否
  - YAML本文はKVに保存せず、ジョブメッセージに埋めて worker が実行する（スナップショットには sha256/bytes を刻む）
- 非ゴール（やらないこと）:
  - 厳密な公平性（優先度/同時実行上限）の実装
  - 強い隔離（tenant別subject/tenant別KV）を前提にした大規模な構成変更
  - 破壊的変更（API/データモデル/ID体系の変更）
- 重要リンク:
  - concept: `./concept.md`
  - spec: `./spec.md`
  - architecture: `./architecture.md`
  - plan: `./plan.md`
  - quickstart: `./quickstart.md`
  - tutorial（server + 複数worker）: `./tutorial_multi_worker.md`
  - library api: `./library_api.md`
  - config: `./config.md`

---

## 現状（ベースライン：実装/テスト/デモの所在）
- 実装（主要モジュール）
  - HTTP gateway: `src/pyoco_server/http_api.py`
    - `POST /runs` -> KV snapshot + JetStream publish
    - `POST /runs/yaml` -> KV snapshot + JetStream publish（job payload に workflow_yaml を埋め込む）
    - `GET /runs/{run_id}` -> snapshot (+任意のliveness付加) with `include=records`
    - `GET /runs/{run_id}/tasks` -> tasks + records + truncation flag
    - `GET /runs` -> list snapshots（既定はsummary、`include=full`でfull）
  - Worker: `src/pyoco_server/worker.py`
    - tag単位のdurable consumer（OR pull）
    - run実行（Pyoco Engine：flow_resolver / workflow_yaml）
    - KV snapshots + worker TTL liveness
    - 長時間run: JetStream `in_progress` ACK（AckWait対策）
    - 失敗ディスポジション: ACK/NAK/TERM + DLQ publish（best-effort）
  - Resources: `src/pyoco_server/resources.py`（stream/KV/DLQ bootstrapping）
  - DLQ helper: `src/pyoco_server/dlq.py`
  - Snapshot model/compaction: `src/pyoco_server/models.py`
  - Trace->KV bridge: `src/pyoco_server/trace.py`
  - HTTP client: `src/pyoco_server/http_client.py`
  - NATS client: `src/pyoco_server/client.py`（主に内部/テスト用）
- テスト（ベースライン）
  - E2E（NATS + worker + HTTP gateway）: `tests/test_nats_e2e.py`
  - Unit（snapshot compaction）: `tests/test_snapshot_compaction.py`
  - Unit（workflow yaml）: `tests/test_workflow_yaml.py`
- Quickstart / demo
  - `docs/quickstart.md`
  - `examples/hello_flow.py`, `examples/run_worker.py`, `examples/submit_run.py`
- テスト実行
  - `uv run pytest`

---

## レビューゲート（必ず止まる）
共通原則：**自己レビュー → 完成と判断できたらユーザー確認 → 合意で次へ**

---

## 更新の安全ルール（判断用）
### 合意不要
- 誤字修正、リンク更新、意味を変えない追記
- plan のチェック更新
- 小さな明確化（既存方針に沿う）

### 提案→合意→適用（必須）
- 大量削除、章構成変更、移動/リネーム
- Spec ID / Error ID の変更
- API/データモデルの形を変える設計変更
- セキュリティ/重大バグ修正で挙動が変わるもの
