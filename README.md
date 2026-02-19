pyoco-server (NATS backend for Pyoco)
====================================

This repository is an early-stage library that enables **distributed execution**
of **Pyoco** workflows using **NATS** (JetStream) as the transport and durable
queue.

Version: 0.5.0

Goals
-----

- Run Pyoco flows with a lightweight client/worker model.
- Use NATS JetStream for a durable work queue (pull-based workers, tag routing).
- Provide run status visibility (latest snapshot via JetStream Key-Value).
- Provide an optional HTTP gateway so Pyoco users do not need to handle NATS.
- Keep local dev/test setup simple: start NATS with `nats-server-bin` and manage
  it with `nats-bootstrap`.

Current state
-------------

This repo is under active construction. See `docs/concept.md` for the initial
architecture and message design.

Quickstart
----------

See `docs/quickstart.md` for a 5-minute end-to-end demo (HTTP submit -> NATS queue -> worker execution -> status query).

CLI commands
------------

- `pyoco-server`: HTTP Gateway launcher
- `pyoco-worker`: worker launcher
- `pyoco-client`: HTTP client CLI (`submit/get/list/watch/tasks/workers/metrics/wheels/wheel-history/wheel-upload/wheel-delete`)
- `pyoco-server-admin`: API key management CLI

CLI UX highlights (v0.4)
------------------------

- `pyoco-client submit` supports:
  - `--params '{"x":1}'` (JSON object)
  - `--params-file params.yaml` (JSON/YAML object file)
  - `--param key=value` (repeatable, override-friendly)
- `pyoco-client list` / `list-vnext`: `--output json|table`
- `pyoco-client watch`: `--output json|status`
- User-fixable errors return exit code `1` with correction hints on stderr.

YAML-first run (recommended)
----------------------------

`.env` is loaded automatically by `NatsBackendConfig.from_env()` (default file: `.env`).
You can disable it with `PYOCO_LOAD_DOTENV=0` or change the file path with `PYOCO_ENV_FILE`.

```bash
uv sync
uv run nats-server -js -a 127.0.0.1 -p 4222 -m 8222
```

Or start server + local NATS together via `nats-bootstrap`:

```bash
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000 --dashboard-lang auto
```

```bash
export PYOCO_NATS_URL="nats://127.0.0.1:4222"
uv run pyoco-server up --host 127.0.0.1 --port 8000 --dashboard-lang auto
```

```bash
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1
```

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
uv run pyoco-client --server http://127.0.0.1:8000 list --tag hello --limit 20
uv run pyoco-client --server http://127.0.0.1:8000 list --tag hello --limit 20 --output table
uv run pyoco-client --server http://127.0.0.1:8000 watch <run_id> --until-terminal --output status
```

Tutorial (multi-worker)
-----------------------

See `docs/tutorial_multi_worker.md` for a more guided walkthrough with one server and multiple workers (CPU/GPU tags), plus ops endpoints.

Docs
----

- Concept: `docs/concept.md`
- Spec (contract): `docs/spec.md`
- Architecture: `docs/architecture.md`
- Library API (Python): `docs/library_api.md`
- Config (.env): `docs/config.md`
- Roadmap: `docs/plan.md`

Development
-----------

Prerequisites:

- Python 3.10+
- `uv`

Install dependencies:

```bash
uv sync
```

Run tests (will start an ephemeral NATS server for integration tests):

```bash
uv run pytest
```

HTTP Gateway (MVP)
------------------

Run the HTTP API (reads NATS settings from env):

```bash
export PYOCO_NATS_URL="nats://127.0.0.1:4222"
uv run pyoco-server up --host 0.0.0.0 --port 8000 --dashboard-lang auto
```

Tag routing
-----------

Runs are routed by subject:

- publish to `pyoco.work.<tag>`
- workers pull from one or more tags (OR semantics)

Wheel registry (optional)
-------------------------

`pyoco-server` exposes a wheel registry on `/wheels` backed by JetStream Object Store.
Workers can opt in to sync and install wheels automatically before processing jobs.
Workers download wheels when their worker tags intersect with wheel tags.
Wheels without tags are treated as shared for all workers.
Uploads must be a strict version bump per package (same/older version returns HTTP 409).
Wheel upload/delete operations are recorded as history with request source metadata.
Sync happens at worker startup and before the next polling cycle.
Workers do not start wheel updates in the middle of an active run.
When multiple versions exist, workers sync/install only the latest version per package.

```bash
export PYOCO_WHEEL_SYNC_ENABLED=1
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags cpu --worker-id w-cpu --wheel-sync
uv run pyoco-client --server http://127.0.0.1:8000 wheel-upload --wheel-file dist/my_ext-0.1.0-py3-none-any.whl --tags cpu,linux
uv run pyoco-client --server http://127.0.0.1:8000 wheels
uv run pyoco-client --server http://127.0.0.1:8000 wheel-history --limit 20
```
