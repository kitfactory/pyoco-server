# Quickstart（5分）：pyoco-server + nats-bootstrap 最短導線

このガイドは、`pyoco-server` を「社内システム向けの軽量分散実行バックエンド」として最短で確認する手順です。

- Client は HTTP を使う
- Server/Worker は NATS JetStream を使う
- 運用は `nats-bootstrap` 連携を中心に回す

## 0) 依存関係を入れる

```bash
uv sync
```

## 1) 最短手順（単体NATSを同時起動）

別ターミナルで実行します。

```bash
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000
```

補足：
- `--with-nats-bootstrap` は `nats-bootstrap` が無いと失敗します。
- このモードは単体NATS起動のみです（クラスタは後述）。

## 2) Worker を起動する

別ターミナルで実行します。

```bash
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1
```

## 3) YAML（flow.yaml）で run を投入する

別ターミナルで実行します。

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

```bash
uv run pyoco-client --server http://127.0.0.1:8000 submit-yaml --workflow-file flow.yaml --flow-name main --tag hello
uv run pyoco-client --server http://127.0.0.1:8000 watch <run_id> --until-terminal --output status
```

補助コマンド：

```bash
uv run pyoco-client --server http://127.0.0.1:8000 list --tag hello --limit 20 --output table
uv run pyoco-client --server http://127.0.0.1:8000 get <run_id>
curl -sS http://127.0.0.1:8000/workers
curl -sS http://127.0.0.1:8000/metrics | head
```

## 4) NATS起動方法（単体 / クラスタ）

### 4a) 単体NATS（nats-server 直接起動）

```bash
uv run nats-server -js -a 127.0.0.1 -p 4222 -m 8222
```

### 4b) 単体NATS（nats-bootstrap）

```bash
uv run nats-bootstrap up -- -js -a 127.0.0.1 -p 4222 -m 8222
```

### 4c) クラスタNATS（3ノード）

ターミナルA:

```bash
uv run nats-bootstrap up --cluster pyoco --listen 127.0.0.1 --client-port 4222 --http-port 8222 --cluster-port 6222 --datafolder artifacts/nats/n1
```

ターミナルB:

```bash
uv run nats-bootstrap join --cluster pyoco --seed 127.0.0.1:6222 --listen 127.0.0.1 --client-port 4223 --http-port 8223 --cluster-port 6223 --datafolder artifacts/nats/n2
```

ターミナルC:

```bash
uv run nats-bootstrap join --cluster pyoco --seed 127.0.0.1:6222 --listen 127.0.0.1 --client-port 4224 --http-port 8224 --cluster-port 6224 --datafolder artifacts/nats/n3
```

以降はAノードを `nats://127.0.0.1:4222` として `pyoco-server` / `pyoco-worker` を接続します。

## 5) Day-2運用（nats-bootstrap）

### 5a) 診断

```bash
uv run nats-bootstrap status
uv run nats-bootstrap doctor
```

### 5b) 退避 / 復旧

```bash
uv run nats-bootstrap backup --stream PYOCO_WORK --output artifacts/backup
uv run nats-bootstrap restore --input artifacts/backup --confirm
```

制約：`backup/restore` は `nats` CLI が必要です（必要に応じて `--nats-cli-path` を指定）。

### 5c) ノード離脱 / 停止

```bash
uv run nats-bootstrap leave --controller <controller-endpoint> --confirm
```

制約：
- `leave` は controller endpoint と `--confirm` が必須です。
- `--controller` は NATS monitor（`:8222`）ではなく、`nats-bootstrap controller start` で立てた endpoint を指定します。
- `--stop-anyway` を付けると controller 不達でも成功扱いにできますが、MVPではローカル停止を実行しません。
- `controller` コマンドは現状 `start` 操作のみです。

`down` を使う場合は、起動時に pid ファイルを作っておく必要があります。

```bash
uv run nats-bootstrap up -- -js -a 127.0.0.1 -p 4222 -m 8222 -P nats-server.pid
uv run nats-bootstrap down --confirm
```

制約：`down` は `--confirm` と `./nats-server.pid` が前提です。

### 5d) （Windows向け）service 管理

```bash
uv run nats-bootstrap service --help
```

`service` は Windows 向け運用コマンドです。

## 6) （任意）HTTP認証（API key）

運用で保護が必要な場合のみ有効化します。

```bash
export PYOCO_HTTP_AUTH_MODE="api_key"
export PYOCO_AUTH_KV_BUCKET="pyoco_auth"
export PYOCO_HTTP_API_KEY_HEADER="X-API-Key"
uv run python -m pyoco_server.admin_cli api-key create --tenant demo
```

## 7) （任意）wheel同期

```bash
export PYOCO_WHEEL_SYNC_ENABLED="1"
export PYOCO_WHEEL_SYNC_DIR=".pyoco/wheels"
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1 --wheel-sync
```

```bash
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/my_task_ext-0.1.0-py3-none-any.whl --tags hello,linux
uv run pyoco-client --server http://127.0.0.1:8000 wheels
uv run pyoco-client --server http://127.0.0.1:8000 wheel-history --limit 20
```
