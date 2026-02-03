# concept.md（必ず書く：最新版）
#1.概要（Overview）（先頭固定）
- 作るもの（What）：Pyoco のワークフロー実行（run）を、HTTP（Client-Server）と NATS JetStream（Server-Worker）で分散実行するための最小バックエンド。
- 解決すること（Why）：Pyoco 利用者が NATS を意識せずに「run投入」「run/タスク状態参照」をできるようにし、導入と運用の負担を最小化する。
- できること（主要機能の要約）：HTTPでrun投入、KVスナップショットで状態参照、タスク状態参照、一覧/フィルタ、worker生死（任意付加）、DLQで診断、長時間runの再配送防止（in_progress ACK）と心拍、運用向けエンドポイント（/metrics, /workers）。
- 使いどころ（When/Where）：Pyoco flow を複数ノード（複数worker）で実行したいが、DBや巨大オーケストレータは持ち込みたくないチーム/環境。
- 成果物（Outputs）：HTTP Gateway（FastAPI）、Worker（Pyoco Engine実行）、JetStreamリソース定義（Stream/KV/DLQ）、PythonライブラリAPI、Quickstart/例。
- 前提（Assumptions）：NATS JetStream が利用可能（信頼性の基盤）、実行保証は at-least-once（重複実行あり得る）、外部DBは前提にしない（JetStream Stream/KVで完結）、サーバー内スケジューラは持たない（トリガーは外側で行う）。

#2.ユーザーの困りごと（Pain）
- 分散実行したいが、NATS/JetStreamの運用やAPI詳細をアプリ利用者に持ち込ませたくない。
- 既存のフル機能オーケストレータ（DAGスケジューリング、監査DB、巨大UI等）は導入が重く、MVPでは過剰。
- runの状態（RUNNINGか、どこまで進んだか）を軽く問い合わせたい（重い履歴DBなしで）。
- 長時間runやworker障害時に「詰まり」にくく、診断可能にしたい（無限再配送の回避、DLQ）。

#3.ターゲットと前提環境（詳細）
- ターゲット：
  - Pyoco利用者（HTTPでrun投入/参照したい）
  - 運用者（NATS/workerを立ち上げ、落ちても復旧できる形にしたい）
- 前提環境：
  - NATS JetStream 有効な NATS（単体〜クラスタ想定）
  - HTTP Gateway は水平スケール可能（状態の真実は JetStream 側）
  - worker はタグ（tag）単位でキューを pull し、複数タグは OR で扱う

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
| F-5 | worker生死の付加（TTL KV） | RUNNINGなのに止まっている疑いを持ちたい | UC-2 |
| F-6 | DLQ（診断用） | 無限再配送や失敗の診断をしたい | UC-6 |
| F-7 | 長時間runの安全性（heartbeat + in_progress ACK） | 長時間runで意図せず再配送/詰まりを起こしたくない | UC-5 |
| F-8 | JetStreamリソースの自動作成/確認 | 導入と運用を軽くしたい | UC-1, UC-5 |
| F-9 | ヘルスチェック | 稼働確認を簡単にしたい | UC-7 |
| F-10 | メトリクス提供（Prometheus互換） | 運用状況を把握したい | UC-8 |
| F-11 | worker一覧取得 | 稼働中workerを把握したい | UC-9 |
| F-12 | YAML（flow.yaml）でrun投入 | 信頼境界内で「ファイルで実行」をしたい | UC-1 |

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
| UC-8 | 運用者 | メトリクスを取得する | HTTP Gateway稼働、NATS利用可能 | `GET /metrics` を呼ぶ | Prometheus互換のメトリクスが得られる | NATS不可なら取得失敗（503） |
| UC-9 | 運用者 | worker一覧を取得する | HTTP Gateway稼働、NATS利用可能 | `GET /workers` を呼ぶ | TTL-KV上のworker一覧が得られる | NATS不可なら取得失敗（503） |

#7.Goals（Goalのみ／ユースケース紐づけ必須）
- G-1: NATSを利用者に露出せず、HTTPのみでrun投入/参照できる（対応：UC-1, UC-2, UC-3, UC-4）
- G-2: 追加DBなし（JetStream Stream/KVで完結）で導入と運用が軽い（対応：UC-1, UC-5）
- G-3: 長時間run/障害時に詰まりにくく、診断可能である（対応：UC-5, UC-6, UC-8, UC-9）

#8.基本レイヤー構造（Layering）
| レイヤー | 役割 | 主な処理/データ流れ |
|---|---|---|
| プレゼンテーション層 | HTTP I/FとクライアントI/F | Client→HTTP Gateway、HTTP Gateway→JSON応答（KV由来） |
| アプリケーション層 | ユースケースの編成 | run投入の原子性（KV+publish）、参照時の付加情報（worker生死） |
| インフラ層 | JetStream資源と永続（最新状態） | WorkQueue publish/pull、KV put/get/keys、TTL-KV、DLQ publish |
| 実行層（worker） | Pyoco Engineでrunを実行 | flow解決→実行→traceでKVスナップショット更新→terminal化→ACK |

#9.主要データクラス（Key Data Classes / Entities）
| データクラス | 主要属性（不要属性なし） | 用途（対応UC/Feature） |
|---|---|---|
| RunJob（ジョブメッセージ） | run_id, flow_name, tag, tags, params, submitted_at, workflow_yaml?, workflow_yaml_sha256?, workflow_yaml_bytes? | workerがpullして実行（UC-5, F-1, F-12） |
| RunSnapshot（最新状態） | run_id, flow_name, status, params, tasks, task_records, heartbeat_at, updated_at, error, worker_id, tag, tags, workflow_yaml_sha256?, workflow_yaml_bytes? | 状態参照/一覧（UC-2, UC-3, UC-4, F-2, F-3, F-4, F-12） |
| WorkerLiveness（生死） | worker_id, heartbeat_at, tags | 状態参照の付加（UC-2, F-5） |
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
- STALE：RUNNINGだがheartbeatが古い状態（v0ではFAILEDにせず表示上の解釈とする）。
