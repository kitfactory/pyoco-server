# architecture.md（必ず書く：最新版）
#1.アーキテクチャ概要（構成要素と責務）
本システムは、プロトコル境界を明確に2面に分ける。

設計中心（Positioning）：
- `pyoco-server` は **Pyoco 本体ではなく**、社内システム向けの軽量分散実行バックエンド。
- 運用対象は単一組織・少人数運用を主眼に置く。
- 厳格マルチテナント分離や超大規模SLA基盤は設計中心に置かない（拡張余地は残す）。

- Client <-> Server：HTTP
  - Pyoco利用者はHTTPのみを使い、NATSを意識しない（資格情報も持たない）。
- Server <-> Worker：NATS JetStream
  - WorkQueue（run投入）と KV（最新状態可視化）と DLQ（診断）と Object Store（wheel配布）を JetStream に集約する。

構成要素：
- HTTP Gateway（Server）
  - HTTP APIを提供（run投入/参照/取消、worker運用可視化/表示制御、wheel管理）
  - JetStreamリソースの確認/作成（Stream/KV/DLQ/Object Store）
  - run投入の原子性（KV初期化 + publish 成功でのみ成功応答）
  - run参照（KV読み出し）と任意のworker状態付加（worker registry）
  - GUI向けの最小状態管理I/F（一覧差分取得、run監視SSE）
  - （opt-in）HTTP API key 認証（`X-API-Key`）と tenant attribution（runへ帰属を刻む）
- Dashboard UI（運用者向け、read-only）
  - run一覧/詳細、worker一覧、metrics を1画面で確認する
  - worker一覧は状態（`RUNNING`/`IDLE`/`STOPPED_GRACEFUL`/`DISCONNECTED`）と hidden 状態を表示する
  - 一覧は cursor + updated_after で差分更新し、詳細は SSE watch を利用する
  - UI文言は `ja`/`en` の辞書で管理し、既定はサーバーロケールで決定する（`PYOCO_DASHBOARD_LANG` / `pyoco-server --dashboard-lang` で上書き可能）
- Operation CLI（利用者/運用者向け）
  - `pyoco-client`：run投入/参照/監視/取消/一覧/workers/metrics/wheels を実行する
  - `pyoco-server`：HTTP Gatewayを起動する
  - `pyoco-worker`：workerを起動する（flow_resolverは必要時のみ指定）
  - `pyoco-server-admin`：API key 管理（create/list/revoke）
  - `nats-bootstrap`：NATS運用（`up/join/status/doctor/backup/restore/leave/down/service`）
- Worker
  - tag 単位の durable consumer から pull でジョブを取得（複数tagは OR）
  - Pyoco Engine で run を実行し、Traceを KV スナップショットへ反映
  - worker registry を更新し、`RUNNING`/`IDLE`/`STOPPED_GRACEFUL` を記録する
  - terminal スナップショットを書いてから ACK（at-least-once）
  - 長時間runは JetStream in_progress ACK を定期送信して意図しない再配送を防ぐ
  - cancel要求を検知した場合は `Engine.cancel(run_id)` を呼び、`CANCELLING -> CANCELLED` に収束させる（best-effort）
  - wheel同期（opt-in）：起動時と `run_once` の次回poll前に Object Store を同期し、タグ一致wheelのみ差分インストールする（実行中runの途中更新はしない）
  - 失敗分類に応じて ACK/NAK/TERM + DLQ publish（best-effort）
- Admin CLI（運用：API key 管理）
  - API key の発行/一覧/失効を行い、JetStream KVへ保存する（平文キーは保存しない）
- NATS JetStream
  - Stream：PYOCO_WORK（WorkQueue）
  - Stream：PYOCO_DLQ（診断用）
  - KV：pyoco_runs（最新スナップショット）
  - KV：pyoco_workers（worker registry）
  - KV：pyoco_auth（API key レコード）
  - KV：pyoco_wheel_history（wheel配布履歴）
  - Object Store：pyoco_wheels（wheel registry）

#2.concept のレイヤー構造との対応表
（テキスト図示）
```
[Pyoco Client / Dashboard UI / Operation CLI / HTTP Client] -> [HTTP Gateway] -> [NATS JetStream (Stream/KV/DLQ/ObjectStore)] <- [Worker + Pyoco Engine]
```

| conceptレイヤー | 対応コンポーネント | 主な責務 |
|---|---|---|
| 運用UI層 | Dashboard UI | run/worker/metricsの継続監視 |
| プレゼンテーション層（CLI） | pyoco-client / pyoco-server / pyoco-worker / pyoco-server-admin | 起動/投入/参照/運用操作のCLI導線 |
| プレゼンテーション層 | PyocoHttpClient / 外部HTTPクライアント | HTTPでrun投入/参照 |
| アプリケーション層 | HTTP Gateway（ユースケース実装） | 原子性・参照時の付加情報・worker状態判定/表示制御・wheel配布契約 |
| インフラ層 | JetStream（Stream/KV/DLQ/Object Store） | 分散キュー/最新状態/診断/配布アーティファクト |
| 実行層（worker） | PyocoNatsWorker + Pyoco Engine | run実行と状態更新 |

#3.インターフェース設計（Interface）
### UI/APP境界（ユースケース単位）
#### UC-1: runを投入する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `POST /runs` | runを受理しKV初期化後にWorkQueueへ投入 | JSON（RunSubmitRequest）：flow_name: string(1+), params: object, tag?: string(`[A-Za-z0-9_-]+`、`.`禁止), tags?: array<string>（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：run_id: uuid, status: "PENDING" | ERR-PYOCO-0002（422）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503）, ERR-PYOCO-0004（best-effort cleanup失敗の可能性） |
| `POST /runs/yaml` | flow.yaml（YAML）を run として受理し、KV初期化後にWorkQueueへ投入 | multipart（RunSubmitYamlRequest）：workflow: file(YAML, bytes), flow_name: string(1+), tag?: string(`[A-Za-z0-9_-]+`、`.`禁止)（opt-in：HTTP auth有効時は header `X-API-Key` 必須。params上書きは提供しない） | JSON：run_id: uuid, status: "PENDING" | ERR-PYOCO-0002（422：YAML不正/不明キー/禁止キー/flow_name欠落等）, ERR-PYOCO-0016（413：サイズ上限超過）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |

#### UC-2: runの状態を確認する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /runs/{run_id}` | runスナップショット（任意でrecords含む）を返す | path：run_id: uuid文字列、query：include?: array<string>（records/full/all）（opt-in：HTTP auth有効時は header `X-API-Key` 必須。tenant不一致は404で隠蔽してよい） | JSON（RunSnapshot）：run_id, flow_name, status, params, tasks, heartbeat_at, updated_at（+任意でtask_records等） | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0005（404）, ERR-PYOCO-0003（503） |

#### UC-3: タスク状態/記録を確認する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /runs/{run_id}/tasks` | tasks と task_records を返す | path：run_id: uuid文字列（opt-in：HTTP auth有効時は header `X-API-Key` 必須。tenant不一致は404で隠蔽してよい） | JSON：run_id, flow_name, status, tasks, task_records, task_records_truncated | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0005（404）, ERR-PYOCO-0003（503） |

#### UC-4: run一覧を取得する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /runs` | KV keysを走査して一覧を返す（best-effort、GUI差分取得対応） | query：status?: string, flow?: string, tag?: string, include?: array<string>, limit?: int(1..200、既定50), updated_after?: number(unix seconds), cursor?: string(opaque), workflow_yaml_sha256?: string（opt-in：HTTP auth有効時は header `X-API-Key` 必須。結果は同一tenantのみに限定） | JSON（互換）：array<RunSummary or RunSnapshot> / JSON（差分取得）：RunListResponse（items, next_cursor） | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0017（422）, ERR-PYOCO-0003（503） |

#### UC-10: run詳細を継続監視する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /runs/{run_id}/watch` | runスナップショット更新をSSEで継続配信する | path：run_id: uuid文字列、query：include?: array<string>（records/full/all）, since?: number(unix seconds), timeout_sec?: int(1..600)（opt-in：HTTP auth有効時は header `X-API-Key` 必須。tenant不一致は404で隠蔽してよい） | `text/event-stream`（RunWatchEvent）：event=`snapshot`/`heartbeat`, data={run_id,snapshot,ts} | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0005（404）, ERR-PYOCO-0003（503） |

#### UC-14: runを取消する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `POST /runs/{run_id}/cancel` | runの取消要求を記録し、非terminal run を `CANCELLING` に遷移させる | path：run_id: uuid文字列、body?: {reason?: string}（将来互換。現行は省略可）（opt-in：HTTP auth有効時は header `X-API-Key` 必須。tenant不一致は404で隠蔽してよい） | JSON（RunSnapshot）：`status=CANCELLING` または terminal run の現行状態 | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0005（404）, ERR-PYOCO-0003（503） |

#### UC-15: wheelを登録・同期する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /wheels` | wheel registry の一覧を返す | -（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：array<{name,size_bytes,bucket,nuid,modified,sha256_hex?,tags:array<string>}> | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |
| `GET /wheels/history` | wheel配布履歴を返す | query：limit?:int(1..500), wheel_name?:string(`*.whl`), action?:`upload|delete`（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：array<{event_id,occurred_at,action,wheel_name,tags,source,actor,...}> | ERR-PYOCO-0002（422）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |
| `POST /wheels` | wheelをタグ付きで登録する | multipart：wheel:file(`*.whl`), replace?:bool(default true), tags?:csv（`[A-Za-z0-9_-]+` のCSV）。同一パッケージは厳密なバージョンアップのみ許可（同一/過去バージョンは409）（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：{name,size_bytes,bucket,nuid,modified,sha256_hex,tags} | ERR-PYOCO-0002（422/413）, ERR-PYOCO-0022（409）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |
| `GET /wheels/{wheel_name}` | wheel bytes を取得する | path：wheel_name:string(`*.whl`)（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | `application/octet-stream` | ERR-PYOCO-0023（404）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |
| `DELETE /wheels/{wheel_name}` | wheelを削除する | path：wheel_name:string(`*.whl`)（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：{name,deleted:true} | ERR-PYOCO-0023（404）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |

#### UC-11: ダッシュボードを表示する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /` | 運用向けダッシュボード（単一HTML）を返す | - | `text/html`（Dashboard index） | 404（静的ファイル未配置時） |
| `GET /static/{path}` | ダッシュボードの静的アセット（JS/CSS）を返す | path: string | `application/javascript` / `text/css` | 404（対象ファイル不存在） |

#### UC-12: CLIでrun運用を行う
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `pyoco-client submit/submit-yaml/get/list/watch/cancel/tasks/workers/metrics/wheels/wheel-history/wheel-upload/wheel-delete` | run運用とwheel配布のCLI操作を提供する | argv（`--server`, `--api-key`, 各subcommand引数） | stdout（JSONまたはtext） | ERR-PYOCO-0018（CLI引数不正）, ERR-PYOCO-0002/0003/0005/0022/0023（HTTP経由） |
| `pyoco-server` | HTTP Gateway起動を簡略化する | argv（`up`, `--host`, `--port`, `--nats-url`, `--with-nats-bootstrap?`, `--nats-listen-host?`, `--nats-client-port?`, `--nats-http-port?`） | process起動 | ERR-PYOCO-0018（CLI引数不正、`nats-bootstrap` 不在、ポート競合など） |
| `pyoco-worker` | worker起動を簡略化する | argv（`--nats-url`, `--tags`, `--worker-id`, `--flow-resolver?`, `--wheel-sync?`, `--wheel-sync-dir?`, `--wheel-sync-interval-sec?`） | process起動 | ERR-PYOCO-0018（CLI引数不正） |

#### UC-7: 稼働状態を確認する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /health` | 稼働確認 | - | JSON：status: "ok" | ERR-PYOCO-0001（到達不可等） |

#### UC-8: メトリクスを取得する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /metrics` | 運用向けメトリクスを返す（best-effort） | -（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | text/plain（Prometheus互換）：pyoco_runs_total/pyoco_workers_alive_total/pyoco_dlq_messages_total | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（NATS不可） |

