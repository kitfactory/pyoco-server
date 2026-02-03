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
uv run uvicorn pyoco_server.http_api:create_app --factory --host 127.0.0.1 --port 8000
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

## 5) CPUワーカーとGPUワーカーを起動する

このリポジトリの例では、`examples/run_worker.py` が「ワーカー実行」を担います。
ワーカーは `--tags` で「自分が処理するtag」を宣言します（複数指定はカンマ区切り、OR）。

### CPUワーカー（tag=cpu）
ターミナルC：

```bash
uv run python examples/run_worker.py --nats-url nats://127.0.0.1:4222 --tags cpu --worker-id cpu-1
```

### GPUワーカー（tag=gpu）
ターミナルD：

```bash
uv run python examples/run_worker.py --nats-url nats://127.0.0.1:4222 --tags gpu --worker-id gpu-1
```

---

## 6) CPU向けrunとGPU向けrunを投入する（ルーティングを体験）

投入はHTTPです。tagを変えると「どのワーカーが拾うか」が変わります。

### CPUに投げる（tag=cpu）
ターミナルE：

```bash
uv run python examples/submit_run.py --server http://127.0.0.1:8000 --tag cpu
```

（HTTP認証を有効にした場合）
```bash
uv run python examples/submit_run.py --server http://127.0.0.1:8000 --tag cpu --api-key "<your_api_key>"
```

### GPUに投げる（tag=gpu）
ターミナルE（もう一度）：

```bash
uv run python examples/submit_run.py --server http://127.0.0.1:8000 --tag gpu
```

（HTTP認証を有効にした場合）
```bash
uv run python examples/submit_run.py --server http://127.0.0.1:8000 --tag gpu --api-key "<your_api_key>"
```

観察ポイント（「おもしろいところ」）：
- CPUのrunはCPUワーカーが拾い、GPUのrunはGPUワーカーが拾う
- `GET /runs/{run_id}` のレスポンスに `worker_id` が入り、どのワーカーが処理したか見える

run_id は `examples/submit_run.py` の出力に表示されます。

例：runの状態を見る

```bash
curl -sS http://127.0.0.1:8000/runs/<run_id>
```

### 6b) （任意）YAML（flow.yaml）をそのまま投入する（Phase 4）
信頼できる社内チーム向けとして、`flow.yaml`（YAML）をそのまま投入できます。

ポイント：
- `flow.yaml` は **単体flow**（top-level `flow:`）です（pyoco 0.6.1）。
- `flow.yaml` に `discovery` は書けません。利用可能なタスクは worker 側の環境で決まります。

例（`flow.yaml`）：
```yaml
version: 1
flow:
  graph: |
    task_a >> task_b
  defaults:
    x: 1
tasks:
  task_a:
    callable: your_pkg.tasks:task_a
  task_b:
    callable: your_pkg.tasks:task_b
```

投入（tagでルーティングします）：
```bash
curl -sS \\
  -F "flow_name=main" \\
  -F "tag=cpu" \\
  -F "workflow=@flow.yaml;type=application/x-yaml" \\
  http://127.0.0.1:8000/runs/yaml
```

（HTTP認証を有効にした場合）
```bash
curl -sS \\
  -H "X-API-Key: <your_api_key>" \\
  -F "flow_name=main" \\
  -F "tag=cpu" \\
  -F "workflow=@flow.yaml;type=application/x-yaml" \\
  http://127.0.0.1:8000/runs/yaml
```

---

## 7) 運用向けエンドポイント（/metrics と /workers）を見る

### /workers（いま生きているワーカー一覧）

```bash
curl -sS http://127.0.0.1:8000/workers
```

ここに `cpu-1` / `gpu-1` が出ていれば、TTL-KVが更新されています。

### /metrics（Prometheus互換のメトリクス：best-effort）

```bash
curl -sS http://127.0.0.1:8000/metrics | head
```

`pyoco_runs_total{status="COMPLETED"}` や `pyoco_workers_alive_total` が増えていきます。

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
