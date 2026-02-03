# pyoco-server（v0）

要件とは（レビュー者視点）＋ Given/When/Done ＋ MSG/ERR のID管理  
※本書は「内容変更なしの全面編集」を前提に、既存の契約を skills テンプレ寄りに再構成したもの。  
※I/F詳細（JSON例やフィールド列挙）は付録に集約し、要件本文は要件レベルに留める。

# 要件一覧（Requirements）
| ID | 要件（固定書式・正常系のみ） | 関連UC-ID |
|---|---|---|
| REQ-0001 | `/health` を呼んだら、稼働状態を返す。 | UC-7 |
| REQ-0002 | run投入をしたら、run_id を採番し初期スナップショットを書き、キューへ投入する。 | UC-1 |
| REQ-0003 | run投入をしたら、KV書き込みとキュー投入が両方成功した場合のみ成功応答を返す。 | UC-1 |
| REQ-0004 | run状態参照をしたら、最新スナップショットを返す。 | UC-2 |
| REQ-0005 | タスク状態参照をしたら、tasks と task_records（省略され得る）を返す。 | UC-3 |
| REQ-0006 | run一覧取得をしたら、best-effortで一覧を返す。 | UC-4 |
| REQ-0007 | 起動時にJetStreamリソースを確認し、必要なら作成する。 | UC-1 |
| REQ-0008 | workerがジョブを取得したら、タグに応じて実行し状態を更新する。 | UC-5 |
| REQ-0009 | workerがrunを完了したら、terminalスナップショットを書いた後にACKする。 | UC-5 |
| REQ-0010 | 長時間runを実行したら、JetStreamの再配送を防ぐため in_progress ACK を定期送信する。 | UC-5 |
| REQ-0011 | スナップショットが上限を超えそうなら、task_recordsを削減して上限内に収める。 | UC-3 |
| REQ-0012 | 失敗が発生したら、失敗種別に応じて ACK/NAK/TERM と DLQ を適用する。 | UC-5, UC-6 |
| REQ-0013 | エラーが発生したら、元例外と発生箇所が追跡できるログを出力する。 | UC-5, UC-6 |
| REQ-0014 | メトリクス取得をしたら、運用向けのメトリクスを返す。 | UC-8 |
| REQ-0015 | worker一覧取得をしたら、TTL-KVに存在するworker情報を返す。 | UC-9 |
| REQ-0016 | （opt-in）HTTP認証を有効にしたら、`X-API-Key` で認証し `/runs*` を保護する。 | UC-1, UC-2, UC-3, UC-4 |
| REQ-0017 | （opt-in）HTTP認証を有効にしたら、runに `tenant_id`/`api_key_id` を刻み、参照/一覧は同一tenantに限定する。 | UC-1, UC-2, UC-3, UC-4 |
| REQ-0018 | ワークフローファイル（YAML: flow.yaml）でrun投入をしたら、YAMLを含むジョブを投入し実行できる。 | UC-1 |

### [PYOCO-0001] `/health` を呼んだら、稼働状態を返す。
Given：HTTP Gateway が起動している。  
When：利用者が `/health` を呼ぶ。  
Done：200 で `status=ok` 相当の応答が返る。

#### エラー分岐（REQ-0001の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0001 | HTTP Gateway が起動していない/到達できない | Gatewayの起動/疎通確認 | MSG-PYOCO-0001 |

### [PYOCO-0002] run投入をしたら、run_id を採番し初期スナップショットを書き、キューへ投入する。
Given：HTTP Gateway が起動しており、NATS JetStream に接続できる。  
When：利用者が run投入（`POST /runs`）を行う。  
Done：run_id が採番され、KV に `PENDING` の初期スナップショットが書かれ、WorkQueue にジョブが投入される。

#### エラー分岐（REQ-0002の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0002 | 入力JSON/スキーマが不正（バリデーション不可） | 入力を修正して再送 | MSG-PYOCO-0002 |
| ERR-PYOCO-0003 | NATS/JetStream が利用不可でKV書き込み/投入ができない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0003] run投入をしたら、KV書き込みとキュー投入が両方成功した場合のみ成功応答を返す。
Given：HTTP Gateway が起動しており、NATS JetStream に接続できる。  
When：利用者が run投入（`POST /runs`）を行う。  
Done：KV書き込みと publish が両方成功した場合のみ 200 を返し、publishが失敗した場合は孤児runを残さない（best-effortでKVキーを削除する）。