#### UC-9: worker一覧を取得する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /workers` | worker registry から一覧を返す（best-effort） | query：scope?: `active|all`（default `active`）, state?: worker state enum, include_hidden?: bool（default false）, limit?: int(1..500)（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：array<{worker_id, state, hidden, last_seen_at, tags, current_run_id?, last_run_status?, stopped_at?, stop_reason?, wheel_sync?}> | ERR-PYOCO-0019（422）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（NATS不可） |

#### UC-13: worker表示を制御する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `PATCH /workers/{worker_id}` | workerの `hidden` を更新する | path：worker_id:string, body：hidden:bool（opt-in：HTTP auth有効時は header `X-API-Key` 必須） | JSON：{worker_id, hidden, updated_at} | ERR-PYOCO-0019（422）, ERR-PYOCO-0020（404）, ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |

#### UC-6: 失敗を診断する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| （運用）DLQ参照 | DLQを診断に使う | JetStream Stream（PYOCO_DLQ）から購読/参照 | DlqMessage（reason/error等） | ERR-PYOCO-0011（best-effort publish失敗の可能性） |

※例外は「発生場所/原因」が分かる形式で記載する。

### 外部I/F（API単位）
#### API: NATS JetStream
| メソッド | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `nats.connect(url, name=...)` | NATSへ接続 | url: string | nc | 接続失敗（ERR-PYOCO-0003） |
| `nc.jetstream()` | JetStream API取得 | - | js | - |
| `js.publish(subject, payload, stream=...)` | WorkQueue/DLQへpublish | subject: string, payload: bytes | ack | publish失敗（ERR-PYOCO-0003） |
| `js.key_value(bucket)` | KV取得 | bucket: string | kv | bucketなし等（起動時にensure_resources） |
| `kv.put(key, value)` | KV更新 | key: string, value: bytes | rev | put失敗（ERR-PYOCO-0003/0008） |
| `kv.get(key)` | KV取得 | key: string | entry | not found（ERR-PYOCO-0005） |
| `kv.keys()` | KVキー一覧 | - | array<string> | NATS不可（ERR-PYOCO-0003） |
| `kv.watch(key)` | KV更新監視 | key: string | async iterator | NATS不可（ERR-PYOCO-0003） |
| `kv.delete(key)` | KV削除 | key: string | - | best-effort（ERR-PYOCO-0004） |
| `js.object_store(bucket)` | Object Store取得 | bucket: string | object_store | bucketなし等（起動時にensure_resources） |
| `object_store.put(name, data, meta)` | wheel登録 | name: string(`*.whl`), data: bytes, meta headers | info | put失敗（ERR-PYOCO-0003） |
| `object_store.get(name)` | wheel取得 | name: string(`*.whl`) | object result(bytes) | not found（ERR-PYOCO-0023） |
| `object_store.get_info(name)` | wheel存在確認 | name: string(`*.whl`) | info | not found（ERR-PYOCO-0023） |
| `object_store.list(ignore_deletes=...)` | wheel一覧取得 | bool | array<info> | NATS不可（ERR-PYOCO-0003） |
| `object_store.delete(name)` | wheel削除 | name: string(`*.whl`) | - | not found / NATS不可（ERR-PYOCO-0023/0003） |
| `js.add_consumer(stream, config)` | durable consumer作成 | durable/filter/AckWait等 | - | 既存consumer等（環境側により変動） |
| `js.pull_subscribe(subject, durable, stream=...)` | pull購読 | subject/durable | subscription | NATS不可（ERR-PYOCO-0003） |
| `sub.fetch(batch, timeout=...)` | メッセージ取得 | batch:int, timeout:float | msgs | timeout等 |
| `msg.ack()` | ACK | - | - | - |
| `msg.nak(delay=...)` | NAK（遅延再配送） | delay: float | - | NATS不可等（best-effort） |
| `msg.term()` | TERM（再配送しない） | - | - | - |
| `msg.in_progress()` | in_progress ACK | - | - | NATS不可等（ERR-PYOCO-0009） |

### 内部I/F（クラス単位）
#### Class: NatsBackendConfig（`src/pyoco_server/config.py`）
##### Method: （dataclass）
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| （各フィールド） | 文字列/数値/真偽 | NATS/JetStream資源名、heartbeat間隔、consumer既定、DLQ設定、スナップショット上限、wheel同期設定等 | docs/spec.md 付録Iに準拠 | - |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| - | - | - |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| - | - | - |

#### Class: HTTP Gateway（`src/pyoco_server/http_api.py`）
##### Method: `create_app()`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| - | - | FastAPI app factory | - | - |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| app | FastAPI | routes: /health,/runs,/runs/{run_id}/watch,/workers,/metrics,/wheels,... |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| - | 起動時startup | NATS接続/ensure_resources失敗（ERR-PYOCO-0003） |

#### Class: PyocoNatsWorker（`src/pyoco_server/worker.py`）
##### Method: `connect(config, flow_resolver, worker_id, tags)`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| config | NatsBackendConfig | JetStream設定 | - | 任意（既定あり） |
| flow_resolver | Callable[[str], Flow] | flow_name→Flow解決 | 未解決はKeyError推奨 | 必須 |
| worker_id | string | worker識別子（KVキーに使う） | 空でない推奨 | 任意（既定 "worker"） |
| tags | array<string> | 実行可能tag（OR） | `.`禁止、`[A-Za-z0-9_-]+`推奨 | 任意（未指定はdefault） |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| worker | PyocoNatsWorker | run_once/close |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| ValueError | __init__ | tagに`.`を含む |
| NATS例外 | connect/_init | NATS不可、ensure_resources不可（ERR-PYOCO-0003） |

##### Method: `run_once(timeout=1.0) -> Optional[str]`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| timeout | float | 1回のpoll上限 | 0+ | 任意 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| run_id | Optional[str] | 処理したrun_id（無ければNone） |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| ValueError | _decode_job | 不正ジョブ（ERR-PYOCO-0012: invalid_job→TERM+DLQ） |
| NatsError | KV/DLQ等 | 一時障害（NAKで再配送：ERR-PYOCO-0003） |

