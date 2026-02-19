# concept.md（必ず書く：最新版）
#1.概要（Overview）（先頭固定）
- 作るもの（What）：Pyoco **本体ではなく**、Pyoco のワークフロー実行（run）を HTTP（Client-Server）と NATS JetStream（Server-Worker）で分散実行するための軽量バックエンド。
- 解決すること（Why）：Pyoco 利用者が NATS を意識せずに「run投入」「run/タスク状態参照」をできるようにし、導入と運用の負担を最小化する。
- できること（主要機能の要約）：HTTPでrun投入、KVスナップショットで状態参照、タスク状態参照、一覧/フィルタ、worker運用可視化（状態区別・手動hide・表示制御）、DLQで診断、長時間runの再配送防止（in_progress ACK）と心拍、運用向けエンドポイント（/metrics, /workers）、GUI向けの最小状態管理I/F（一覧差分取得・run監視SSE）、CLI（server/worker/client/admin）による運用操作、run取消（cancel、best-effort）、wheelレジストリとworkerタグ一致での依存配布、wheel配布履歴（アップロード元情報付き）の参照。
- 使いどころ（When/Where）：単一組織の社内システムで、Pyoco flow を複数ノード（複数worker）で実行したいが、DBや巨大オーケストレータは持ち込みたくない小規模チーム。
- 成果物（Outputs）：HTTP Gateway（FastAPI）、Worker（Pyoco Engine実行）、JetStreamリソース定義（Stream/KV/DLQ）、PythonライブラリAPI、Quickstart/例、運用向け最小GUI（read-only）。
- 前提（Assumptions）：NATS JetStream が利用可能（信頼性の基盤）、実行保証は at-least-once（重複実行あり得る）、外部DBは前提にしない（JetStream Stream/KVで完結）、サーバー内スケジューラは持たない（トリガーは外側で行う）、運用は `nats-bootstrap` 連携を中核に置く、厳格マルチテナント分離を主目的にしない。

#2.ユーザーの困りごと（Pain）
- 分散実行したいが、NATS/JetStreamの運用やAPI詳細をアプリ利用者に持ち込ませたくない。
- 既存のフル機能オーケストレータ（DAGスケジューリング、監査DB、巨大UI等）は導入が重く、MVPでは過剰。
- runの状態（RUNNINGか、どこまで進んだか）を軽く問い合わせたい（重い履歴DBなしで）。
- 長時間runやworker障害時に「詰まり」にくく、診断可能にしたい（無限再配送の回避、DLQ）。
- 運用時にCLI/curlだけで追跡するのは負担が高く、GUIで一覧・詳細を継続監視したい。
- CLIはあるが、入力形式（JSON直書き）やエラー表示が実装者向けで、初見ユーザーには扱いづらい。
- workerが「正常停止した」のか「途中で途絶した」のかが分からないと、障害判断と運用判断を誤りやすい。
- 役目を終えたworkerを表示から外せないと、運用画面のノイズが増えて監視効率が落ちる。
- 新しいタスクを追加するたびに、各workerでライブラリを個別インストールする運用は手間が大きく、更新漏れを起こしやすい。
- 単体NATSとクラスタNATSで手順が分断されると、少人数運用でDay-2（増設/縮退/診断/退避/復旧）が回しづらい。

#3.ターゲットと前提環境（詳細）
- ターゲット：
  - Pyoco利用者（HTTPでrun投入/参照したい）
  - 運用者（NATS/workerを立ち上げ、落ちても復旧できる形にしたい）
  - 単一組織の少人数運用チーム（同一CLI手順でDay-2運用を回したい）
- 前提環境：
  - NATS JetStream 有効な NATS（単体〜クラスタ想定）
  - HTTP Gateway は水平スケール可能（状態の真実は JetStream 側）
  - worker はタグ（tag）単位でキューを pull し、複数タグは OR で扱う
  - `nats-bootstrap` を併用し、`up/join/status/doctor/backup/restore/leave/down/service` を運用導線として使う
- Fitするケース：
  - 1チームで運用する社内基盤
  - Docker中心で、導入コストを抑えて分散実行基盤を持ちたい
  - 監視/診断を CLI と最小GUIで回したい