#### エラー分岐（REQ-0003の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0004 | KV書き込み後に publish が失敗し、削除も失敗して孤児runが残る可能性がある（best-effortの限界） | 運用で該当run_idを確認/必要なら削除 | MSG-PYOCO-0004 |

### [PYOCO-0004] run状態参照をしたら、最新スナップショットを返す。
Given：利用者が run_id を保持している。  
When：利用者が run状態参照（`GET /runs/{run_id}`）を行う。  
Done：KV上の最新スナップショットが返る（任意で worker 生死等が付加され得る）。また、既知の拡張を除き、未知フィールドはクライアント側で無視できる前提とする（後方互換）。

#### エラー分岐（REQ-0004の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0005 | run_id に対応するKVキーが存在しない | run_id を確認 | MSG-PYOCO-0005 |
| ERR-PYOCO-0003 | NATS/JetStream が利用不可でKV参照ができない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0005] タスク状態参照をしたら、tasks と task_records（省略され得る）を返す。
Given：利用者が run_id を保持している。  
When：利用者がタスク状態参照（`GET /runs/{run_id}/tasks`）を行う。  
Done：tasks と task_records（欠落/省略され得る）と truncation フラグが返る。

#### エラー分岐（REQ-0005の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0005 | run_id に対応するKVキーが存在しない | run_id を確認 | MSG-PYOCO-0005 |
| ERR-PYOCO-0003 | NATS/JetStream が利用不可でKV参照ができない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0006] run一覧取得をしたら、best-effortで一覧を返す。
Given：HTTP Gateway が起動しており、NATS JetStream に接続できる。  
When：利用者が run一覧取得（`GET /runs`）を行う。  
Done：KV keys を走査して best-effort な一覧が返る。既定では軽量な要約で返し、指定時のみ詳細（task_records等）を返し得る。

#### エラー分岐（REQ-0006の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0003 | NATS/JetStream が利用不可でKV参照ができない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0007] 起動時にJetStreamリソースを確認し、必要なら作成する。
Given：HTTP Gateway / worker が起動し、NATS JetStream に接続できる。  
When：起動処理でリソース確認を行う。  
Done：WorkQueue用Stream、DLQ用Stream、runスナップショットKV、worker生死KVが利用可能になる（既存の場合は環境側の設定を尊重し、既存値を維持し得る）。

#### エラー分岐（REQ-0007の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0003 | NATS/JetStream が利用不可でリソース確認/作成ができない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0008] workerがジョブを取得したら、タグに応じて実行し状態を更新する。
Given：worker が対象 tag の consumer から pull できる。  
When：worker がジョブを取得する。  
Done：flow を解決し、Pyoco Engine で run を実行し、RUNNING→（タスク遷移）→terminal のスナップショットをKVへ反映する。

#### エラー分岐（REQ-0008の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0006 | flow_name を解決できない（workerが該当flowを持たない） | flow_name/worker配置を確認 | MSG-PYOCO-0006 |
| ERR-PYOCO-0007 | Pyoco実行で例外が発生する（実行失敗） | 入力/コード/依存を確認し再投入 | MSG-PYOCO-0007 |
| ERR-PYOCO-0003 | NATS/KV書き込みが一時的に失敗する | NATS復旧後に再試行（NAKで再配送） | MSG-PYOCO-0003 |

### [PYOCO-0009] workerがrunを完了したら、terminalスナップショットを書いた後にACKする。
Given：worker がジョブを実行中である。  
When：run が完了（COMPLETED/FAILED 等の terminal）する。  
Done：terminal スナップショットを書いた後に ACK し、キューから除去する（at-least-once）。

#### エラー分岐（REQ-0009の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0008 | terminal スナップショットを書けずACKできない | NATS復旧後に再試行（NAKで再配送） | MSG-PYOCO-0008 |

### [PYOCO-0010] 長時間runを実行したら、JetStreamの再配送を防ぐため in_progress ACK を定期送信する。
Given：run が `AckWait` を超える可能性がある。  
When：worker が run を実行している。  
Done：`ack_progress_interval_sec < AckWait` を満たす間隔で `in_progress` ACK を送信し、意図しない再配送を防ぐ（KVの heartbeat とは別物）。

#### エラー分岐（REQ-0010の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0009 | in_progress ACK が送れない（接続断など） | NATS復旧後に再試行 | MSG-PYOCO-0009 |