##### Method: `close()`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| - | - | NATS接続を閉じる | - | - |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| - | - | - |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| - | - | - |

#### Class: PyocoHttpClient（`src/pyoco_server/http_client.py`）
##### Method: `submit_run(flow_name, params=None, tag=None, tags=None) -> dict`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| flow_name | string | 実行するflow名 | 1文字以上 | 必須 |
| params | object | 実行パラメータ | JSON object | 任意 |
| tag | string | ルーティングtag | `.`禁止、pattern推奨 | 任意 |
| tags | array<string> | 表示/検索用タグ | 任意 | 任意 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | dict | run_id, status |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 422/503 等（ERR-PYOCO-0002/0003） |

##### Method: `submit_run_yaml(workflow_yaml, tag) -> dict`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| workflow_yaml | string | 単体flowのYAML（flow.yaml） | UTF-8 | 必須 |
| tag | string | ルーティングtag | `.`禁止、pattern推奨 | 必須 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | dict | run_id, status |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 422/413/503 等（ERR-PYOCO-0002/0016/0003） |

##### Method: `list_wheels() -> list[dict]`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| - | - | wheel一覧を取得 | - | - |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | list[dict] | name, size_bytes, bucket, nuid, modified, sha256_hex?, tags |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 503/401/403 等（ERR-PYOCO-0003/0014/0015） |

##### Method: `list_wheel_history(limit=None, wheel_name=None, action=None) -> list[dict]`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| limit | int | 取得上限 | 1..500 | 任意 |
| wheel_name | string | wheel名フィルタ | `*.whl` | 任意 |
| action | string | 操作種別フィルタ | `upload|delete` | 任意 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | list[dict] | event_id, occurred_at, action, wheel_name, tags, source, actor |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 422/503/401/403（ERR-PYOCO-0002/0003/0014/0015） |

##### Method: `upload_wheel(filename, data, replace=True, tags=None) -> dict`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| filename | string | wheelファイル名 | `*.whl` | 必須 |
| data | bytes | wheel本体 | 0 < bytes <= `PYOCO_WHEEL_MAX_BYTES` | 必須 |
| replace | bool | 後方互換用フラグ（version policy優先） | default true | 任意 |
| tags | array<string> | wheel適用対象タグ | `[A-Za-z0-9_-]+` の集合 | 任意 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | dict | name, size_bytes, bucket, nuid, modified, sha256_hex, tags |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 409/413/422/503/401/403（ERR-PYOCO-0022/0002/0003/0014/0015） |

##### Method: `delete_wheel(wheel_name) -> dict`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| wheel_name | string | 削除対象wheel名 | `*.whl` | 必須 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | dict | name, deleted |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 404/503/401/403（ERR-PYOCO-0023/0003/0014/0015） |

##### Method: `cancel_run(run_id, wait=False, timeout_sec=None) -> dict`
| 引数 | 型 | 意味 | 値範囲/制約 | 必須 |
|---|---|---|---|---|
| run_id | string | 取消対象run | uuid文字列 | 必須 |
| wait | bool | terminalまで待機するか | default false | 任意 |
| timeout_sec | int | 待機上限秒 | 1..3600推奨 | 任意 |

| 戻り値 | 型 | 主要フィールド |
|---|---|---|
| resp | dict | run_id, status, cancel_requested_at? |

| 例外 | 発生場所 | 発生原因 |
|---|---|---|
| HTTPStatusError | HTTP client | 404/503/401/403 等（ERR-PYOCO-0005/0003/0014/0015） |

#### 依存先I/F（最小契約）
| 依存先 | 最小メソッド | 目的 |
|---|---|---|
| flow_resolver | `__call__(flow_name) -> Flow` / `KeyError` | flow解決（ERR-PYOCO-0006） |
| JetStream KV | `put/get/keys/watch/delete` | runスナップショット/worker registry/SSE監視 |
| JetStream Object Store | `list/get/get_info/put/delete` | wheel registry 管理/同期（ERR-PYOCO-0022/0023/0003） |
| JetStream publish | `publish(subject,payload,stream)` | WorkQueue/DLQ |
| JetStream msg | `ack/nak/term/in_progress` | ディスポジション/長時間run |

### 型定義（入出力/DTOの主要フィールド）
| 型 | 主要フィールド（値範囲/制約） | 用途 |
|---|---|---|
| RunSubmitRequest | flow_name: string(1+), params: object, tag?: string(`[A-Za-z0-9_-]+`、`.`禁止), tags?: array<string> | `POST /runs` |
| RunSubmitYamlRequest | workflow: file(YAML), flow_name: string(1+), tag?: string(`[A-Za-z0-9_-]+`、`.`禁止) | `POST /runs/yaml` |
| RunSnapshot | run_id: uuid, flow_name: string, status: enum, params: object, tasks: object, task_records: object, heartbeat_at: number, updated_at: number, error?: string/null, worker_id?: string, workflow_yaml_sha256?: string/null, workflow_yaml_bytes?: number/null | `GET /runs/{id}` / 一覧 |
| RunSummary | run_id, flow_name?, tag?, tags?, status, updated_at, heartbeat_at?, worker_id?, error? | `GET /runs` 既定の軽量返却 |
| RunListResponse | items: array<RunSummary or RunSnapshot>, next_cursor?: string | `GET /runs` |
| RunWatchEvent | event: string(`snapshot`/`heartbeat`), run_id: uuid, snapshot: RunSnapshot, ts: number | `GET /runs/{run_id}/watch` |
| RunCancelRequest | run_id: uuid, reason?: string | `POST /runs/{run_id}/cancel` |
| WheelArtifact | name: string(`*.whl`), size_bytes: int, bucket: string, nuid: string, modified: number, sha256_hex?: string/null, tags: array<string> | `GET/POST /wheels` |
| WheelHistoryEvent | event_id: string, occurred_at: number, action: enum(`upload|delete`), wheel_name: string, tags: array<string>, source: object, actor: object | `GET /wheels/history` |
| WheelSyncState | wheel_name: string, package_name: string, package_version: string, nuid: string, size_bytes: int, sha256_hex: string, tags: array<string>, installed_at: number | worker ローカル同期マニフェスト（`.installed.json`） |
| WorkerRecord | worker_id: string, instance_id: string, state: enum(`RUNNING|IDLE|STOPPED_GRACEFUL|DISCONNECTED`), hidden: bool, last_seen_at: number, last_heartbeat_at: number, tags: array<string>, current_run_id?: string/null, last_run_status?: string/null, stopped_at?: number/null, stop_reason?: string/null, wheel_sync?: object | worker運用表示/制御（`GET /workers`, `PATCH /workers/{worker_id}`） |
| WorkerPatchRequest | hidden: bool | worker表示制御 |
| DlqMessage | timestamp: number, reason: string, error?: string/null, run_id?, flow_name?, tag?, tags?, worker_id?, num_delivered?, subject? | DLQ診断 |
※List/Arrayは要素型を必ず明記する（例: tags: array<string>）