- Fitしないケース：
  - 厳格マルチテナント（強い境界制御や組織間分離が必須）
  - 強い監査分離（組織横断での高度な統制証跡が必須）
  - 超大規模SLA（高度な公平制御・隔離制御・大規模オーケストレーション）

#4.採用する技術スタック（採用理由つき）
- Python：Pyoco本体と親和性が高く、worker実装を最小で済ませられる。
- FastAPI（HTTP Gateway）：入力バリデーションと実装の簡潔さを両立し、HTTP契約を薄く保てる。
- NATS JetStream（Server-Worker）：WorkQueue + KV + TTL-KV + DLQ を単一基盤で扱え、外部DB不要で運用が軽い。
- httpx（HTTP client）：Pyoco利用者がHTTPで扱えるクライアントを提供しやすい。

#5.機能一覧（Features）
| ID | 機能 | 解決するPain | 対応UC |
|---|---|---|---|
| F-1 | run投入（HTTP→JetStream publish） | 利用者にNATSを意識させず分散実行したい | UC-1 |
| F-2 | runスナップショット参照（KV→HTTP） | 軽量に状態を問い合わせたい | UC-2 |
| F-3 | タスク状態参照（tasks/records） | どこまで進んだかを見たい | UC-3 |
| F-4 | run一覧/フィルタ（KV keys走査のbest-effort） | 直近実行を俯瞰したい | UC-4 |
| F-5 | worker状態の付加（registry + heartbeat） | RUNNINGなのに止まっている疑いを持ちたい | UC-2 |
| F-6 | DLQ（診断用） | 無限再配送や失敗の診断をしたい | UC-6 |
| F-7 | 長時間runの安全性（heartbeat + in_progress ACK） | 長時間runで意図せず再配送/詰まりを起こしたくない | UC-5 |
| F-8 | JetStreamリソースの自動作成/確認 | 導入と運用を軽くしたい | UC-1, UC-5 |
| F-9 | ヘルスチェック | 稼働確認を簡単にしたい | UC-7 |
| F-10 | メトリクス提供（Prometheus互換） | 運用状況を把握したい | UC-8 |
| F-11 | worker運用可視化（状態区別＋表示制御） | 停止種別を区別し、必要なworkerだけを監視したい | UC-9, UC-13 |
| F-12 | YAML（flow.yaml）でrun投入 | 信頼境界内で「ファイルで実行」をしたい | UC-1 |
| F-13 | run一覧の差分取得（cursor / updated_after / sha256 filter） | GUIで一覧更新を軽くしたい | UC-4 |
| F-14 | run監視ストリーミング（SSE） | GUIで詳細状態をほぼリアルタイムに見たい | UC-10 |
| F-15 | 最小GUIダッシュボード（一覧/詳細/workers/metrics） | 運用状況を1画面で把握したい | UC-4, UC-8, UC-9, UC-10, UC-11 |
| F-16 | CLIの使い勝手改善（入力簡略化/エラー案内） | CLI操作時の試行錯誤を減らしたい | UC-12 |
| F-17 | Dashboard文言の多言語化（ja/en） | 利用環境に応じて読みやすいUIで運用したい | UC-11 |
| F-18 | `nats-bootstrap` 連携（server起動時NATS同時起動 + 運用CLI整合） | ローカル/クラスタの運用手順を揃えたい | UC-12 |
| F-19 | run取消（cancel、best-effort） | 実行中runを運用判断で止めたい | UC-14 |
| F-20 | wheelレジストリとタグ一致同期（Object Store） | workerごとの依存配布を一元化したい | UC-15 |
| F-21 | wheel配布履歴（source/actor監査） | どこからアップロードされたか追跡したい | UC-15 |