### [PYOCO-0011] スナップショットが上限を超えそうなら、task_recordsを削減して上限内に収める。
Given：task_records が増大し得る。  
When：worker がスナップショットをKVへ書く。  
Done：スナップショットサイズ上限を超える場合、task_records を削減し `task_records_truncated=true` を立てる（tasks は保持する）。

#### エラー分岐（REQ-0011の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0010 | 上限を超えて書けず状態更新に失敗する（上限設定が小さすぎる等） | 上限設定を見直す | MSG-PYOCO-0010 |

### [PYOCO-0012] 失敗が発生したら、失敗種別に応じて ACK/NAK/TERM と DLQ を適用する。
Given：worker がジョブを処理している。  
When：失敗（不正ジョブ/flow解決不可/実行失敗/NATS一時障害 等）が発生する。  
Done：失敗種別に応じて、キューアクション（ACK/NAK/TERM）と DLQ publish を行い、無限再配送を避けつつ診断可能にする。

#### エラー分岐（REQ-0012の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0011 | DLQ publish が失敗する（best-effort） | まずrunスナップショットで原因を確認 | MSG-PYOCO-0011 |

### [PYOCO-0013] エラーが発生したら、元例外と発生箇所が追跡できるログを出力する。
Given：HTTP Gateway / worker が稼働している。  
When：例外が発生し、エラーとして扱う（HTTP 4xx/5xx になる、ジョブ失敗になる、DLQ publish になる等）。  
Done：ログ設定が有効（例：`configure_logging(service=...)` が呼ばれている）な場合、ログに次の情報が記録される。
- どのプログラムか（service：`pyoco-server:http` / `pyoco-server:worker`）
- どの場所か（logger名、ファイルパス、行番号、関数名）
- 例外の情報（例外クラス、例外メッセージ、トレースバック）
- 可能な範囲でコンテキスト（run_id, flow_name, tag, worker_id, err_id, msg_id, reason など）

#### エラー分岐（REQ-0013の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0013 | ログ出力の設定が不正/出力先が利用不可（best-effort） | 設定/実行環境を確認 | MSG-PYOCO-0013 |

### [PYOCO-0014] メトリクス取得をしたら、運用向けのメトリクスを返す。
Given：HTTP Gateway が起動しており、NATS JetStream に接続できる。  
When：利用者/運用者が `GET /metrics` を呼ぶ。  
Done：Prometheus互換の text/plain メトリクスが返る（best-effort）。

#### エラー分岐（REQ-0014の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0003 | NATS/JetStream が利用不可で集計できない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0015] worker一覧取得をしたら、TTL-KVに存在するworker情報を返す。
Given：HTTP Gateway が起動しており、NATS JetStream に接続できる。  
When：利用者/運用者が `GET /workers` を呼ぶ。  
Done：TTL-KV（`pyoco_workers`）に存在する worker 情報の一覧が返る（best-effort）。

#### エラー分岐（REQ-0015の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0003 | NATS/JetStream が利用不可で取得できない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0016] （opt-in）HTTP認証を有効にしたら、`X-API-Key` で認証し `/runs*` を保護する。
Given：HTTP Gateway が起動しており、認証モードが `api_key` である。  
When：利用者が `/runs` / `/runs/{run_id}` / `/runs/{run_id}/tasks` を呼ぶ。  
Done：`X-API-Key` が無い場合は 401、無効/失効の場合は 403 を返す。認証に成功した場合は通常どおり処理する。

#### エラー分岐（REQ-0016の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0014 | `X-API-Key` が未指定 | API key を付与して再試行 | MSG-PYOCO-0014 |
| ERR-PYOCO-0015 | API key が無効/失効 | API key を確認/再発行して再試行 | MSG-PYOCO-0015 |
| ERR-PYOCO-0003 | NATS/JetStream が利用不可で照合できない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0017] （opt-in）HTTP認証を有効にしたら、runに `tenant_id`/`api_key_id` を刻み、参照/一覧は同一tenantに限定する。
Given：HTTP Gateway が起動しており、認証モードが `api_key` である。  
When：利用者が `POST /runs` を行い、その後 `GET /runs/{run_id}` / `GET /runs` を行う。  
Done：成功した run のスナップショットに `tenant_id` と `api_key_id` が含まれる。参照/一覧は「同一tenantに属する run のみ」を返す（他tenantのrunは 404 相当で隠蔽してよい）。