#4.主要フロー設計（成功/失敗）
| フロー | 成功条件 | 失敗条件 | 例外時の動作 |
|---|---|---|---|
| run投入（HTTP→KV→publish） | KV初期化とpublishが成功し200返却 | NATS不可、入力不正 | 422/503。publish失敗後はKV delete（best-effort） |
| run実行（Worker pull→Pyoco→KV→ACK） | terminalスナップショットを書いてACK | 不正ジョブ、flow解決不可、実行失敗、KV一次障害 | invalid_jobはDLQ+TERM。flow_not_found/実行失敗はFAILED記録+ACK（DLQは既定ON）。KV一次障害はNAK(delay) |
| run参照（HTTP→KV→付加情報） | KVスナップショットを返す | run_id不存在、NATS不可 | 404/503。worker状態付加は任意でbest-effort |
| run取消（HTTP→KV更新→worker協調停止） | 非terminal run が `CANCELLING` になり、最終的に `CANCELLED` に収束する | run_id不存在、NATS不可、cancel収束タイムアウト | 404/503。収束タイムアウトは worker 側で `ERR-PYOCO-0021` を記録（best-effort） |
| wheel登録/配布（HTTP→Object Store） | 登録/一覧/取得/削除ができる | 入力不正、同一/過去バージョン登録、対象なし、NATS不可 | 422/413/409/404/503。認証有効時は401/403 |
| worker wheel同期（Worker→Object Store→pip install） | タグ一致wheelのうちパッケージ最新版のみ差分反映される。同期結果は worker registry `wheel_sync` に記録される | NATS不可、ダウンロード/インストール失敗 | 失敗をログ化し次回同期で再試行（best-effort） |
| 一覧（HTTP→KV keys→get→sort） | best-effortで一覧返却（差分取得対応） | クエリ不正、NATS不可 | 422/503。順序はupdated_atでbest-effort。cursorは不透明トークン |
| worker一覧（HTTP→worker registry） | 条件に応じたworker一覧を返す | クエリ不正、NATS不可 | 422/503。`scope=active` 既定、`include_hidden=false` 既定 |
| worker表示制御（HTTP PATCH→worker registry） | hidden更新が反映される | 入力不正、worker不存在、NATS不可 | 422/404/503。hiddenは表示制御のみで実データ削除はしない |
| run監視（HTTP SSE→KV watch/poll） | スナップショット更新を継続配信 | run_id不存在、NATS不可、接続断 | 404/503。接続断はクライアント再接続で復帰（best-effort） |
| ダッシュボード配信（HTTP→静的ファイル） | `/` と `/static/*` が配信される | ファイル未配置、HTTP到達不可 | 404/到達不可。API契約には影響しない |

#5.データ設計（永続化・整合性・マイグレーション）
| データ | 永続化 | 整合性 | マイグレーション |
|---|---|---|---|
| WorkQueueジョブ | JetStream Stream（PYOCO_WORK, WorkQueue） | runは1subjectにのみpublish（重複投入しない） | schema_version導入を将来検討（付録） |
| run最新状態 | JetStream KV（pyoco_runs, history=1） | terminal化後にACK（at-least-once） | 追加フィールドは後方互換（未知フィールド無視） |
| worker registry | JetStream KV（pyoco_workers, history=1） | `last_seen_at` と disconnect timeout から `DISCONNECTED` を導出。`STOPPED_GRACEFUL` は保持する | 追加フィールドは後方互換で拡張 |
| DLQ | JetStream Stream（PYOCO_DLQ, Limits） | 診断用。runの真実はKV | retention上限で運用 |
| wheel registry | JetStream Object Store（pyoco_wheels） | wheelタグをmeta headerへ保持し、worker同期判定に利用する | header追加は後方互換で拡張 |
| wheel履歴 | JetStream KV（pyoco_wheel_history, key: `<ts_ms>_<event_id>`） | upload/delete と source/actor を監査できる | ttl設定で保持期間を制御 |
| wheel同期マニフェスト | workerローカルファイル（`.pyoco/wheels/.installed.json`） | `nuid` 差分で再インストール判定。レジストリ削除時はローカルも除去 | manifest破損時は空として再同期（best-effort） |