#6.ユースケース（Use Cases）
| ID | 主体 | 目的 | 前提 | 主要手順（最小操作） | 成功条件 | 例外/制約 |
|---|---|---|---|---|---|---|
| UC-1 | Pyoco利用者 | runを投入する | HTTP Gateway稼働、NATS利用可能 | `POST /runs` または `POST /runs/yaml` を呼ぶ | run_idが返り、PENDINGが観測できる | NATS不可なら投入失敗（503） |
| UC-2 | Pyoco利用者 | runの状態を確認する | run_idを保持 | `GET /runs/{run_id}` を呼ぶ | 最新スナップショットが得られる | KVに無いrun_idは404 |
| UC-3 | Pyoco利用者 | タスク状態/記録を確認する | run_idを保持 | `GET /runs/{run_id}/tasks` を呼ぶ | tasks と task_records が得られる | task_recordsは欠落/省略され得る |
| UC-4 | Pyoco利用者 | run一覧を取得する | HTTP Gateway稼働 | `GET /runs` を呼ぶ（任意でフィルタ） | best-effortで一覧が得られる | KVは順序保証なし（updated_atでbest-effort） |
| UC-5 | worker運用者 | workerがrunを実行し状態を書き込む | workerがNATSに接続可能 | JetStreamからpull→Pyoco実行→KV更新→ACK | terminal状態（COMPLETED/FAILED）が記録される | at-least-onceで重複実行あり得る |
| UC-6 | 運用者/開発者 | 失敗を診断する | DLQが有効 | DLQメッセージを参照する | 失敗理由/メタデータで原因調査できる | DLQは診断用（真実はrunスナップショット） |
| UC-7 | 利用者/運用者 | 稼働状態を確認する | HTTP Gateway稼働 | `GET /health` を呼ぶ | status=okが返る | 到達できない場合は疎通/起動確認 |
| UC-8 | 運用者/GUI | メトリクスを取得する | HTTP Gateway稼働、NATS利用可能 | `GET /metrics` を呼ぶ | Prometheus互換のメトリクスが得られる | NATS不可なら取得失敗（503） |
| UC-9 | 運用者/GUI | worker一覧を取得する | HTTP Gateway稼働、NATS利用可能 | `GET /workers` を呼ぶ（`scope`/`state`/`include_hidden` で表示条件を調整） | worker状態（`RUNNING`/`IDLE`/`STOPPED_GRACEFUL`/`DISCONNECTED`）付きで一覧を得られる | NATS不可なら取得失敗（503） |
| UC-10 | 運用者/GUI | run詳細を継続監視する | run_idを保持、HTTP Gateway稼働 | `GET /runs/{run_id}/watch`（SSE）を呼ぶ（切断時は再接続） | スナップショット更新を継続受信できる | run_id不存在は404、NATS不可は503、順序はbest-effort |
| UC-11 | 運用者/GUI | ダッシュボードで運用状態を俯瞰する | HTTP Gateway稼働 | `GET /` でダッシュボードを開く | run/worker/metricsを1画面で確認できる | 静的ファイル未配置時は404 |
| UC-12 | 運用者/利用者 | CLIでrun投入/参照とNATS運用を最小手順で行う | CLI利用環境がある | `pyoco-client` / `pyoco-worker` / `pyoco-server` と `nats-bootstrap`（`up/join/status/doctor/backup/restore/leave/down/service`）を使う | 必要最小の手順で投入・参照・監視・運用作業ができる | `nats-bootstrap` のMVP制約（backup/restore の nats CLI 前提、leave/controller、down の pid前提）を持つ |
| UC-13 | 運用者/GUI | worker表示を整理する | 対象workerが一覧に存在する | `PATCH /workers/{worker_id}` で `hidden` を切り替える | 運用上不要なworkerを非表示化/再表示できる | 対象workerが無ければ404 |
| UC-14 | 運用者/利用者 | 実行中runを取消する | run_idを保持、HTTP Gateway/worker稼働 | `POST /runs/{run_id}/cancel` または `pyoco-client cancel --run-id <id>` を呼ぶ | runが `CANCELLING` を経て `CANCELLED` に収束する | 取消はbest-effort（legacy workerや境界外実行では即時停止を保証しない） |
| UC-15 | 運用者/利用者 | wheelを配布し、対象workerだけ同期する | HTTP Gateway/worker稼働、Object Store利用可能 | `POST /wheels`（tags付き）で登録し、workerが定期同期する。`GET /wheels/history` で履歴を参照する | 同一パッケージはバージョンを必ず上げて登録され、workerタグと一致した最新版のみ同期・インストールされ、履歴で配布元を追跡できる | 同期/インストールはbest-effort（失敗時は再同期まで遅延） |

