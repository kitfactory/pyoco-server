# docs/OVERVIEW.md（入口 / 運用の正本）

この文書は **プロジェクト運用の正本**です。`AGENTS.md` は最小ルールのみで、詳細はここに集約します。

---

## 現在地（必ず更新）
- 現在フェーズ: Phase 4（v0.4：YAML（flow.yaml）投入の運用I/F）
- 現在のバージョン（実装の区切り）: v0.5.0
- 今回スコープ（1〜5行）:
  - pyoco 0.6.2（single-flow: `flow:`）に合わせ、`flow.yaml`（YAML）を multipart で投入できるようにする（`POST /runs/yaml`）
  - params は `flow.defaults` を正本とし、HTTP側の上書きI/Fは初期は提供しない
  - policy（最小）：ファイルサイズ上限（`PYOCO_WORKFLOW_YAML_MAX_BYTES`）、YAMLスキーマの不明キー拒否、禁止キー（`flows`/`discovery`）拒否
  - YAML本文はKVに保存せず、ジョブメッセージに埋めて worker が実行する（スナップショットには sha256/bytes を刻む）
  - GUI向け最小状態管理I/Fを追加実装（`GET /runs` の差分取得、`GET /runs/{run_id}/watch` SSE）
  - 最小GUIダッシュボードを静的配信で提供（`GET /` と `GET /static/*`）
  - Dashboard文言の日英切替（サーバーロケールを既定とし、`PYOCO_DASHBOARD_LANG` / `pyoco-server --dashboard-lang` で指定可能）
  - `NatsBackendConfig.from_env()` で `.env` 自動読込に対応（`PYOCO_LOAD_DOTENV` / `PYOCO_ENV_FILE`）
  - `pyoco-server up --with-nats-bootstrap` で単体NATSを同時起動可能（任意依存、未導入時は明示エラー）
  - CLIの使い勝手改善を反映済み（`submit` の入力簡略化、`list/watch` の出力モード、修正例付きエラー表示）
  - 完了スコープ：Workers運用可視化の拡張（停止種別の区別、手動hide、運用表示改善）
  - run取消（`POST /runs/{run_id}/cancel`、`CANCELLING -> CANCELLED`、best-effort、`PYOCO_CANCEL_GRACE_PERIOD_SEC`）を実装し、HTTP/worker/CLI/Dashboard/E2E を反映済み
  - wheelレジストリ（JetStream Object Store）を追加し、`/wheels` API（list/upload/download/delete/history）と worker の wheel 同期・差分インストール（opt-in）を実装（wheelタグとworkerタグの一致で配布）
  - wheelアップロードは同一パッケージで「必ずバージョンアップ」を必須化（同一/過去バージョンは 409 で拒否）
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
    - `GET /` / `GET /static/*` -> Dashboard UI（静的HTML/CSS/JS）
    - `GET /wheels` / `POST /wheels` / `GET /wheels/{wheel_name}` / `DELETE /wheels/{wheel_name}` / `GET /wheels/history` -> wheel registry 管理/履歴参照
    - `POST /runs` -> KV snapshot + JetStream publish
    - `POST /runs/yaml` -> KV snapshot + JetStream publish（job payload に workflow_yaml を埋め込む）
    - `GET /runs/{run_id}` -> snapshot (+任意のliveness付加) with `include=records`
    - `GET /runs/{run_id}/watch` -> SSE で run snapshot 更新を配信
    - `GET /runs/{run_id}/tasks` -> tasks + records + truncation flag
    - `GET /runs` -> list snapshots（既定はsummary、差分取得時は `items/next_cursor`）
    - `POST /runs/{run_id}/cancel` -> 実装済み（非terminal run は `CANCELLING`、worker協調で `CANCELLED` へ収束、terminal run は冪等）
    - `GET /workers` には `wheel_sync` が含まれ、workerごとの配布結果（反映済み/互換外skip/失敗）を確認可能
  - Dashboard assets: `src/pyoco_server/static/index.html`, `src/pyoco_server/static/styles.css`, `src/pyoco_server/static/app.js`
  - Worker: `src/pyoco_server/worker.py`
    - tag単位のdurable consumer（OR pull）
    - run実行（Pyoco Engine：flow_resolver / workflow_yaml）
    - KV snapshots + worker registry（`RUNNING/IDLE/STOPPED_GRACEFUL/DISCONNECTED`）
    - wheel同期（JetStream Object Store `pyoco_wheels`）と差分インストール（`wheel_sync_enabled=true` 時のみ。起動時と次回poll前に同期し、実行中runの途中では更新しない）
    - 同一パッケージの複数バージョンが存在する場合、worker は最新版のみ同期/インストールする
    - wheel配布履歴（JetStream KV `pyoco_wheel_history`）を記録し、アップロード元情報を参照可能
    - 長時間run: JetStream `in_progress` ACK（AckWait対策）
    - 失敗ディスポジション: ACK/NAK/TERM + DLQ publish（best-effort）
  - Resources: `src/pyoco_server/resources.py`（stream/KV/DLQ bootstrapping）
  - DLQ helper: `src/pyoco_server/dlq.py`
  - Snapshot model/compaction: `src/pyoco_server/models.py`
  - Trace->KV bridge: `src/pyoco_server/trace.py`
  - HTTP client: `src/pyoco_server/http_client.py`
  - NATS client: `src/pyoco_server/client.py`（主に内部/テスト用）
  - CLI:
    - `pyoco-server` -> `src/pyoco_server/server_cli.py`
    - `pyoco-worker` -> `src/pyoco_server/worker_cli.py`
    - `pyoco-client` -> `src/pyoco_server/client_cli.py`
    - `pyoco-server-admin` -> `src/pyoco_server/admin_cli.py`
- テスト（ベースライン）
  - E2E（NATS + worker + HTTP gateway）: `tests/test_nats_e2e.py`
  - E2E（wheel registry + worker sync）: `tests/test_wheel_registry.py`
  - E2E（Browser: Playwright / WSL headless Chromium）: `tests/test_dashboard_playwright_e2e.py`
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