#### エラー分岐（REQ-0017の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0014 | `X-API-Key` が未指定 | API key を付与して再試行 | MSG-PYOCO-0014 |
| ERR-PYOCO-0015 | API key が無効/失効 | API key を確認/再発行して再試行 | MSG-PYOCO-0015 |
| ERR-PYOCO-0003 | NATS/JetStream が利用不可で照合/参照できない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

### [PYOCO-0018] ワークフローファイル（YAML: flow.yaml）でrun投入をしたら、YAMLを含むジョブを投入し実行できる。
Given：HTTP Gateway が起動しており、NATS JetStream に接続できる。  
When：利用者がワークフローファイル（YAML: `flow.yaml`）と `flow_name` を指定して run 投入（`POST /runs/yaml`）を行う。  
Done：run_id が採番され、KV に `PENDING` の初期スナップショットが書かれ、WorkQueue に「YAMLを含むジョブ」が投入される。  

補足（v0.4 / pyoco 0.6.1 前提）：
- `flow.yaml` は **単体flow** とし、top-level は `flow:`（`graph` / `defaults`）を正とする（`flows` は使わない）。
- `flow_name` は投入I/F（`POST /runs/yaml`）で指定し、runスナップショット/ログに刻む（pyoco側の `flow.yaml` は名前を持たないため）。
- `params` は `flow.defaults` を正本とし、HTTP側での上書きI/Fは初期は提供しない。
- server は policy として「ファイルサイズ上限」「YAMLスキーマの不明キー拒否」「禁止キー（`flows` / `discovery`）拒否」を行う。
- 初期スナップショットには、少なくとも `workflow_yaml_sha256` / `workflow_yaml_bytes` を含める（YAML本文はKVに保存しない）。

#### エラー分岐（REQ-0018の枝番）
| ERR-ID | 発生条件 | ユーザーアクション | 関連MSG-ID |
|---|---|---|---|
| ERR-PYOCO-0002 | multipart/ファイルが不正、YAMLが不正、スキーマに不明キーがある、禁止キー（`flows`/`discovery`）を含む | `flow.yaml` を修正して再送 | MSG-PYOCO-0002 |
| ERR-PYOCO-0016 | `flow.yaml` がサイズ上限を超える | ファイルサイズを削減する / 上限設定を見直す | MSG-PYOCO-0016 |
| ERR-PYOCO-0003 | NATS/JetStream が利用不可でKV書き込み/投入ができない | NATSの復旧後に再試行 | MSG-PYOCO-0003 |

## メッセージID管理（MSG-PYOCO）
| ID | 文面テンプレ | 出力先 | 発生条件 | 関連REQ/ERR |
|---|---|---|---|---|
| MSG-PYOCO-0001 | 稼働確認に失敗しました | クライアント/ログ | Gatewayに到達できない | REQ-0001/ERR-PYOCO-0001 |
| MSG-PYOCO-0002 | リクエストが不正です | HTTP 422 | 入力バリデーション失敗 | REQ-0002/ERR-PYOCO-0002 |
| MSG-PYOCO-0003 | NATSが利用できません | HTTP 503 / workerログ | NATS利用不可 | REQ-0002/ERR-PYOCO-0003 他 |
| MSG-PYOCO-0004 | 孤児runが残っている可能性があります（best-effort cleanup失敗） | ログ/運用 | cleanup失敗の可能性 | REQ-0003/ERR-PYOCO-0004 |
| MSG-PYOCO-0005 | runが見つかりません | HTTP 404 | KVに存在しないrun_id | REQ-0004/ERR-PYOCO-0005 他 |
| MSG-PYOCO-0006 | flowが見つかりません | workerログ/DLQ | flow_nameが解決できない | REQ-0008/ERR-PYOCO-0006 |
| MSG-PYOCO-0007 | 実行に失敗しました | workerログ/DLQ | Pyoco実行中例外 | REQ-0008/ERR-PYOCO-0007 |
| MSG-PYOCO-0008 | terminal状態の記録に失敗しました | workerログ | terminal化できずNAK | REQ-0009/ERR-PYOCO-0008 |
| MSG-PYOCO-0009 | in_progress ACK の送信に失敗しました | workerログ | in_progress送信失敗 | REQ-0010/ERR-PYOCO-0009 |
| MSG-PYOCO-0010 | スナップショットが大きすぎます | workerログ | 上限超過で更新失敗 | REQ-0011/ERR-PYOCO-0010 |
| MSG-PYOCO-0011 | DLQへのpublishに失敗しました（best-effort） | workerログ | DLQ publish失敗 | REQ-0012/ERR-PYOCO-0011 |
| MSG-PYOCO-0012 | 不正なジョブを受信しました | workerログ/DLQ | JSON不正/必須欠落等 | REQ-0012/ERR-PYOCO-0012 |
| MSG-PYOCO-0013 | ログ出力に失敗しました（best-effort） | ログ/運用 | ログ出力の設定不正等 | REQ-0013/ERR-PYOCO-0013 |
| MSG-PYOCO-0014 | API key が必要です | HTTP 401 | `X-API-Key` 未指定 | REQ-0016/ERR-PYOCO-0014 |
| MSG-PYOCO-0015 | API key が無効です | HTTP 403 | API key 無効/失効 | REQ-0016/ERR-PYOCO-0015 |
| MSG-PYOCO-0016 | ワークフローファイルが大きすぎます | HTTP 413 | `flow.yaml` がサイズ上限を超過 | REQ-0018/ERR-PYOCO-0016 |