#7.Goals（Goalのみ／ユースケース紐づけ必須）
- G-1: NATSを利用者に露出せず、HTTPのみでrun投入/参照できる（対応：UC-1, UC-2, UC-3, UC-4）
- G-2: 追加DBなし（JetStream Stream/KVで完結）で導入と運用が軽い（対応：UC-1, UC-5）
- G-3: 長時間run/障害時に詰まりにくく、診断可能である（対応：UC-5, UC-6, UC-8, UC-9）
- G-4: GUIでrun/worker/運用状態を最小操作で継続監視できる（対応：UC-4, UC-8, UC-9, UC-10, UC-13）
- G-5: CLIでrun運用を低学習コストで実行できる（対応：UC-12）
- G-6: 実行中runを安全に取消できる（対応：UC-14）
- G-7: worker依存の配布を中央管理し、タグ一致で安全に展開できる（対応：UC-15）
- G-8: `nats-bootstrap` 連携で単体/クラスタ運用の手順を揃え、小チームでもDay-2運用を継続できる（対応：UC-12）

#8.基本レイヤー構造（Layering）
| レイヤー | 役割 | 主な処理/データ流れ |
|---|---|---|
| 運用UI層 | 運用者向けの最小GUI（read-only） | Dashboard→HTTP Gateway（一覧/詳細/SSE/workers/metrics） |
| プレゼンテーション層 | HTTP I/FとクライアントI/F（CLI含む） | Client/CLI→HTTP Gateway、HTTP Gateway→JSON応答（KV由来） |
| アプリケーション層 | ユースケースの編成 | run投入の原子性（KV+publish）、参照時の付加情報（worker状態判定/hidden制御）、wheel登録/配布制御 |
| インフラ層 | JetStream資源と永続（最新状態） | WorkQueue publish/pull、KV put/get/keys（run/worker registry）、DLQ publish、Object Store（wheel registry） |
| 実行層（worker） | Pyoco Engineでrunを実行 | flow解決→実行→traceでKVスナップショット更新→terminal化→ACK |

#9.主要データクラス（Key Data Classes / Entities）
| データクラス | 主要属性（不要属性なし） | 用途（対応UC/Feature） |
|---|---|---|
| RunJob（ジョブメッセージ） | run_id, flow_name, tag, tags, params, submitted_at, workflow_yaml?, workflow_yaml_sha256?, workflow_yaml_bytes? | workerがpullして実行（UC-5, F-1, F-12） |
| RunSnapshot（最新状態） | run_id, flow_name, status, params, tasks, task_records, heartbeat_at, updated_at, error, worker_id, tag, tags, workflow_yaml_sha256?, workflow_yaml_bytes? | 状態参照/一覧（UC-2, UC-3, UC-4, F-2, F-3, F-4, F-12） |
| RunListCursor（一覧カーソル） | next_cursor, limit, updated_after? | GUIの一覧差分取得（UC-4, F-13） |
| RunWatchEvent（SSEイベント） | event, run_id, snapshot, ts | GUIのrun詳細監視（UC-10, F-14） |
| RunCancelRequest（取消要求） | run_id, requested_at, requested_by?, reason? | run取消の受理/監査（UC-14, F-19） |
| WorkerRegistry（worker運用状態） | worker_id, instance_id, state, hidden, tags, last_seen_at, last_run_status?, stop_reason?, wheel_sync? | worker一覧/表示制御（UC-9, UC-13, F-11） |
| WheelArtifact（配布wheel） | name, tags, digest, size_bytes, nuid, uploaded_at | wheel登録/一覧/配布対象判定（UC-15, F-20） |
| WheelHistoryEvent（配布履歴） | event_id, action, wheel_name, tags, occurred_at, source, actor | upload/delete監査（UC-15, F-21） |
| WheelSyncState（worker同期状態） | worker_id, wheel_name, nuid, installed_at, sha256_hex | worker側の差分同期/再インストール判定（UC-15, F-20） |
| DlqMessage（診断） | timestamp, reason, error, run_id?, flow_name?, tag?, tags?, worker_id?, num_delivered?, subject? | 診断（UC-6, F-6） |

