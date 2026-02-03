pyoco-server (NATS backend for Pyoco)
====================================

This repository is an early-stage library that enables **distributed execution**
of **Pyoco** workflows using **NATS** (JetStream) as the transport and durable
queue.

Version: 0.4.0

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
uv run uvicorn pyoco_server.http_api:create_app --factory --host 0.0.0.0 --port 8000
```

Tag routing
-----------

Runs are routed by subject:

- publish to `pyoco.work.<tag>`
- workers pull from one or more tags (OR semantics)