## エラーID管理（ERR-PYOCO）
| ID | 原因 | 検出条件 | ユーザーアクション | 再試行可否 | 関連MSG-ID | 関連REQ |
|---|---|---|---|---|---|---|
| ERR-PYOCO-0001 | Gateway停止/到達不可 | health応答が得られない | 起動/疎通確認 | 可 | MSG-PYOCO-0001 | REQ-0001 |
| ERR-PYOCO-0002 | 入力不正 | 422 | 入力修正 | 可 | MSG-PYOCO-0002 | REQ-0002 |
| ERR-PYOCO-0003 | NATS利用不可 | 503 / worker例外 | NATS復旧後に再試行 | 可 | MSG-PYOCO-0003 | REQ-0002 他 |
| ERR-PYOCO-0004 | cleanup失敗 | ログ等 | 運用確認 | 可（運用） | MSG-PYOCO-0004 | REQ-0003 |
| ERR-PYOCO-0005 | run_id不存在 | 404 | run_id確認 | 不可 | MSG-PYOCO-0005 | REQ-0004 |
| ERR-PYOCO-0006 | flow解決不可 | KeyError等 | flow_name/worker配置確認 | 不可（決定的） | MSG-PYOCO-0006 | REQ-0008 |
| ERR-PYOCO-0007 | 実行失敗 | 例外 | 入力/コード/依存を確認 | 可（再投入） | MSG-PYOCO-0007 | REQ-0008 |
| ERR-PYOCO-0008 | terminal化失敗 | KV put失敗 | NATS復旧後に再試行 | 可 | MSG-PYOCO-0008 | REQ-0009 |
| ERR-PYOCO-0009 | in_progress失敗 | msg.in_progress失敗 | NATS復旧後に再試行 | 可 | MSG-PYOCO-0009 | REQ-0010 |
| ERR-PYOCO-0010 | 上限超過 | サイズ超過 | 上限設定見直し | 可 | MSG-PYOCO-0010 | REQ-0011 |
| ERR-PYOCO-0011 | DLQ publish失敗 | publish例外 | runスナップショットで確認 | 可 | MSG-PYOCO-0011 | REQ-0012 |
| ERR-PYOCO-0012 | 不正ジョブ | JSON不正/必須欠落 | producer/subject/実装を確認 | 不可（TERM） | MSG-PYOCO-0012 | REQ-0012 |
| ERR-PYOCO-0013 | ログ出力失敗 | 設定不正/出力先不可 | 設定/実行環境を確認 | 可 | MSG-PYOCO-0013 | REQ-0013 |
| ERR-PYOCO-0014 | API key 未指定 | `X-API-Key` が無い | API key を付与 | 可 | MSG-PYOCO-0014 | REQ-0016 |
| ERR-PYOCO-0015 | API key 無効/失効 | 照合に失敗/失効 | API key を確認/再発行 | 可 | MSG-PYOCO-0015 | REQ-0016 |
| ERR-PYOCO-0016 | ワークフローYAMLが大きすぎる | 413 | ファイルサイズ超過 | 可 | MSG-PYOCO-0016 | REQ-0018 |

---

# 付録（契約詳細 / 既存仕様の保持）

