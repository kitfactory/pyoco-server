# architecture.md（必ず書く：最新版）
#1.アーキテクチャ概要（構成要素と責務）
本システムは、プロトコル境界を明確に2面に分ける。

- Client <-> Server：HTTP
  - Pyoco利用者はHTTPのみを使い、NATSを意識しない（資格情報も持たない）。
- Server <-> Worker：NATS JetStream
  - WorkQueue（run投入）と KV（最新状態可視化）と DLQ（診断）を JetStream に集約する。

構成要素：
- HTTP Gateway（Server）
  - HTTP APIを提供（run投入/参照）
  - JetStreamリソースの確認/作成（Stream/KV/DLQ）
  - run投入の原子性（KV初期化 + publish 成功でのみ成功応答）
  - run参照（KV読み出し）と任意のworker生死付加（TTL-KV）
  - （opt-in）HTTP API key 認証（`X-API-Key`）と tenant attribution（runへ帰属を刻む）
- Worker
  - tag 単位の durable consumer から pull でジョブを取得（複数tagは OR）
  - Pyoco Engine で run を実行し、Traceを KV スナップショットへ反映
  - terminal スナップショットを書いてから ACK（at-least-once）
  - 長時間runは JetStream in_progress ACK を定期送信して意図しない再配送を防ぐ
  - 失敗分類に応じて ACK/NAK/TERM + DLQ publish（best-effort）
- Admin CLI（運用：API key 管理）
  - API key の発行/一覧/失効を行い、JetStream KVへ保存する（平文キーは保存しない）
- NATS JetStream
  - Stream：PYOCO_WORK（WorkQueue）
  - Stream：PYOCO_DLQ（診断用）
  - KV：pyoco_runs（最新スナップショット）
  - KV（TTL）：pyoco_workers（worker生死）
  - KV：pyoco_auth（API key レコード）

#2.concept のレイヤー構造との対応表
（テキスト図示）
```
[Pyoco Client / HTTP Client] -> [HTTP Gateway] -> [NATS JetStream (Stream/KV/DLQ)] <- [Worker + Pyoco Engine]
```

| conceptレイヤー | 対応コンポーネント | 主な責務 |
|---|---|---|
| プレゼンテーション層 | PyocoHttpClient / 外部HTTPクライアント | HTTPでrun投入/参照 |
| アプリケーション層 | HTTP Gateway（ユースケース実装） | 原子性・参照時の付加情報 |
| インフラ層 | JetStream（Stream/KV/DLQ） | 分散キュー/最新状態/診断 |
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
| `GET /runs` | KV keysを走査して一覧を返す（best-effort） | query：status?: string, flow?: string, tag?: string, include?: array<string>, limit?: int(1..200、既定50)（opt-in：HTTP auth有効時は header `X-API-Key` 必須。結果は同一tenantのみに限定） | JSON：array<RunSummary or RunSnapshot> | ERR-PYOCO-0014（401）, ERR-PYOCO-0015（403）, ERR-PYOCO-0003（503） |

#### UC-7: 稼働状態を確認する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /health` | 稼働確認 | - | JSON：status: "ok" | ERR-PYOCO-0001（到達不可等） |

#### UC-8: メトリクスを取得する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /metrics` | 運用向けメトリクスを返す（best-effort） | - | text/plain（Prometheus互換）：pyoco_runs_total/pyoco_workers_alive_total/pyoco_dlq_messages_total | ERR-PYOCO-0003（NATS不可） |

#### UC-9: worker一覧を取得する
| 操作/API | 役割 | 入力（型/主要フィールド/値範囲） | 出力（型/主要フィールド） | 例外（発生条件） |
|---|---|---|---|---|
| `GET /workers` | TTL-KVからworker一覧を返す（best-effort） | - | JSON：array<{worker_id, heartbeat_at, tags}> | ERR-PYOCO-0003（NATS不可） |

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
| `kv.delete(key)` | KV削除 | key: string | - | best-effort（ERR-PYOCO-0004） |
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
| （各フィールド） | 文字列/数値/真偽 | NATS/JetStream資源名、heartbeat間隔、consumer既定、DLQ設定、スナップショット上限等 | docs/spec.md 付録Iに準拠 | - |

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
| app | FastAPI | routes: /health,/runs,... |

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

#### 依存先I/F（最小契約）
| 依存先 | 最小メソッド | 目的 |
|---|---|---|
| flow_resolver | `__call__(flow_name) -> Flow` / `KeyError` | flow解決（ERR-PYOCO-0006） |
| JetStream KV | `put/get/keys/delete` | runスナップショット/worker生死 |
| JetStream publish | `publish(subject,payload,stream)` | WorkQueue/DLQ |
| JetStream msg | `ack/nak/term/in_progress` | ディスポジション/長時間run |

