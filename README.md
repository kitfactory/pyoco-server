pyoco-server (NATS backend for Pyoco)
====================================

`pyoco-server` is a lightweight distributed execution backend for Pyoco.
It is optimized for internal systems (single organization, small ops team),
not for a large strict multi-tenant platform.

Version: 0.5.0

Positioning
-----------

- Role: distributed execution backend (HTTP Gateway + worker + NATS JetStream).
- Optimization target: internal platform operations by one team.
- Non-goal: strict multi-tenant isolation platform with strong audit separation.

Value proposition with `nats-bootstrap`
---------------------------------------

`pyoco-server` focuses on execution, while `nats-bootstrap` handles practical
NATS operations with the same CLI family across local and cluster workflows.

- Symmetric operations: `up` / `join` / `status` / `doctor` / `backup` /
  `restore` / `leave` / `down` / `service` are provided by `nats-bootstrap`.
- Day-2 operations: lifecycle and recovery are scriptable from CLI.
- Complexity level: designed to be operable by a small team.

Evidence (commands):

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
```

Fit / Non-fit
-------------

Fit:

- One team operating one internal environment.
- Internal platform where users submit jobs via HTTP.
- Docker-centric deployment with NATS JetStream.
- "Start small, then operate" use cases needing queue + latest status + basic ops.

Non-fit:

- Strict multi-tenant boundary requirements (hard isolation per tenant).
- Strong audit/compliance separation across organizations.
- Very large-scale SLO/SLA platforms requiring advanced fairness and isolation.

Quickstart (shortest path)
--------------------------

For the shortest local path (single-node NATS managed together):

```bash
uv sync
uv run pyoco-server up --with-nats-bootstrap --host 127.0.0.1 --port 8000 --dashboard-lang auto
uv run pyoco-worker --nats-url nats://127.0.0.1:4222 --tags hello --worker-id w1
```

Then submit a YAML workflow:

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

For single-node or 3-node cluster startup details, see `docs/quickstart.md`.

Operational constraints (current behavior)
------------------------------------------

These are current constraints aligned with implemented behavior and
`nats-bootstrap` 0.0.9 CLI/runtime behavior.

1. `backup` / `restore` require `nats` CLI.
- `nats-bootstrap backup --help` and `restore --help` expose `--nats-cli-path`.
- If `nats` CLI cannot be resolved, command fails (`nats cli not found`).

2. `leave` / `controller` are MVP-scoped.
- `leave` requires `--confirm` and controller endpoint(s).
- `--controller` must point to the endpoint started by `nats-bootstrap controller start`
  (not the NATS monitor port).
- `--stop-anyway` allows success when controller is unavailable, but local stop
  is skipped in MVP behavior.
- `controller` currently provides `start` operation.

3. `down` depends on PID file in current directory.
- `down` requires `--confirm` and `./nats-server.pid`.
- If PID file is missing/invalid, `down` fails.
- If you need `down`, start NATS with PID output, e.g.:

```bash
uv run nats-bootstrap up -- -js -a 127.0.0.1 -p 4222 -m 8222 -P nats-server.pid
uv run nats-bootstrap down --confirm
```

Current state
-------------

This repo is under active construction. See `docs/concept.md` and `docs/spec.md`
for current behavior and contracts.

CLI commands
------------

- `pyoco-server`: HTTP Gateway launcher
- `pyoco-worker`: worker launcher
- `pyoco-client`: HTTP client CLI (`submit/get/list/watch/tasks/workers/metrics/wheels/wheel-history/wheel-upload/wheel-delete`)
- `pyoco-server-admin`: API key management CLI

YAML-first run (recommended)
----------------------------

`.env` is loaded automatically by `NatsBackendConfig.from_env()` (default file: `.env`).
You can disable it with `PYOCO_LOAD_DOTENV=0` or change the file path with `PYOCO_ENV_FILE`.

```bash
export PYOCO_NATS_URL="nats://127.0.0.1:4222"
uv run pyoco-server up --host 127.0.0.1 --port 8000 --dashboard-lang auto
```

Docs
----

- Japanese README: `README_ja.md`
- Concept: `docs/concept.md`
- Spec (contract): `docs/spec.md`
- Architecture: `docs/architecture.md`
- Quickstart: `docs/quickstart.md`
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
