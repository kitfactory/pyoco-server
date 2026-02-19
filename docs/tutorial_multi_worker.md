# チュートリアル：pyoco-server を「サーバー + 複数ワーカー（CPU/GPU）」で動かす

このチュートリアルでは、次の構成をローカルで動かします。

- NATS（JetStream有効）：分散キュー + KV（最新状態） + DLQ（診断）
- pyoco-server（HTTP Gateway）：利用者はHTTPだけでrunを投入/参照
- 複数ワーカー：
  - CPUワーカー（tag=`cpu`）
  - GPUワーカー（tag=`gpu`）

ポイント：
- ルーティングは `tag` で行います（subject `pyoco.work.<tag>`）。
- tagマッチは OR のみです（ANDはしません）。
- ワーカーは「自分が処理できるtag」を引き受けるだけで、GPU/CPUの“実際の能力判定”はここでは扱いません。
  - 実運用では「GPUが載っているマシンだけ `--tags gpu` で起動」など、起動時に宣言して運用します。
- wheel配布もタグ一致で制御できます（wheel tags と worker tags の共通要素がある場合だけ同期）。

---

## 0) 前提（必要なもの）
- Python 3.10+
- `uv`
- ローカルで複数プロセスを起動できること（ターミナルを複数使います）

依存関係の導入：

```bash
uv sync
```

---

## 1) NATSサーバーのインストール（選択肢）

### 選択肢A（おすすめ：このリポジトリの dev 依存を使う）
このリポジトリは開発用依存に `nats-server-bin` を含みます。`uv sync` 後は `uv run nats-server ...` で起動できます。

確認：
```bash
uv run nats-server --help
```

### 選択肢B（OSにインストールする）
環境に合わせて、OSのパッケージマネージャや公式配布（GitHub Releasesなど）を利用して `nats-server` をインストールしてください。

確認：
```bash
nats-server --help
```

### 選択肢C（Dockerで起動する）
Dockerが使える環境なら、NATS公式イメージで起動できます（JetStreamを有効にする必要があります）。

※Dockerの具体的な起動コマンドは環境差が大きいので、まずは選択肢Aを推奨します。

---

## 2) NATS（JetStream）を起動する

ターミナルA：

```bash
uv run nats-server -js -a 127.0.0.1 -p 4222 -m 8222
```

ここから先では、NATS URL を `nats://127.0.0.1:4222` とします。

---

## 3) （任意）`.env` を用意する（server/worker共通）

`.env` は任意です。使うと、複数ターミナルで同じ設定を再利用しやすくなります。

例（必要なものだけでOK）：

```bash
PYOCO_NATS_URL="nats://127.0.0.1:4222"

# Logging（例）
PYOCO_LOG_LEVEL="INFO"
PYOCO_LOG_FORMAT="json"
PYOCO_LOG_INCLUDE_TRACEBACK="true"
```

読み込み（bash）：

```bash
set -a
source .env
set +a
```

設定一覧は `docs/config.md` と `docs/spec.md`（付録I）を参照してください。

---

## 4) HTTP Gateway（pyoco-server）を起動する

ターミナルB：

```bash
export PYOCO_NATS_URL="nats://127.0.0.1:4222"
uv run pyoco-server up --host 127.0.0.1 --port 8000
```

単体NATSでよければ、次のように同時起動もできます（`nats-bootstrap` 必須）。

```bash
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000
```

### （任意）HTTP認証（API key）を有効化する
既定は無認証です。運用で保護したい場合だけ有効化します（opt-in）。

HTTP Gateway を起動する前に設定します：

```bash
export PYOCO_HTTP_AUTH_MODE="api_key"
export PYOCO_AUTH_KV_BUCKET="pyoco_auth"
export PYOCO_HTTP_API_KEY_HEADER="X-API-Key"
```

API key を発行します（平文キーはこの時だけ表示されます）：

```bash
uv run python -m pyoco_server.admin_cli api-key create --tenant demo
```

以降のHTTPリクエストに `X-API-Key` として付与します。

疎通確認：

```bash
curl -sS http://127.0.0.1:8000/health
```

---

## 5) CPUワーカーとGPUワーカーを起動する（YAMLメイン）

ワーカーは `--tags` で「自分が処理するtag」を宣言します（複数指定はカンマ区切り、OR）。
YAMLジョブ（`submit-yaml`）を主に使う場合、`--flow-resolver` は不要です。

このチュートリアルでは wheel同期の挙動も見るため、先に次を設定します。

```bash
export PYOCO_WHEEL_SYNC_ENABLED="1"
export PYOCO_WHEEL_SYNC_DIR=".pyoco/wheels"
```

### CPUワーカー（tag=cpu）
ターミナルC：

```bash
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags cpu --worker-id cpu-1 --wheel-sync
```

### GPUワーカー（tag=gpu）
ターミナルD：

```bash
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags gpu --worker-id gpu-1 --wheel-sync
```

補足：`submit`（flow_name投入）も使う場合は、`--flow-resolver examples/hello_flow.py:resolve_flow` を付けて起動してください。

---

## 6) YAMLでCPU向けrunとGPU向けrunを投入する（推奨）

投入はHTTPです。tagを変えると「どのワーカーが拾うか」が変わります。
まず `flow.yaml` を作ります（このチュートリアルでは package 同梱のテスト用タスクを使います）。

```bash
cat > flow.yaml <<'YAML'
version: 1
flow:
  graph: |
    add_one >> to_text
  defaults:
    x: 1
tasks:
  add_one:
    callable: pyoco_server._workflow_test_tasks:add_one
  to_text:
    callable: pyoco_server._workflow_test_tasks:to_text
YAML
```