### 型定義（入出力/DTOの主要フィールド）
| 型 | 主要フィールド（値範囲/制約） | 用途 |
|---|---|---|
| RunSubmitRequest | flow_name: string(1+), params: object, tag?: string(`[A-Za-z0-9_-]+`、`.`禁止), tags?: array<string> | `POST /runs` |
| RunSubmitYamlRequest | workflow: file(YAML), flow_name: string(1+), tag?: string(`[A-Za-z0-9_-]+`、`.`禁止) | `POST /runs/yaml` |
| RunSnapshot | run_id: uuid, flow_name: string, status: enum, params: object, tasks: object, task_records: object, heartbeat_at: number, updated_at: number, error?: string/null, worker_id?: string, workflow_yaml_sha256?: string/null, workflow_yaml_bytes?: number/null | `GET /runs/{id}` / 一覧 |
| RunSummary | run_id, flow_name?, tag?, tags?, status, updated_at, heartbeat_at?, worker_id?, error? | `GET /runs` 既定の軽量返却 |
| WorkerLiveness | worker_id: string, heartbeat_at: number, tags?: array<string> | worker生死（TTL-KV） |
| DlqMessage | timestamp: number, reason: string, error?: string/null, run_id?, flow_name?, tag?, tags?, worker_id?, num_delivered?, subject? | DLQ診断 |
※List/Arrayは要素型を必ず明記する（例: tags: array<string>）

#4.主要フロー設計（成功/失敗）
| フロー | 成功条件 | 失敗条件 | 例外時の動作 |
|---|---|---|---|
| run投入（HTTP→KV→publish） | KV初期化とpublishが成功し200返却 | NATS不可、入力不正 | 422/503。publish失敗後はKV delete（best-effort） |
| run実行（Worker pull→Pyoco→KV→ACK） | terminalスナップショットを書いてACK | 不正ジョブ、flow解決不可、実行失敗、KV一次障害 | invalid_jobはDLQ+TERM。flow_not_found/実行失敗はFAILED記録+ACK（DLQは既定ON）。KV一次障害はNAK(delay) |
| run参照（HTTP→KV→付加情報） | KVスナップショットを返す | run_id不存在、NATS不可 | 404/503。worker生死付加は任意でbest-effort |
| 一覧（HTTP→KV keys→get→sort） | best-effortで一覧返却 | NATS不可 | 503。順序はupdated_atでbest-effort |

#5.データ設計（永続化・整合性・マイグレーション）
| データ | 永続化 | 整合性 | マイグレーション |
|---|---|---|---|
| WorkQueueジョブ | JetStream Stream（PYOCO_WORK, WorkQueue） | runは1subjectにのみpublish（重複投入しない） | schema_version導入を将来検討（付録） |
| run最新状態 | JetStream KV（pyoco_runs, history=1） | terminal化後にACK（at-least-once） | 追加フィールドは後方互換（未知フィールド無視） |
| worker生死 | JetStream KV（pyoco_workers, TTL） | TTL切れ＝server視点で非alive | TTL値はenvで調整 |
| DLQ | JetStream Stream（PYOCO_DLQ, Limits） | 診断用。runの真実はKV | retention上限で運用 |

#6.設定：場所／キー／既定値
| 項目 | 場所 | キー | 既定値 |
|---|---|---|---|
| NATS URL | env | `PYOCO_NATS_URL` | `nats://127.0.0.1:4222` |
| Work subject prefix | env | `PYOCO_WORK_SUBJECT_PREFIX` | `pyoco.work` |
| Default tag | env | `PYOCO_DEFAULT_TAG` | `default` |
| Runs KV bucket | env | `PYOCO_RUNS_KV_BUCKET` | `pyoco_runs` |
| Workers KV bucket | env | `PYOCO_WORKERS_KV_BUCKET` | `pyoco_workers` |
| Workers KV TTL | env | `PYOCO_WORKERS_KV_TTL_SEC` | `15.0` |
| Run heartbeat | env | `PYOCO_RUN_HEARTBEAT_INTERVAL_SEC` | `1.0` |
| Worker heartbeat | env | `PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC` | `5.0` |
| Consumer AckWait | env | `PYOCO_CONSUMER_ACK_WAIT_SEC` | `30.0` |
| Consumer MaxDeliver | env | `PYOCO_CONSUMER_MAX_DELIVER` | `20` |
| Consumer MaxAckPending | env | `PYOCO_CONSUMER_MAX_ACK_PENDING` | `200` |
| Ack progress interval | env | `PYOCO_ACK_PROGRESS_INTERVAL_SEC` | `10.0`（AckWait未満） |
| DLQ stream | env | `PYOCO_DLQ_STREAM` | `PYOCO_DLQ` |
| DLQ subject prefix | env | `PYOCO_DLQ_SUBJECT_PREFIX` | `pyoco.dlq` |
| DLQ publish execution error | env | `PYOCO_DLQ_PUBLISH_EXECUTION_ERROR` | `true` |
| Snapshot size cap | env | `PYOCO_MAX_RUN_SNAPSHOT_BYTES` | `262144` |
| Workflow YAML size cap | env | `PYOCO_WORKFLOW_YAML_MAX_BYTES` | `262144` |
| Log level | env | `PYOCO_LOG_LEVEL` | `INFO` |
| Log format | env | `PYOCO_LOG_FORMAT` | `json` |
| Log UTC | env | `PYOCO_LOG_UTC` | `true` |
| Log traceback | env | `PYOCO_LOG_INCLUDE_TRACEBACK` | `true` |