#6.設定：場所／キー／既定値
| 項目 | 場所 | キー | 既定値 |
|---|---|---|---|
| NATS URL | env | `PYOCO_NATS_URL` | `nats://127.0.0.1:4222` |
| Work subject prefix | env | `PYOCO_WORK_SUBJECT_PREFIX` | `pyoco.work` |
| Default tag | env | `PYOCO_DEFAULT_TAG` | `default` |
| Runs KV bucket | env | `PYOCO_RUNS_KV_BUCKET` | `pyoco_runs` |
| Workers KV bucket | env | `PYOCO_WORKERS_KV_BUCKET` | `pyoco_workers` |
| Workers KV TTL | env | `PYOCO_WORKERS_KV_TTL_SEC` | `15.0`（v0互換） |
| Worker disconnect timeout | env | `PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC` | `20.0` |
| Run heartbeat | env | `PYOCO_RUN_HEARTBEAT_INTERVAL_SEC` | `1.0` |
| Worker heartbeat | env | `PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC` | `5.0` |
| Cancel grace period | env | `PYOCO_CANCEL_GRACE_PERIOD_SEC` | `30.0` |
| Consumer AckWait | env | `PYOCO_CONSUMER_ACK_WAIT_SEC` | `30.0` |
| Consumer MaxDeliver | env | `PYOCO_CONSUMER_MAX_DELIVER` | `20` |
| Consumer MaxAckPending | env | `PYOCO_CONSUMER_MAX_ACK_PENDING` | `200` |
| Ack progress interval | env | `PYOCO_ACK_PROGRESS_INTERVAL_SEC` | `10.0`（AckWait未満） |
| DLQ stream | env | `PYOCO_DLQ_STREAM` | `PYOCO_DLQ` |
| DLQ subject prefix | env | `PYOCO_DLQ_SUBJECT_PREFIX` | `pyoco.dlq` |
| DLQ publish execution error | env | `PYOCO_DLQ_PUBLISH_EXECUTION_ERROR` | `true` |
| Snapshot size cap | env | `PYOCO_MAX_RUN_SNAPSHOT_BYTES` | `262144` |
| Wheel Object Store bucket | env | `PYOCO_WHEEL_OBJECT_STORE_BUCKET` | `pyoco_wheels` |
| Wheel max bytes | env | `PYOCO_WHEEL_MAX_BYTES` | `536870912` |
| Wheel sync enabled | env | `PYOCO_WHEEL_SYNC_ENABLED` | `0`（`0|1`） |
| Wheel sync dir | env | `PYOCO_WHEEL_SYNC_DIR` | `.pyoco/wheels` |
| Wheel sync interval | env | `PYOCO_WHEEL_SYNC_INTERVAL_SEC` | `10.0` |
| Wheel install timeout | env | `PYOCO_WHEEL_INSTALL_TIMEOUT_SEC` | `180.0` |
| Wheel history KV bucket | env | `PYOCO_WHEEL_HISTORY_KV_BUCKET` | `pyoco_wheel_history` |
| Wheel history TTL | env | `PYOCO_WHEEL_HISTORY_TTL_SEC` | `7776000`（90日） |
| Workflow YAML size cap | env | `PYOCO_WORKFLOW_YAML_MAX_BYTES` | `262144` |
| Dashboard locale | env | `PYOCO_DASHBOARD_LANG` | `auto`（`auto|ja|en`） |
| Dotenv auto load | env | `PYOCO_LOAD_DOTENV` | `1`（`0|1`） |
| Dotenv file path | env | `PYOCO_ENV_FILE` | `.env` |
| Log level | env | `PYOCO_LOG_LEVEL` | `INFO` |
| Log format | env | `PYOCO_LOG_FORMAT` | `json` |
| Log UTC | env | `PYOCO_LOG_UTC` | `true` |
| Log traceback | env | `PYOCO_LOG_INCLUDE_TRACEBACK` | `true` |

#7.依存と拡張点（Extensibility）
| 依存 | 目的 | 拡張点 |
|---|---|---|
| JetStream subject namespace | テナント/環境分離 | `pyoco.<tenant>.work.<tag>` 等のnamespace化 |
| HTTP I/F | 利用者向け契約 | Authn/Authz、cancel waitモードの強化（段階拡張） |
| wheel registry I/F | 依存配布契約 | 署名検証/承認フロー/配布チャネル分離（将来） |
| run watch stream | GUIの詳細監視 | server push最適化（初期はSSE、将来はWS併用） |
| Snapshot schema | 可視化 | event stream（履歴/ログ）導入でKV肥大化を回避（将来） |

#7.5.依存関係（DI）
（テキスト図示）
```
HTTP Gateway -> NatsBackendConfig -> NATS JetStream
PyocoNatsWorker -> NatsBackendConfig -> NATS JetStream
PyocoNatsWorker -> flow_resolver -> Pyoco Flow（通常の `POST /runs` 経路）
PyocoNatsWorker -> workflow_yaml（flow.yaml） -> Pyoco Flow（`POST /runs/yaml` 経路）
HTTP Gateway -> runs KV -> cancel flag（`POST /runs/{run_id}/cancel` 経路）
HTTP Gateway -> wheel Object Store（`/wheels*`）
PyocoNatsWorker -> wheel Object Store -> local wheel dir -> pip install（同期経路）
Pyoco Engine -> TraceBackend(NatsKvTraceBackend) -> JetStream KV
```

| クラス | コンストラクタDI（依存先） | 目的 |
|---|---|---|
| HTTP Gateway | NatsBackendConfig（envから生成） | 資源名/既定の集約 |
| PyocoNatsWorker | NatsBackendConfig, flow_resolver | 実行と状態更新 |
| NatsKvTraceBackend | asyncio loop, KV, RunContext | thread-safeにKVへflush |
| Client CLI | PyocoHttpClient | run操作のCLI I/F |

