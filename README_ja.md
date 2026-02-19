pyoco-server（Pyoco向け NATS バックエンド）
=========================================

`pyoco-server` は、Pyoco のための軽量な分散実行バックエンドです。
対象は社内システム（単一組織・少人数運用）であり、大規模な厳格マルチテナント基盤は目的にしていません。

バージョン: 0.5.0

位置づけ
--------

- 役割: 分散実行バックエンド（HTTP Gateway + Worker + NATS JetStream）
- 最適化対象: 1チームが運用する社内基盤
- 非ゴール: 厳格なテナント分離を前提にした大規模基盤

価値提案（`nats-bootstrap` 連携）
--------------------------------

`pyoco-server` は実行バックエンドに集中し、NATS の運用手順は
`nats-bootstrap` のCLIに寄せる構成を想定します。

- 対称運用: 単体/クラスタで同系統のCLI手順を使える
- Day-2運用: `join/leave/doctor/backup/restore/service` を含む運用操作をCLIで実施できる
- 複雑性: 小チームでも扱える運用粒度を維持する

根拠コマンド:

```bash
uv run nats-bootstrap --help
uv run nats-bootstrap up --help
uv run nats-bootstrap join --help
uv run nats-bootstrap status --help
uv run nats-bootstrap doctor --help
uv run nats-bootstrap backup --help
uv run nats-bootstrap restore --help
uv run nats-bootstrap leave --help
uv run nats-bootstrap down --help
uv run nats-bootstrap service --help
uv run nats-bootstrap controller --help
```

適用範囲
--------

Fitするケース:

- 1チームで管理する社内基盤
- HTTP投入 + NATS JetStream でrunを分散実行したい
- Docker中心で、導入と運用を軽くしたい

Fitしないケース:

- 厳格なマルチテナント分離（強い境界制御）
- 組織間の強い監査分離が必須
- 超大規模SLAを前提にした複雑な公平制御・隔離制御

最短クイックスタート
----------------------

最短手順（`pyoco-server + nats-bootstrap` の同時起動）:

```bash
uv sync
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1
```

YAML投入例:

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

uv run pyoco-client --server http://127.0.0.1:8000 submit-yaml --workflow-file flow.yaml --flow-name main --tag hello
uv run pyoco-client --server http://127.0.0.1:8000 watch <run_id> --until-terminal --output status
```

単体NATS起動とクラスタ起動の両方の詳細は `docs/quickstart.md` を参照してください。

運用制約（現状仕様）
--------------------

1. `backup/restore` は `nats` CLI 前提
- `backup --help` / `restore --help` に `--nats-cli-path` がある
- `nats` CLI が解決できないと失敗する

2. `leave/controller` はMVP制約あり
- `leave` は `--confirm` と controller endpoint が必須
- `--controller` は NATS monitor ポートではなく、`nats-bootstrap controller start` のendpointを指定する
- `--stop-anyway` 指定時、controller 不達でも成功扱いにできるが、MVPではローカル停止は実行しない
- `controller` は現状 `start` 操作のみ

3. `down` は pid ファイル前提
- `down` は `--confirm` と `./nats-server.pid` が必要
- pidファイルが無い/不正なら失敗する
- `down` を使う場合は PID 出力付きで起動する

```bash
uv run nats-bootstrap up -- -js -a 127.0.0.1 -p 4222 -m 8222 -P nats-server.pid
uv run nats-bootstrap down --confirm
```

主要CLI
-------

- `pyoco-server`: HTTP Gateway起動
- `pyoco-worker`: Worker起動
- `pyoco-client`: run投入/参照/監視/運用操作
- `pyoco-server-admin`: API key管理

ドキュメント
------------

- Concept: `docs/concept.md`
- Spec: `docs/spec.md`
- Architecture: `docs/architecture.md`
- Quickstart: `docs/quickstart.md`
- Config: `docs/config.md`
- Plan: `docs/plan.md`

開発
----

```bash
uv sync
uv run pytest
```