#7.依存と拡張点（Extensibility）
| 依存 | 目的 | 拡張点 |
|---|---|---|
| JetStream subject namespace | テナント/環境分離 | `pyoco.<tenant>.work.<tag>` 等のnamespace化 |
| HTTP I/F | 利用者向け契約 | Authn/Authz、SSE watch、cancel等（将来） |
| Snapshot schema | 可視化 | event stream（履歴/ログ）導入でKV肥大化を回避（将来） |

#7.5.依存関係（DI）
（テキスト図示）
```
HTTP Gateway -> NatsBackendConfig -> NATS JetStream
PyocoNatsWorker -> NatsBackendConfig -> NATS JetStream
PyocoNatsWorker -> flow_resolver -> Pyoco Flow（通常の `POST /runs` 経路）
PyocoNatsWorker -> workflow_yaml（flow.yaml） -> Pyoco Flow（`POST /runs/yaml` 経路）
Pyoco Engine -> TraceBackend(NatsKvTraceBackend) -> JetStream KV
```

| クラス | コンストラクタDI（依存先） | 目的 |
|---|---|---|
| HTTP Gateway | NatsBackendConfig（envから生成） | 資源名/既定の集約 |
| PyocoNatsWorker | NatsBackendConfig, flow_resolver | 実行と状態更新 |
| NatsKvTraceBackend | asyncio loop, KV, RunContext | thread-safeにKVへflush |

#8.エラーハンドリング設計（冪等性/リトライ/タイムアウト/部分失敗）
| 事象 | 発生場所 | 発生原因 | 方針 | 備考 |
|---|---|---|---|---|
| 入力不正 | HTTP Gateway | 422 | 422で返す | ERR-PYOCO-0002 |
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
| 最小権限 | worker/gatewayは必要なStream/KVへの権限のみ付与する。 |
| ログ方針 | 機密（params等）が含まれ得るため、DLQのpayloadやログ出力は運用で注意する。 |

#10.観測性（ログ/診断：doctor/status/debug）
| 種別 | 内容 | 出力先 |
|---|---|---|
| health | Gatewayの生存 | `GET /health` |
| snapshot | runの最新状態 | `GET /runs/{run_id}` / `GET /runs` |
| worker liveness | workerの生死 | TTL-KV（HTTP応答に任意付加） |
| metrics | 運用向けメトリクス（best-effort） | `GET /metrics` |
| workers | worker一覧（best-effort） | `GET /workers` |
| DLQ | 失敗診断 | JetStream（PYOCO_DLQ） |
| doctor/status/debug | 該当なし（v0では専用コマンド未提供） | - |

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
| UC-2/3/4 | NATS不可 | 503 | MSG-PYOCO-0003 | ERR-PYOCO-0003 |
| UC-5 | 重複実行 | v0は許容（at-least-once） | 明示的に設計上の前提 | （spec付録E） |
| UC-2 | STALE表示 | statusはRUNNINGのまま | UI側の解釈（FAILEDにしない） | （spec付録G） |

#11.テスト設計（単体/統合/E2E、モック方針）
| 種別 | 対象 | 方針 |
|---|---|---|
| 単体 | スナップショットコンパクション | `compact_run_snapshot` の上限/切り捨てを検証する（`tests/test_snapshot_compaction.py`）。 |
| 統合/E2E | HTTP投入→worker実行→HTTP参照 | JetStream有効NATSを起動し、契約（include, DLQ, ACK/NAK等）を検証する（`tests/test_nats_e2e.py`）。 |
| 統合 | 長時間run | in_progress ACKで再配送しないことを検証する（E2Eで追加）。 |

#12.配布・実行形態（インストール/更新/互換性/破壊的変更）
- 実行形態：
  - HTTP Gateway：uvicornで起動（`pyoco_server.http_api:create_app --factory`）
  - Worker：Pythonプロセスとして起動（例：`examples/run_worker.py` 等）
- 更新方針：
  - on-wire契約（HTTP/NATS/KV/DLQ）は `docs/spec.md` を正とし、原則は後方互換（追加はOK、破壊は慎重）。
  - 0.xでは破壊的変更が起こり得るため、明示する。

#13.CLI：コマンド体系／引数／出力／exit code
Phase 3（v0.3 opt-in）では、API key 管理用の最小CLIを提供する。

- 目的：API key の発行/一覧/失効（保存先は JetStream KV、平文キーは保存しない）
- 実行例：
  - `python -m pyoco_server.admin_cli api-key create --tenant <tenant_id>`
  - `python -m pyoco_server.admin_cli api-key list`
  - `python -m pyoco_server.admin_cli api-key revoke --key-id <key_id>`

※HTTP Gateway / worker の起動例は `docs/quickstart.md` と `examples/` を参照。