## 付録A.バージョニングと互換性（v0）
- v0（MVP）である。
- 原則は後方互換（フィールド追加/新エンドポイント追加）を優先する。
- 0.xでも破壊的変更は起こり得るが、明示する。
- 将来 `schema_version` を payload/snapshot に入れる余地を残す（v0は暗黙バージョン）。

## 付録B.用語
- run：Pyoco flow の1回の実行。
- tag：JetStream subject `pyoco.work.<tag>` の `<tag>`。ルーティングキー。
- tags：表示/検索用の任意メタデータ。ルーティングには影響しない。
- snapshot：KVに保存する run の最新状態。
- terminal：以後更新が想定されない状態。

## 付録C.ステータスモデル
### Run status（文字列enum）
- `PENDING`：serverに受理されたが、まだworkerが開始していない
- `RUNNING`：workerが実行中
- `COMPLETED`：正常終了
- `FAILED`：異常終了
- `CANCELLING`：取消要求中（将来）
- `CANCELLED`：取消済み（将来）

Terminal（v0）：
- `COMPLETED|FAILED|CANCELLED`

### Task status（文字列enum）
- `PENDING|RUNNING|SUCCEEDED|FAILED|CANCELLED`

備考：
- `task_records` は best-effort であり、workerクラッシュ等で部分的になり得る。

## 付録D.HTTP API（Client <-> Server）
Base URL 例：`http://127.0.0.1:8000`

### GET /health
- 200（例）：`{"status":"ok"}`

### POST /runs（run投入）
- request（v0）：
  - `flow_name`（string, required）
  - `params`（object, optional; default `{}`）
  - `tag`（string, optional; default `default`）
  - `tags`（array[string], optional; default `[tag]`）
- response（v0）：
  - `run_id`（uuid）
  - `status`（`PENDING`）
- errors：
  - 422：入力不正（FastAPI validation）
  - 503：NATS利用不可

原子性（v0）：
- server は「初期スナップショットをKVに書けた」かつ「ジョブをJetStreamへpublishできた」場合のみ 200 を返すことを推奨する。
- KV書き込み後に publish が失敗した場合、孤児run回避のため KV を削除する（best-effort）。

冪等性（v0）：
- `POST /runs` に冪等キーはない。
- 同一payloadを2回送ると別runとして扱う。

### GET /runs/{run_id}（run状態）
- query：
  - `include`（repeatable, optional）
    - `records`：`task_records` を含める
    - `full`/`all`：全て含める（現状は `records` と同義）
- response（v0）の最低要件：
  - `run_id`, `flow_name`, `status`, `params`, `tasks`, `heartbeat_at`, `updated_at`
- 既定では `task_records` は省略することを推奨（レスポンスを小さくする）。
- 追加フィールドは随時増え得る（クライアントは未知フィールドを無視する）。
- worker生死の付加（任意）：
  - `worker_alive`（bool）
  - `worker_heartbeat_at`（unix seconds or null）
  - `worker_tags`（array[string] or null）
- errors：
  - 404：run not found
  - 503：NATS利用不可

### GET /runs/{run_id}/tasks（タスク状態）
- response（v0）の最低要件：
  - `run_id`, `flow_name`, `status`, `tasks`, `task_records`, `task_records_truncated`
- errors：
  - 404：run not found
  - 503：NATS利用不可

### GET /runs（一覧）
- query：
  - `status`（optional）
  - `flow`（optional）
  - `tag`（optional）
  - `limit`（optional; default 50; max 200）
  - `include`（repeatable, optional）
    - `full`/`all`：詳細スナップショットを返す（task_records等を含み得る）
- response（v0）：
  - list[object]
  - list item は最低でも `run_id`, `status`, `updated_at` を含むこと
- notes：
  - KVは順序保証がないため、`updated_at` でbest-effortにソートする。
  - TTL/運用ポリシーによりキーが消える可能性がある（将来追加の場合）。

### GET /metrics（運用向け：Prometheus互換、v0.2）
- response（best-effort）：
  - content-type：`text/plain; version=0.0.4`
  - 例（抜粋）：
    - `pyoco_runs_total{status="COMPLETED"} 1`
    - `pyoco_workers_alive_total 1`
    - `pyoco_dlq_messages_total 0`
- errors：
  - 503：NATS利用不可