#8.エラーハンドリング設計（冪等性/リトライ/タイムアウト/部分失敗）
| 事象 | 発生場所 | 発生原因 | 方針 | 備考 |
|---|---|---|---|---|
| 入力不正 | HTTP Gateway | 422 | 422で返す | ERR-PYOCO-0002 |
| CLI引数不正 | CLI（client/worker/server） | 必須不足、JSON形式不正、resolver指定不正 | 非0終了 + stderrに修正例を表示 | ERR-PYOCO-0018 |
| 一覧クエリ不正 | HTTP Gateway | cursor/updated_after等が不正 | 422で返す | ERR-PYOCO-0017 |
| workers入力不正 | HTTP Gateway | `scope`/`state`/`include_hidden`/`hidden` が不正 | 422で返す | ERR-PYOCO-0019 |
| worker不存在 | HTTP Gateway | `PATCH /workers/{worker_id}` の対象が無い | 404で返す | ERR-PYOCO-0020 |
| wheelバージョン不整合 | HTTP Gateway | `POST /wheels` で同一パッケージの同一/過去バージョンを登録しようとした | 409で返す | ERR-PYOCO-0022 |
| wheel不存在 | HTTP Gateway | `GET/DELETE /wheels/{wheel_name}` の対象が無い | 404で返す | ERR-PYOCO-0023 |
| cancel収束タイムアウト | Worker | cancel要求後も `CANCELLED` へ遷移しない | `ERR-PYOCO-0021` を記録し、運用で再判断する | best-effort |
| wheel同期失敗 | Worker | Object Store取得失敗、pip install失敗、ローカルI/O失敗 | ログ記録して次回同期で再試行 | ERR-PYOCO-0024（best-effort） |
| NATS不可（HTTP） | HTTP Gateway | connect/KV/publish失敗 | 503で返す | ERR-PYOCO-0003 |
| run_id不存在 | HTTP Gateway | KV not found | 404で返す | ERR-PYOCO-0005 |
| 不正ジョブ | Worker | JSON不正/必須欠落 | DLQ+TERM（再配送しない） | reason=invalid_job |
| flow解決不可 | Worker | flow_resolverがKeyError | FAILEDを記録してACK、DLQ（既定ON） | reason=flow_not_found |
| 実行失敗 | Worker | Engine例外 | FAILEDを記録してACK、DLQ（既定ON） | reason=execution_error |
| KV一次障害 | Worker | KV put失敗等 | NAK(delay)で再配送 | 既定delay=2s |
| 長時間run再配送 | Worker | AckWait超過 | in_progress ACKを定期送信 | interval < AckWait |

#9.セキュリティ設計（秘密情報・最小権限・ログ方針）
| 観点 | 方針 |
|---|---|
| NATS認証/TLS | 内部面（Server-Worker）でNATS側の認証/TLSを利用する（HTTP利用者には露出しない）。 |
| HTTP認証/認可 | 既定は無認証（簡単に始める）。opt-in で `X-API-Key` による認証を有効化できる（`docs/spec.md` REQ-0016/0017）。 |
| 最小権限 | worker/gatewayは必要なStream/KV/Object Storeへの権限のみ付与する。 |
| wheel供給チェーン | wheelは実行コードを含むため、配布主体を制限し、必要に応じてdigest/署名検証の導入余地を確保する。 |
| ログ方針 | 機密（params等）が含まれ得るため、DLQのpayloadやログ出力は運用で注意する。 |

#10.観測性（ログ/診断：doctor/status/debug）
| 種別 | 内容 | 出力先 |
|---|---|---|
| health | Gatewayの生存 | `GET /health` |
| snapshot | runの最新状態 | `GET /runs/{run_id}` / `GET /runs` |
| watch | run状態の継続更新（best-effort） | `GET /runs/{run_id}/watch`（SSE） |
| worker registry | worker状態（RUNNING/IDLE/STOPPED_GRACEFUL/DISCONNECTED）と表示制御 | `GET /workers` / `PATCH /workers/{worker_id}` |
| metrics | 運用向けメトリクス（best-effort） | `GET /metrics` |
| wheel registry | wheel一覧/登録/取得/削除 | `GET/POST /wheels`, `GET/DELETE /wheels/{wheel_name}` |
| wheel history | wheel配布履歴の参照 | `GET /wheels/history` |
| wheel sync status | workerの同期/インストール成否と互換外skip | `GET /workers` の `wheel_sync` / workerログ（`wheel sync failed` など） |
| DLQ | 失敗診断 | JetStream（PYOCO_DLQ） |
| doctor/status/debug | pyoco-server専用のdoctor/status/debugは未提供。NATS運用診断は `nats-bootstrap status/doctor` を使う | CLI（`uv run nats-bootstrap status` / `uv run nats-bootstrap doctor`） |

### ログ仕様（提案：JSON Lines）
v0では、運用上の診断容易性を優先し、HTTP Gateway / worker は stdout に JSON Lines を出力する。

基本方針：
- 1行=1 JSON（JSON Lines）。
- エラー時は必ず「元例外（オリジナルの例外）」を `exc_*` として記録する（例外クラス/メッセージ/トレースバック）。
- どのプログラム/どの場所かが追えるように、service/logger/ファイル/行/関数を必ず含める。
- 可能な範囲で run コンテキスト（run_id, flow_name, tag, worker_id）と、仕様ID（err_id, msg_id）を付与する。

必須フィールド（推奨）：
- `ts`：時刻（UTC推奨）
- `service`：`pyoco-server:http` / `pyoco-server:worker`
- `level`：INFO/ERROR等
- `logger`：logger名
- `message`：メッセージ
- `pathname` / `lineno` / `func`：ログ発生箇所

エラー時の必須フィールド（推奨）：
- `exc_type`：例外クラス名
- `exc_message`：例外メッセージ
- `exc_traceback`：トレースバック（全文）
- `exc_origin`：例外発生元（file/line/func のヒント）

コンテキストフィールド（任意）：
- `run_id`, `flow_name`, `tag`, `worker_id`
- `err_id`, `msg_id`, `reason`

## 例外ハンドリング方針（UI/ユースケース層）
| UC | 例外 | 表示/通知 | エラーID/コード方針 | 関連spec ERR-ID |
|---|---|---|---|---|
| UC-1 | 入力不正 | 422（invalid request） | MSG-PYOCO-0002 | ERR-PYOCO-0002 |
| UC-1 | NATS不可 | 503（nats unavailable） | MSG-PYOCO-0003 | ERR-PYOCO-0003 |
| UC-2/3 | run not found | 404（run not found） | MSG-PYOCO-0005 | ERR-PYOCO-0005 |
| UC-4 | 一覧クエリ不正 | 422（invalid list query） | MSG-PYOCO-0017 | ERR-PYOCO-0017 |
| UC-9/13 | workers入力不正 | 422（invalid workers request） | MSG-PYOCO-0019 | ERR-PYOCO-0019 |
| UC-13 | worker not found | 404（worker not found） | MSG-PYOCO-0020 | ERR-PYOCO-0020 |
| UC-14 | run cancel | 404/503/401/403（条件に応じる） | MSG-PYOCO-0005/0003/0014/0015 | ERR-PYOCO-0005/0003/0014/0015 |
| UC-14 | cancel timeout | workerログで通知（best-effort） | MSG-PYOCO-0021 | ERR-PYOCO-0021 |
| UC-15 | wheel version conflict | 409（same/older version is rejected） | MSG-PYOCO-0022 | ERR-PYOCO-0022 |
| UC-15 | wheel not found | 404（wheel not found） | MSG-PYOCO-0023 | ERR-PYOCO-0023 |
| UC-15 | wheel sync failed | workerログで通知（best-effort） | MSG-PYOCO-0024 | ERR-PYOCO-0024 |
| UC-2/3/4/10 | NATS不可 | 503 | MSG-PYOCO-0003 | ERR-PYOCO-0003 |
| UC-10 | run not found | 404（run not found） | MSG-PYOCO-0005 | ERR-PYOCO-0005 |
| UC-12 | CLI引数不正 | 非0終了 + stderr | MSG-PYOCO-0018 | ERR-PYOCO-0018 |
| UC-5 | 重複実行 | v0は許容（at-least-once） | 明示的に設計上の前提 | （spec付録E） |
| UC-9 | DISCONNECTED表示 | `last_seen_at` 超過で状態導出 | worker状態として表示し、FAILEDとは混同しない | （spec付録G） |