#10.機能部品の実装順序（Implementation Order）
1. JetStreamリソース作成/確認（Stream/KV/DLQ）
2. RunJob / RunSnapshot の最小スキーマとコンパクション（task_records truncation）
3. HTTP Gateway（/health, /runs, /runs/{id}, /runs/{id}/tasks, /runs 一覧）
4. Worker（pull, flow解決, Pyoco実行, KV更新, terminal化後ACK）
5. 長時間run対策（run heartbeat, worker heartbeat, in_progress ACK）
6. DLQ（invalid_job / flow_not_found / execution_error の診断イベント）
7. 統合テスト（HTTP投入→worker実行→HTTP参照）
8. Quickstart/サンプル整備（5分で体験できる）
9. 運用向けエンドポイント（/metrics, /workers）
10. run一覧のGUI向け強化（cursor / updated_after / workflow_yaml_sha256 filter）
11. run監視ストリーミング（`GET /runs/{run_id}/watch` SSE）
12. 最小GUIダッシュボード（一覧/詳細/workers/metrics、read-only）
13. CLIの使い勝手改善（入力簡略化、エラー表示改善、help整備）
14. worker運用可視化（`RUNNING`/`IDLE`/`STOPPED_GRACEFUL`/`DISCONNECTED`）と表示制御（hide/unhide）
15. run取消（`POST /runs/{run_id}/cancel`、worker協調停止、CLI `cancel`、E2E）
16. wheelレジストリ（`/wheels`）とworker同期（タグ一致配布、差分インストール、E2E）

#11.用語集（Glossary）
- run：Pyoco flow の1回の実行（分散の単位）。
- tag：JetStream subject `pyoco.work.<tag>` の `<tag>`。ルーティングキー（ANDは扱わない）。
- tags：表示/検索用の任意メタデータ（ルーティングには使わない）。
- WorkQueue：JetStreamのretentionポリシー。at-least-onceのキュー用途。
- snapshot：KVに保存する最新状態（履歴ではない）。
- terminal：COMPLETED/FAILED/CANCELLED 等、以後更新が想定されない状態。
- DLQ：診断用の隔離キュー（runの真実はRunSnapshot）。
- AckWait：JetStreamが再配送可否を判断する待ち時間。
- in_progress ACK：長時間runで再配送を防ぐためにworkerが定期送信するACK。
- cancel（best-effort）：runに取消要求を記録し、workerが協調的に `CANCELLING -> CANCELLED` へ遷移させる。
- worker state：`RUNNING`（run実行中）、`IDLE`（稼働中だが未実行）、`STOPPED_GRACEFUL`（明示停止）、`DISCONNECTED`（heartbeat途絶）。
- hidden：運用画面での表示制御フラグ。履歴削除ではない。
- cursor：一覧差分取得の継続位置を示す不透明トークン。
- watch（SSE）：run状態の更新を継続配信するHTTPストリーム。
- Dashboard：運用者向けの最小GUI（read-only、状態監視用途）。
- nats-bootstrap：NATS起動・参加・診断・退避/復旧を行う運用CLI群（`backup/restore` は `nats` CLI 前提）。
- leave/controller（MVP制約）：`leave` は controller endpoint（`nats-bootstrap controller start` のendpoint）と `--confirm` が必要。`--stop-anyway` でもローカル停止はMVPでは実行しない。
- down（pid前提）：`down` は `--confirm` と `./nats-server.pid` が必要。
- wheel registry：JetStream Object Store に保持する配布用wheelの保管領域。
- wheel version policy：同一パッケージを再配布する場合は、必ずバージョンを上げる（同一/過去バージョンは拒否）。
- wheel tags：wheelの適用対象を表すタグ集合。worker tags と1つ以上一致した場合に同期対象になる。
- wheel history：wheelのupload/delete履歴。source（接続元情報）と actor（認証主体）を保持する監査データ。