### GET /workers（運用向け：worker一覧、v0.2）
- response（best-effort）：
  - JSON：array<object>
  - 1要素（例）：
    - `worker_id`（string）
    - `heartbeat_at`（unix seconds）
    - `tags`（array[string]）
- errors：
  - 503：NATS利用不可

## 付録E.NATS（Server <-> Worker）
### JetStream リソース（v0）
必須：
- Stream：`PYOCO_WORK`
  - subjects：`pyoco.work.>`
  - retention：WorkQueue
- Stream：`PYOCO_DLQ`
  - subjects：`pyoco.dlq.>`
  - retention：Limits（診断用。上限制御推奨）
- KV bucket：`pyoco_runs`（history=1）
- KV bucket：`pyoco_workers`（history=1, ttl有効）

### Consumer 既定（v0）
worker は tag 単位の durable consumer を利用する。既定値：
- `AckWait`：30s（env：`PYOCO_CONSUMER_ACK_WAIT_SEC`）
- `MaxDeliver`：20（env：`PYOCO_CONSUMER_MAX_DELIVER`）
- `MaxAckPending`：200（env：`PYOCO_CONSUMER_MAX_ACK_PENDING`）

注意：
- consumer が既に存在する場合、環境側の設定を尊重し、既存値が維持され得る。

### タグルーティング（ORのみ）
- run は必ず1つのsubject（`pyoco.work.<tag>`）にのみ publish する。
- worker は複数 tag の consumer にバインドして OR を実現する。
- AND（AもBも満たすworkerにだけ配る）は v0 では扱わない。

### ジョブメッセージ（JSON payload）
publish subject：`pyoco.work.<tag>`

フィールド：
- `run_id`（uuid, required）
- `flow_name`（string, required）
- `tag`（string, required）
- `tags`（array[string], optional）
- `params`（object, optional）
- `submitted_at`（unix seconds, required）

### ACK / 再配送
- worker は terminal スナップショットを書いた後に ACK する。
- ACK 前に落ちた場合、再配送が起こり得る（at-least-once）。
- v0 では exactly-once を保証しない（重複実行が起こり得る）。

長時間run：
- `AckWait` を超える可能性がある run は、worker が定期的に JetStream `in_progress` ACK を送る必要がある。
- 推奨：
  - `in_progress` 間隔は `AckWait` 未満（推奨：`AckWait/2`）
  - 既定：10s（env：`PYOCO_ACK_PROGRESS_INTERVAL_SEC`）

### 失敗分類とディスポジション（推奨）
アクション：
- ACK：キューから除去
- NAK(delay)：後で再配送（一次障害）
- TERM：再配送しない（無限ループ回避）

| 失敗種別 | 例 | スナップショット | キューアクション | DLQ |
|---|---|---|---|---|
| 不正ジョブ | JSON不正/必須欠落 | （run_idが分かるなら）FAILED、そうでなければ無し | TERM | あり（`invalid_job`） |
| flow解決不可 | workerがflowコードを持たない | FAILED | ACK | あり（`flow_not_found`） |
| 実行失敗 | 例外 | FAILED | ACK | 既定であり（`execution_error`） |
| NATS一次障害 | KV put失敗等 | なし/部分的 | NAK(delay) | なし |

補足：
- flow解決不可は `flow_resolver(flow_name)` が `KeyError` を投げる形で表現する。
- terminal化できない一次障害では ACK せず、再配送で別試行できるようにする。
- 既定の NAK delay は 2 秒（実装詳細。将来変更し得る）。

### DLQ スキーマ
subject：
- `pyoco.dlq.<tag>`

payload（JSON）：
- `timestamp`（unix seconds）
- `reason`（string；例：`invalid_job`, `execution_error`）
- `error`（string or null）
- `run_id`（optional）
- `flow_name`（optional）
- `tag` / `tags`（optional）
- `worker_id`（optional）
- `num_delivered`（optional）
- `subject`（optional；元subject）

`reason` 値（v0）：
- `invalid_job`
- `flow_not_found`
- `execution_error`

## 付録F.KV スキーマ
### runスナップショット（bucket `pyoco_runs`, key `<run_id>`）
required（v0）：
- `run_id`（uuid）
- `flow_name`（string）
- `status`（string enum）
- `params`（object）
- `tasks`（object）
- `heartbeat_at`（unix seconds）
- `updated_at`（unix seconds）

recommended：
- `tag`（string）
- `tags`（array[string]）
- `worker_id`（string）
- `task_records`（object）
- `task_records_truncated`（bool）
- `start_time` / `end_time`（unix seconds）
- `error`（string or null）