#11.テスト設計（単体/統合/E2E、モック方針）
| 種別 | 対象 | 方針 |
|---|---|---|
| 単体 | スナップショットコンパクション | `compact_run_snapshot` の上限/切り捨てを検証する（`tests/test_snapshot_compaction.py`）。 |
| 統合/E2E | HTTP投入→worker実行→HTTP参照 | JetStream有効NATSを起動し、契約（include, DLQ, ACK/NAK等）を検証する（`tests/test_nats_e2e.py`）。 |
| 統合 | 長時間run | in_progress ACKで再配送しないことを検証する（E2Eで追加）。 |
| 統合/E2E | GUI向け一覧差分 | `GET /runs` の cursor / updated_after / sha256 filter を検証する。 |
| 統合/E2E | run監視SSE | `GET /runs/{run_id}/watch` で snapshot イベント継続受信と再接続を検証する。 |
| 統合/E2E | run取消 | `POST /runs/{run_id}/cancel` で `CANCELLING -> CANCELLED` を検証し、terminalへの冪等cancelも検証する。 |
| 統合/E2E | workers API（状態/表示制御） | `GET /workers` の `scope/state/include_hidden` と `PATCH /workers/{worker_id}` の hide/unhide を検証する。 |
| 統合/E2E | worker停止種別表示 | graceful停止とheartbeat途絶で `STOPPED_GRACEFUL` / `DISCONNECTED` が区別されることを検証する。 |
| 統合/E2E | wheel registry / worker同期 | `POST/GET/DELETE /wheels` と、同一パッケージの同一/過去バージョン拒否、workerタグ一致かつ最新版のみ同期されることを検証する（`tests/test_wheel_registry.py`）。 |
| 単体 | CLI引数/出力 | `pyoco-client` / `pyoco-worker` の引数検証と出力形式を検証する。 |

#12.配布・実行形態（インストール/更新/互換性/破壊的変更）
- 実行形態：
  - HTTP Gateway：uvicornで起動（`pyoco_server.http_api:create_app --factory`）
  - Worker：Pythonプロセスとして起動（例：`examples/run_worker.py` 等）
  - 依存配布：wheel registry（Object Store）を使い、workerが差分同期して更新する（opt-in）
  - NATS運用：`nats-bootstrap` を利用して単体/クラスタ運用を行う
- 更新方針：
  - on-wire契約（HTTP/NATS/KV/DLQ）は `docs/spec.md` を正とし、原則は後方互換（追加はOK、破壊は慎重）。
  - wheel同期は起動時/次回poll前に実行し、実行中runの途中では更新しない。
  - 0.xでは破壊的変更が起こり得るため、明示する。
- `nats-bootstrap` 連携の運用制約（現行）：
  - `backup/restore` は `nats` CLI 前提（`--nats-cli-path` で上書き可能）
  - `leave` は controller endpoint（`nats-bootstrap controller start` のendpoint）と `--confirm` が必要
  - `leave --stop-anyway` は controller 不達時の成功扱いを許容するが、MVPではローカル停止を実施しない
  - `controller` は現状 `start` 操作のみ
  - `down` は `--confirm` + `./nats-server.pid` を前提にする

#13.CLI：コマンド体系／引数／出力／exit code
提供コマンド（v0）：
- `pyoco-server`（HTTP Gateway起動）
- `pyoco-worker`（worker起動）
- `pyoco-client`（run運用CLI）
- `pyoco-server-admin`（API key管理）
- `nats-bootstrap`（NATS運用CLI）

`pyoco-client` の主なsubcommand：
- `submit` / `submit-yaml` / `get` / `tasks` / `list` / `list-vnext` / `watch` / `cancel` / `workers` / `metrics` / `wheels` / `wheel-history` / `wheel-upload` / `wheel-delete`

CLI UX方針（v0.4実装）：
- helpで「最小実行例」を示す
- 入力不正時は非0終了 + stderrに修正可能な形式を表示する
- YAML-first運用を優先し、`submit-yaml` を主要導線として維持する
- `submit` は `--params-file` / `--params` / `--param key=value` を併用可能（後勝ち）
- `list` / `list-vnext` は `--output json|table`
- `watch` は `--output json|status`
- `cancel` は `--run-id` を必須にし、必要に応じて `--wait --timeout-sec` を提供する
- `wheel-upload` は `--wheel-file` を必須にし、任意で `--tags` / `--replace` / `--no-replace` を提供する
- `wheel-history` は `--limit` / `--wheel-name` / `--action upload|delete` を提供する
- `pyoco-worker` は `--wheel-sync` / `--wheel-sync-dir` / `--wheel-sync-interval-sec` / `--wheel-install-timeout-sec` を提供する
- `nats-bootstrap` は `up/join/status/doctor/backup/restore/leave/down/service/controller` を提供する（現行の controller は `start` のみ）

exit code（方針）：
- `0`：成功
- `1`：利用者が修正可能な失敗（引数不正、入力形式不正、HTTP呼び出し失敗）
- `130`：SIGINT等で中断