### CPUに投げる（tag=cpu）
ターミナルE：

```bash
uv run pyoco-client --server http://127.0.0.1:8000 submit-yaml --workflow-file flow.yaml --flow-name main --tag cpu
```

（HTTP認証を有効にした場合）
```bash
uv run pyoco-client --server http://127.0.0.1:8000 --api-key "<your_api_key>" submit-yaml --workflow-file flow.yaml --flow-name main --tag cpu
```

### GPUに投げる（tag=gpu）
ターミナルE（もう一度）：

```bash
uv run pyoco-client --server http://127.0.0.1:8000 submit-yaml --workflow-file flow.yaml --flow-name main --tag gpu
```

（HTTP認証を有効にした場合）
```bash
uv run pyoco-client --server http://127.0.0.1:8000 --api-key "<your_api_key>" submit-yaml --workflow-file flow.yaml --flow-name main --tag gpu
```

観察ポイント（「おもしろいところ」）：
- CPUのrunはCPUワーカーが拾い、GPUのrunはGPUワーカーが拾う
- `GET /runs/{run_id}` のレスポンスに `worker_id` が入り、どのワーカーが処理したか見える

run_id は `pyoco-client` のJSON出力に表示されます。

例：runの状態を見る

```bash
uv run pyoco-client --server http://127.0.0.1:8000 get <run_id>
uv run pyoco-client --server http://127.0.0.1:8000 watch <run_id> --until-terminal --output status
uv run pyoco-client --server http://127.0.0.1:8000 list --tag cpu --limit 20 --output table
```

`submit`（flow_name投入）を使う場合の params 指定は、`--params-file` / `--params` / `--param key=value` を併用できます（後勝ち）。

---

## 6b) wheel をタグ付きで配布する（CPU/GPUで出し分け）

運用者は wheel registry（`/wheels`）に配布物を登録できます。  
worker は自分の `--tags` と一致する wheel だけ同期します。

```bash
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/task_cpu-0.1.0-py3-none-any.whl --tags cpu
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/task_gpu-0.1.0-py3-none-any.whl --tags gpu
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/task_shared-0.1.0-py3-none-any.whl
uv run pyoco-client --server http://127.0.0.1:8000 wheels
uv run pyoco-client --server http://127.0.0.1:8000 wheel-history --limit 20
```

観察ポイント：
- CPU worker は `cpu` + 共有wheelを同期する
- GPU worker は `gpu` + 共有wheelを同期する
- 同一パッケージに複数バージョンがある場合、各workerは最新版のみを同期する
- 同期は起動時と次回poll前に行われ、実行中runの途中更新はしない
- 同一パッケージの再配布はバージョンアップが必須（同一/過去バージョンは409）

---

## 7) 運用向けエンドポイント（/metrics と /workers）を見る

### /workers（worker運用一覧）

```bash
curl -sS http://127.0.0.1:8000/workers
```

既定では `scope=active` なので、`RUNNING|IDLE` のみ表示されます。  
全件表示（hidden含む）は次です。

```bash
curl -sS "http://127.0.0.1:8000/workers?scope=all&include_hidden=true"
```

状態で絞り込む例：

```bash
curl -sS "http://127.0.0.1:8000/workers?scope=all&state=STOPPED_GRACEFUL"
curl -sS "http://127.0.0.1:8000/workers?scope=all&state=DISCONNECTED"
```

表示制御（hidden）の例：

```bash
# hidden=true（一覧から隠す）
curl -sS -X PATCH "http://127.0.0.1:8000/workers/cpu-1" \
  -H "Content-Type: application/json" \
  -d '{"hidden": true}'

# hidden=false（再表示）
curl -sS -X PATCH "http://127.0.0.1:8000/workers/cpu-1" \
  -H "Content-Type: application/json" \
  -d '{"hidden": false}'
```

状態の見方：
- `RUNNING`：run実行中
- `IDLE`：起動中だが実行していない
- `STOPPED_GRACEFUL`：Ctrl+C などで正常停止した
- `DISCONNECTED`：異常停止や通信断などで heartbeat が途絶した

補足：
- `DISCONNECTED` 判定は `PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC`（既定20秒）を超えたときに行われます。
- `STOPPED_GRACEFUL` と `DISCONNECTED` は別状態として区別されます。

### /metrics（Prometheus互換のメトリクス：best-effort）

```bash
curl -sS http://127.0.0.1:8000/metrics | head
```

`pyoco_runs_total{status="COMPLETED"}` や `pyoco_workers_alive_total` が増えていきます。

### Dashboard UI（read-only）
ブラウザで `http://127.0.0.1:8000/` を開くと、run一覧/詳細、workers、metrics を1画面で確認できます。  
Auth有効時は、画面右上に `X-API-Key` を入力して適用します。

---

## 8) ログ（エラー時に“どこで何が起きたか”を残す）

ログ設定は `PYOCO_LOG_*` で制御できます（server/worker共通）。
推奨は JSON Lines で、エラー時に「元例外（例外クラス/メッセージ/トレースバック）＋発生箇所（ファイル/行/関数）」を必ず残します。

- 仕様：`docs/spec.md`（REQ-0013）
- 設計：`docs/architecture.md`（ログ仕様）
- `.env` 例：`docs/config.md`

---

## 9) 片付け

起動したターミナル（A〜D）のプロセスを Ctrl+C で停止します。