更新ルール（v0）：
- server は publish 前に `PENDING` を書く。
- worker は開始時に `RUNNING` へ遷移させる。
- worker は ACK 前に terminal スナップショットを書く。
- heartbeat 更新は `status` の意味を変えず、`heartbeat_at` を更新する。

サイズ上限（v0）：
- 上限超過時は `task_records` を落として `task_records_truncated=true` を立て得る（tasksは保持）。

### worker生死（bucket `pyoco_workers`, key `<worker_id>`）
fields：
- `worker_id`（string）
- `heartbeat_at`（unix seconds）
- `tags`（array[string], optional）

TTL：
- 未更新で値がexpireする。serverは「キー無し＝生存していない」と扱い得る。

## 付録G.heartbeat / 長時間runの表示（v0の推奨）
worker は：
- RUNNING中、runスナップショットの `heartbeat_at` を定期更新する。
- worker自身の生死キー（`pyoco_workers`）も定期更新する。

利用者/UI の推奨解釈（server側の状態変更ではない）：
- `status == RUNNING` かつ `heartbeat_at` が閾値より古ければ STALE 表示（FAILEDにはしない）。
- 推奨閾値：
  - `hb = PYOCO_RUN_HEARTBEAT_INTERVAL_SEC`（既定 1s）
  - `now - heartbeat_at > max(30s, 3*hb)` で STALE

## 付録H.tag 命名規則（v0）
- `tag` は `pyoco.work.<tag>` の `<tag>`（subjectの1トークン）。
- よって `tag` に `.` は含めない（MUST NOT）。
- 推奨パターン：`[A-Za-z0-9_-]+`
- 既定 tag：`default`

## 付録I.設定（環境変数）
HTTP Gateway：
- `PYOCO_NATS_URL`
- `PYOCO_WORK_SUBJECT_PREFIX`（default：`pyoco.work`）
- `PYOCO_DEFAULT_TAG`（default：`default`）
- `PYOCO_RUNS_KV_BUCKET`（default：`pyoco_runs`）
- `PYOCO_WORKERS_KV_BUCKET`（default：`pyoco_workers`）

HTTP auth（opt-in）：
- `PYOCO_HTTP_AUTH_MODE`（default：`none`；`none` / `api_key`）
- `PYOCO_HTTP_API_KEY_HEADER`（default：`X-API-Key`）
- `PYOCO_AUTH_KV_BUCKET`（default：`pyoco_auth`）
- `PYOCO_AUTH_PEPPER`（default：未設定；任意。設定する場合は秘密情報として扱う）

heartbeat：
- `PYOCO_RUN_HEARTBEAT_INTERVAL_SEC`（default：1.0）
- `PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC`（default：5.0）
- `PYOCO_WORKERS_KV_TTL_SEC`（default：15.0）

JetStream consumer：
- `PYOCO_CONSUMER_ACK_WAIT_SEC`（default：30.0）
- `PYOCO_CONSUMER_MAX_DELIVER`（default：20）
- `PYOCO_CONSUMER_MAX_ACK_PENDING`（default：200）
- `PYOCO_ACK_PROGRESS_INTERVAL_SEC`（default：10.0；`< AckWait`）

DLQ：
- `PYOCO_DLQ_STREAM`（default：`PYOCO_DLQ`）
- `PYOCO_DLQ_SUBJECT_PREFIX`（default：`pyoco.dlq`）
- `PYOCO_DLQ_PUBLISH_EXECUTION_ERROR`（default：true）
- `PYOCO_DLQ_MAX_AGE_SEC`（default：604800）
- `PYOCO_DLQ_MAX_MSGS`（default：100000）
- `PYOCO_DLQ_MAX_BYTES`（default：536870912）

スナップショットサイズ：
- `PYOCO_MAX_RUN_SNAPSHOT_BYTES`（default：262144）

ワークフローYAML投入：
- `PYOCO_WORKFLOW_YAML_MAX_BYTES`（default：262144）

ログ（HTTP Gateway / worker 共通）：
- `PYOCO_LOG_LEVEL`（default：INFO）
- `PYOCO_LOG_FORMAT`（default：json；`json` / `text`）
- `PYOCO_LOG_UTC`（default：true）
- `PYOCO_LOG_INCLUDE_TRACEBACK`（default：true）
