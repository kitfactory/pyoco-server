import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import threading

import pyoco
import nats

from pyoco_server import NatsBackendConfig, PyocoHttpClient, PyocoNatsClient, PyocoNatsWorker


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_tcp(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"port not ready: {host}:{port}")


def _wait_http(url: str, timeout: float = 10.0) -> None:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=0.5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.05)
    raise TimeoutError(f"http not ready: {url}")


def _build_flow(flow_name: str) -> pyoco.Flow:
    @pyoco.task
    def t1():
        return 1

    @pyoco.task
    def t2(ctx):
        # Validate that params/results wiring works.
        assert ctx.results["t1"] == 1
        return "ok"

    flow = pyoco.Flow(name=flow_name)
    flow.add_task(t1.task)
    flow.add_task(t2.task)
    t2.task.dependencies.add(t1.task)
    t1.task.dependents.add(t2.task)
    return flow


def test_e2e_submit_and_run_with_ephemeral_nats():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    # Demonstrate nats-bootstrap can resolve the binary.
    nats_bootstrap = shutil.which("nats-bootstrap")
    assert nats_bootstrap, "nats-bootstrap not found"
    with tempfile.TemporaryDirectory() as td:
        cfg_path = os.path.join(td, "nats-config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"nats_server_path": nats_server}, f)
        status = subprocess.run(
            [nats_bootstrap, "--config", cfg_path, "status"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert status.returncode == 0, status.stderr

    port = _free_port()
    mon_port = _free_port()
    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            cfg = NatsBackendConfig(nats_url=f"nats://127.0.0.1:{port}")

            flow_name = "main"
            flow = _build_flow(flow_name)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == flow_name
                return flow

            async def scenario():
                client = await PyocoNatsClient.connect(cfg)
                worker = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="t0",
                    tags=["default"],
                )
                try:
                    run_id = await client.submit_run(flow_name, params={"hello": "world"}, tag="default")
                    processed = await worker.run_once(timeout=5.0)
                    assert processed == run_id

                    snap = await client.get_run(run_id)
                    assert snap["status"] == "COMPLETED"
                    assert snap["tasks"]["t1"] == "SUCCEEDED"
                    assert snap["tasks"]["t2"] == "SUCCEEDED"
                finally:
                    await worker.close()
                    await client.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_flow_not_found_is_failed_and_dlqed():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()
    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            cfg = NatsBackendConfig(nats_url=f"nats://127.0.0.1:{port}")

            # Make the flow deterministic "not found".
            def resolve_flow(name: str) -> pyoco.Flow:
                raise KeyError(name)

            async def scenario():
                client = await PyocoNatsClient.connect(cfg)
                worker = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="w-missing",
                    tags=["missing"],
                )
                nc_dlq = await nats.connect(cfg.nats_url, name="pyoco-test-dlq")
                js = nc_dlq.jetstream()
                dlq_sub = await js.pull_subscribe(
                    subject=f"{cfg.dlq_subject_prefix}.missing",
                    durable="test_dlq_missing",
                    stream=cfg.dlq_stream,
                )
                try:
                    run_id = await client.submit_run("no_such_flow", params={}, tag="missing")
                    processed = await worker.run_once(timeout=10.0)
                    assert processed == run_id

                    snap = await client.get_run(run_id)
                    assert snap["status"] == "FAILED"
                    assert "flow_not_found" in (snap.get("error") or "")

                    msgs = await dlq_sub.fetch(1, timeout=5.0)
                    assert len(msgs) == 1
                    body = json.loads(msgs[0].data.decode("utf-8"))
                    assert body["reason"] == "flow_not_found"
                    assert body.get("run_id") == run_id
                    assert body.get("flow_name") == "no_such_flow"
                    assert body.get("tag") == "missing"
                    assert body.get("worker_id") == "w-missing"
                finally:
                    await worker.close()
                    await client.close()
                    await nc_dlq.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_consumer_is_created_with_default_contract():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            tag = "contract"
            cfg = NatsBackendConfig(
                nats_url=f"nats://127.0.0.1:{port}",
                consumer_ack_wait_sec=12.0,
                consumer_max_deliver=7,
                consumer_max_ack_pending=99,
            )

            def resolve_flow(name: str) -> pyoco.Flow:
                raise KeyError(name)

            async def scenario():
                # Creating the worker should create (or bind to) the durable consumer.
                worker = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w-contract", tags=[tag]
                )
                nc = await nats.connect(cfg.nats_url, name="pyoco-test-consumer-info")
                js = nc.jetstream()
                try:
                    info = await js.consumer_info(cfg.work_stream, f"{cfg.consumer_prefix}_{tag}")
                    assert info.config.filter_subject == f"{cfg.work_subject_prefix}.{tag}"
                    assert int(info.config.max_deliver) == int(cfg.consumer_max_deliver)
                    assert int(info.config.max_ack_pending) == int(cfg.consumer_max_ack_pending)
                    aw = info.config.ack_wait
                    if hasattr(aw, "total_seconds"):
                        seconds = float(aw.total_seconds())
                    else:
                        awf = float(aw)
                        # Some representations are nanoseconds; normalize heuristically.
                        seconds = awf / 1e9 if awf > 1e6 else awf
                    assert abs(seconds - float(cfg.consumer_ack_wait_sec)) < 1e-6
                finally:
                    await nc.close()
                    await worker.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_invalid_job_is_term_and_dlqed():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            tag = "badjob"
            cfg = NatsBackendConfig(nats_url=f"nats://127.0.0.1:{port}")

            def resolve_flow(name: str) -> pyoco.Flow:
                raise KeyError(name)

            async def scenario():
                worker = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w-badjob", tags=[tag]
                )

                nc = await nats.connect(cfg.nats_url, name="pyoco-test-badjob")
                js = nc.jetstream()
                dlq_sub = await js.pull_subscribe(
                    subject=f"{cfg.dlq_subject_prefix}.{tag}",
                    durable=f"dlq_{tag}",
                    stream=cfg.dlq_stream,
                )
                try:
                    # Publish an invalid payload to the work queue.
                    await js.publish(
                        subject=f"{cfg.work_subject_prefix}.{tag}",
                        payload=b"not-json",
                        stream=cfg.work_stream,
                    )
                    processed = await worker.run_once(timeout=10.0)
                    assert processed is None

                    msgs = await dlq_sub.fetch(1, timeout=5.0)
                    assert msgs, "expected a DLQ message"
                    body = json.loads(msgs[0].data.decode("utf-8"))
                    assert body.get("reason") == "invalid_job"
                    assert body.get("worker_id") == "w-badjob"
                    assert body.get("subject") == f"{cfg.work_subject_prefix}.{tag}"
                finally:
                    await nc.close()
                    await worker.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_execution_error_is_failed_and_dlqed():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            tag = "execerr"
            cfg = NatsBackendConfig(nats_url=f"nats://127.0.0.1:{port}")

            @pyoco.task
            def boom():
                raise ValueError("boom")

            flow = pyoco.Flow(name="main")
            flow.add_task(boom.task)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == "main"
                return flow

            async def scenario():
                client = await PyocoNatsClient.connect(cfg)
                worker = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w-execerr", tags=[tag]
                )

                nc_dlq = await nats.connect(cfg.nats_url, name="pyoco-test-execerr-dlq")
                js = nc_dlq.jetstream()
                dlq_sub = await js.pull_subscribe(
                    subject=f"{cfg.dlq_subject_prefix}.{tag}",
                    durable=f"dlq_{tag}",
                    stream=cfg.dlq_stream,
                )
                try:
                    run_id = await client.submit_run("main", params={}, tag=tag)
                    processed = await worker.run_once(timeout=10.0)
                    assert processed == run_id

                    snap = await client.get_run(run_id)
                    assert snap["status"] == "FAILED"
                    assert "boom" in (snap.get("error") or "")

                    msgs = await dlq_sub.fetch(1, timeout=5.0)
                    assert msgs, "expected a DLQ message"
                    body = json.loads(msgs[0].data.decode("utf-8"))
                    assert body.get("reason") == "execution_error"
                    assert body.get("run_id") == run_id
                    assert body.get("flow_name") == "main"
                    assert body.get("tag") == tag
                    assert body.get("worker_id") == "w-execerr"
                finally:
                    await nc_dlq.close()
                    await worker.close()
                    await client.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_kv_failure_causes_nak_and_redelivery():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            tag = "kvfail"
            cfg = NatsBackendConfig(nats_url=f"nats://127.0.0.1:{port}")

            @pyoco.task
            def t1():
                return "ok"

            flow = pyoco.Flow(name="main")
            flow.add_task(t1.task)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == "main"
                return flow

            async def delete_kv_stream() -> None:
                nc = await nats.connect(cfg.nats_url, name="pyoco-test-kv-delete")
                js = nc.jetstream()
                try:
                    await js.delete_stream(f"KV_{cfg.runs_kv_bucket}")
                finally:
                    await nc.close()

            async def scenario():
                client = await PyocoNatsClient.connect(cfg)

                w1 = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w-kvfail-1", tags=[tag]
                )
                try:
                    # Submit while KV is healthy (client writes initial snapshot + publishes the job).
                    run_id = await client.submit_run("main", params={}, tag=tag)

                    # Break KV after submit while keeping the worker instance alive, so KV writes fail mid-flight.
                    await delete_kv_stream()

                    r1 = await w1.run_once(timeout=10.0)
                    assert r1 == run_id
                finally:
                    await w1.close()

                # NAK delay is 2s in the worker; wait a bit before retrying.
                await asyncio.sleep(2.5)

                # A new worker should recreate resources and be able to process the redelivered job.
                w2 = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w-kvfail-2", tags=[tag]
                )
                try:
                    r2 = await w2.run_once(timeout=10.0)
                    assert r2 == run_id

                    snap = await client.get_run(run_id)
                    assert snap["status"] == "COMPLETED"
                finally:
                    await w2.close()
                    await client.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_long_task_heartbeat_and_running_visibility():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()
    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            cfg = NatsBackendConfig(
                nats_url=f"nats://127.0.0.1:{port}",
                run_heartbeat_interval_sec=0.2,
                worker_heartbeat_interval_sec=0.5,
                workers_kv_ttl_sec=2.0,
            )

            @pyoco.task
            def slow():
                time.sleep(1.2)
                return "done"

            flow_name = "main"
            flow = pyoco.Flow(name=flow_name)
            flow.add_task(slow.task)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == flow_name
                return flow

            async def scenario():
                client = await PyocoNatsClient.connect(cfg)
                worker = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="t1",
                    tags=["slow"],
                )
                try:
                    run_id = await client.submit_run(flow_name, params={}, tag="slow")

                    runner = asyncio.create_task(worker.run_once(timeout=10.0))

                    # While the run is executing, we should be able to observe RUNNING.
                    deadline = time.time() + 5.0
                    saw_running = False
                    while time.time() < deadline:
                        snap = await client.get_run(run_id)
                        if snap.get("status") == "RUNNING" and snap.get("tasks", {}).get("slow") == "RUNNING":
                            saw_running = True
                            break
                        await asyncio.sleep(0.05)

                    assert saw_running, "did not observe RUNNING state during long task"

                    processed = await runner
                    assert processed == run_id

                    snap = await client.get_run(run_id)
                    assert snap["status"] == "COMPLETED"
                    assert snap["tasks"]["slow"] == "SUCCEEDED"
                finally:
                    await worker.close()
                    await client.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_http_gateway_e2e_submit_list_and_task_status():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        nats_proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(nats_port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        api_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            env = dict(os.environ)
            env["PYOCO_NATS_URL"] = f"nats://127.0.0.1:{nats_port}"
            env["PYOCO_WORKERS_KV_TTL_SEC"] = "2.0"
            env["PYOCO_RUN_HEARTBEAT_INTERVAL_SEC"] = "0.2"
            env["PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC"] = "0.5"

            api_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            base_url = f"http://127.0.0.1:{api_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            cfg = NatsBackendConfig(nats_url=env["PYOCO_NATS_URL"])

            @pyoco.task
            def t1():
                return 1

            @pyoco.task
            def t2(ctx):
                assert ctx.results["t1"] == 1
                return "ok"

            flow = pyoco.Flow(name="main")
            flow.add_task(t1.task)
            flow.add_task(t2.task)
            t2.task.dependencies.add(t1.task)
            t1.task.dependents.add(t2.task)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == "main"
                return flow

            client = PyocoHttpClient(base_url)
            try:
                submitted = client.submit_run("main", params={"x": 1}, tag="http", tags=["http", "cpu"])
                run_id = submitted["run_id"]

                async def run_worker_once():
                    worker = await PyocoNatsWorker.connect(
                        config=cfg,
                        flow_resolver=resolve_flow,
                        worker_id="w-http",
                        tags=["http", "slow"],
                    )
                    try:
                        processed = await worker.run_once(timeout=10.0)
                        assert processed == run_id
                    finally:
                        await worker.close()

                asyncio.run(run_worker_once())

                # List endpoint should include the run.
                runs = client.list_runs(limit=200)
                assert any(r.get("run_id") == run_id for r in runs)

                # Run details should include task states.
                deadline = time.time() + 10.0
                snap = None
                while time.time() < deadline:
                    snap = client.get_run(run_id)
                    if snap.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                        break
                    time.sleep(0.05)
                assert snap is not None
                assert snap["status"] == "COMPLETED"
                assert snap["tasks"]["t1"] == "SUCCEEDED"
                assert snap["tasks"]["t2"] == "SUCCEEDED"
                assert "task_records" not in snap, "task_records should be omitted by default"

                # Tasks endpoint should provide an easy way to fetch task list + records.
                tasks = client.get_tasks(run_id)
                assert tasks["run_id"] == run_id
                assert tasks["tasks"]["t1"] == "SUCCEEDED"
                assert tasks["tasks"]["t2"] == "SUCCEEDED"
                assert tasks["task_records_truncated"] in {False, True}

                # Opt-in: fetch run with task_records included.
                full = client.get_run_with_records(run_id)
                assert full["run_id"] == run_id
                assert full["status"] == "COMPLETED"
                assert "task_records" in full
                assert isinstance(full["task_records"], dict)
            finally:
                client.close()
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_http_gateway_e2e_submit_yaml_and_run():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        nats_proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(nats_port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        api_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            env = dict(os.environ)
            env["PYOCO_NATS_URL"] = f"nats://127.0.0.1:{nats_port}"
            env["PYOCO_RUN_HEARTBEAT_INTERVAL_SEC"] = "0.2"
            env["PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC"] = "0.5"

            api_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            base_url = f"http://127.0.0.1:{api_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            cfg = NatsBackendConfig(nats_url=env["PYOCO_NATS_URL"])

            def resolve_flow(_: str) -> pyoco.Flow:
                # YAML投入のジョブでは resolver が呼ばれないことを担保したい。
                raise KeyError("unexpected_resolver_call")

            workflow_yaml = """
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
""".lstrip()

            client = PyocoHttpClient(base_url)
            try:
                submitted = client.submit_run_yaml(workflow_yaml, flow_name="train", tag="yaml")
                run_id = submitted["run_id"]

                async def run_worker_once():
                    worker = await PyocoNatsWorker.connect(
                        config=cfg,
                        flow_resolver=resolve_flow,
                        worker_id="w-yaml",
                        tags=["yaml"],
                    )
                    try:
                        processed = await worker.run_once(timeout=10.0)
                        assert processed == run_id
                    finally:
                        await worker.close()

                asyncio.run(run_worker_once())

                deadline = time.time() + 10.0
                snap = None
                while time.time() < deadline:
                    snap = client.get_run(run_id)
                    if snap.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                        break
                    time.sleep(0.05)
                assert snap is not None
                assert snap["status"] == "COMPLETED"
                assert snap["flow_name"] == "train"
                assert snap["tasks"]["add_one"] == "SUCCEEDED"
                assert snap["tasks"]["to_text"] == "SUCCEEDED"
                assert snap.get("workflow_yaml_sha256")
                assert snap.get("workflow_yaml_bytes")
            finally:
                client.close()
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_http_gateway_metrics_and_workers_endpoints():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        nats_proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(nats_port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        api_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            env = dict(os.environ)
            env["PYOCO_NATS_URL"] = f"nats://127.0.0.1:{nats_port}"
            env["PYOCO_WORKERS_KV_TTL_SEC"] = "2.0"
            env["PYOCO_RUN_HEARTBEAT_INTERVAL_SEC"] = "0.05"
            env["PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC"] = "0.1"

            api_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            base_url = f"http://127.0.0.1:{api_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            # Auth KV bucket should be created on startup (Phase 3 pre-req).
            async def check_auth_kv():
                nc = await nats.connect(env["PYOCO_NATS_URL"])
                try:
                    js = nc.jetstream()
                    await js.key_value("pyoco_auth")
                finally:
                    await nc.close()

            asyncio.run(check_auth_kv())

            cfg = NatsBackendConfig(
                nats_url=env["PYOCO_NATS_URL"],
                workers_kv_ttl_sec=2.0,
                run_heartbeat_interval_sec=0.05,
                worker_heartbeat_interval_sec=0.1,
            )

            @pyoco.task
            def slow():
                time.sleep(0.4)
                return "ok"

            flow = pyoco.Flow(name="main")
            flow.add_task(slow.task)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == "main"
                return flow

            client = PyocoHttpClient(base_url)
            try:
                submitted = client.submit_run("main", params={}, tag="m", tags=["m"])
                run_id = submitted["run_id"]

                async def run_worker_once():
                    worker = await PyocoNatsWorker.connect(
                        config=cfg,
                        flow_resolver=resolve_flow,
                        worker_id="w-metrics",
                        tags=["m"],
                    )
                    try:
                        processed = await worker.run_once(timeout=10.0)
                        assert processed == run_id
                    finally:
                        await worker.close()

                asyncio.run(run_worker_once())

                import httpx

                # /workers should expose the TTL-KV contents (best-effort).
                workers = httpx.get(f"{base_url}/workers", timeout=5.0).json()
                assert any(w.get("worker_id") == "w-metrics" for w in workers)
                w = next(w for w in workers if w.get("worker_id") == "w-metrics")
                assert "m" in (w.get("tags") or [])

                # /metrics should expose at least run status counts.
                metrics = httpx.get(f"{base_url}/metrics", timeout=5.0).text
                assert 'pyoco_runs_total{status="COMPLETED"}' in metrics or 'pyoco_runs_total{status="FAILED"}' in metrics
                assert "pyoco_workers_alive_total" in metrics
                assert "pyoco_dlq_messages_total" in metrics
            finally:
                client.close()
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_http_gateway_default_allows_submit_without_api_key():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        nats_proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(nats_port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        api_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            env = dict(os.environ)
            env["PYOCO_NATS_URL"] = f"nats://127.0.0.1:{nats_port}"
            # Default is unauthenticated.
            env.pop("PYOCO_HTTP_AUTH_MODE", None)

            api_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            base_url = f"http://127.0.0.1:{api_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            import httpx

            r = httpx.post(
                f"{base_url}/runs",
                json={"flow_name": "main", "params": {}, "tag": "default", "tags": ["default"]},
                timeout=5.0,
            )
            assert r.status_code == 200
            body = r.json()
            assert "run_id" in body
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_http_gateway_api_key_auth_and_admin_cli_e2e():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        nats_proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(nats_port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        api_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            env = dict(os.environ)
            env["PYOCO_NATS_URL"] = f"nats://127.0.0.1:{nats_port}"
            env["PYOCO_HTTP_AUTH_MODE"] = "api_key"

            api_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            base_url = f"http://127.0.0.1:{api_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            import httpx

            # Missing key -> 401
            r0 = httpx.post(
                f"{base_url}/runs",
                json={"flow_name": "main", "params": {}, "tag": "auth", "tags": ["auth"]},
                timeout=5.0,
            )
            assert r0.status_code == 401

            # Issue a key via admin CLI.
            created = subprocess.run(
                [sys.executable, "-m", "pyoco_server.admin_cli", "api-key", "create", "--tenant", "demo"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            created_body = json.loads(created.stdout)
            api_key = created_body["api_key"]
            key_id = created_body["key_id"]

            # Invalid key -> 403
            r1 = httpx.post(
                f"{base_url}/runs",
                headers={"X-API-Key": "pyoco_bad.bad"},
                json={"flow_name": "main", "params": {}, "tag": "auth", "tags": ["auth"]},
                timeout=5.0,
            )
            assert r1.status_code == 403

            # Valid key -> submit accepted
            r2 = httpx.post(
                f"{base_url}/runs",
                headers={"X-API-Key": api_key},
                json={"flow_name": "main", "params": {"x": 1}, "tag": "auth", "tags": ["auth"]},
                timeout=5.0,
            )
            assert r2.status_code == 200
            run_id = r2.json()["run_id"]

            cfg = NatsBackendConfig(nats_url=env["PYOCO_NATS_URL"])
            flow = _build_flow("main")

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == "main"
                return flow

            async def run_worker_once():
                worker = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w-auth", tags=["auth"]
                )
                try:
                    processed = await worker.run_once(timeout=10.0)
                    assert processed == run_id
                finally:
                    await worker.close()

            asyncio.run(run_worker_once())

            # Without key, reads are protected too.
            r3 = httpx.get(f"{base_url}/runs/{run_id}", timeout=5.0)
            assert r3.status_code == 401

            # With key, run snapshot should include attribution.
            deadline = time.time() + 10.0
            snap = None
            while time.time() < deadline:
                rr = httpx.get(f"{base_url}/runs/{run_id}", headers={"X-API-Key": api_key}, timeout=5.0)
                assert rr.status_code == 200
                snap = rr.json()
                if snap.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                    break
                time.sleep(0.05)
            assert snap is not None
            assert snap["tenant_id"] == "demo"
            assert snap["api_key_id"] == key_id

            # List should return only same-tenant runs.
            rlist = httpx.get(f"{base_url}/runs", headers={"X-API-Key": api_key}, timeout=5.0)
            assert rlist.status_code == 200
            assert any(r.get("run_id") == run_id for r in rlist.json())

            # Another tenant cannot see it (404 to avoid leaking existence).
            created2 = subprocess.run(
                [sys.executable, "-m", "pyoco_server.admin_cli", "api-key", "create", "--tenant", "other"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            api_key_other = json.loads(created2.stdout)["api_key"]
            r4 = httpx.get(f"{base_url}/runs/{run_id}", headers={"X-API-Key": api_key_other}, timeout=5.0)
            assert r4.status_code == 404
            r5 = httpx.get(f"{base_url}/runs", headers={"X-API-Key": api_key_other}, timeout=5.0)
            assert r5.status_code == 200
            assert not any(r.get("run_id") == run_id for r in r5.json())

            # Revoke -> 403 on submit.
            revoked = subprocess.run(
                [sys.executable, "-m", "pyoco_server.admin_cli", "api-key", "revoke", "--key-id", key_id],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            assert json.loads(revoked.stdout)["key_id"] == key_id
            r6 = httpx.post(
                f"{base_url}/runs",
                headers={"X-API-Key": api_key},
                json={"flow_name": "main", "params": {}, "tag": "auth", "tags": ["auth"]},
                timeout=5.0,
            )
            assert r6.status_code == 403
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_ack_progress_prevents_redelivery_for_long_run():
    """
    If AckWait is smaller than run duration, JetStream would redeliver.
    We prevent this by sending msg.in_progress() periodically.
    """

    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    port = _free_port()
    mon_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_tcp("127.0.0.1", port, timeout=10.0)

            tag = "shortack"
            cfg = NatsBackendConfig(
                nats_url=f"nats://127.0.0.1:{port}",
                run_heartbeat_interval_sec=0.2,
                worker_heartbeat_interval_sec=0.5,
                workers_kv_ttl_sec=2.0,
                ack_progress_interval_sec=0.05,
            )

            counter = {"n": 0}
            lock = threading.Lock()

            def build_flow(flow_name: str) -> pyoco.Flow:
                @pyoco.task
                def slow():
                    with lock:
                        counter["n"] += 1
                    time.sleep(1.0)
                    return "ok"

                flow = pyoco.Flow(name=flow_name)
                flow.add_task(slow.task)
                return flow

            def resolve_flow(name: str) -> pyoco.Flow:
                return build_flow(name)

            async def scenario():
                client = await PyocoNatsClient.connect(cfg)
                # Create a consumer with a very small AckWait to force redelivery
                # unless ack progress is sent.
                import nats
                from nats.js import api
                from nats.js.errors import BadRequestError

                nc = await nats.connect(cfg.nats_url)
                js = nc.jetstream()
                try:
                    await js.add_consumer(
                        cfg.work_stream,
                        api.ConsumerConfig(
                            durable_name=f"{cfg.consumer_prefix}_{tag}",
                            ack_wait=0.2,
                            max_deliver=5,
                            filter_subject=f"{cfg.work_subject_prefix}.{tag}",
                        ),
                    )
                except BadRequestError:
                    pass
                finally:
                    await nc.close()

                w1 = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w1", tags=[tag]
                )
                w2 = await PyocoNatsWorker.connect(
                    config=cfg, flow_resolver=resolve_flow, worker_id="w2", tags=[tag]
                )
                try:
                    run_id = await client.submit_run("main", params={}, tag=tag)

                    t1 = asyncio.create_task(w1.run_once(timeout=10.0))
                    # Wait until w1 owns the run before starting w2.
                    deadline = time.time() + 5.0
                    while time.time() < deadline:
                        snap = await client.get_run(run_id)
                        if snap.get("worker_id") == "w1" and snap.get("status") == "RUNNING":
                            break
                        await asyncio.sleep(0.05)
                    t2 = asyncio.create_task(w2.run_once(timeout=1.5))

                    r1 = await t1
                    r2 = await t2

                    assert r1 == run_id
                    assert r2 is None, "unexpected redelivery to a second worker"
                    assert counter["n"] == 1, f"expected single execution, got {counter['n']}"
                finally:
                    await w2.close()
                    await w1.close()
                    await client.close()

            asyncio.run(scenario())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_http_submit_publish_failure_leaves_no_orphan_run():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    with tempfile.TemporaryDirectory() as store_dir:
        nats_proc = subprocess.Popen(
            [
                nats_server,
                "-js",
                "-a",
                "127.0.0.1",
                "-p",
                str(nats_port),
                "-m",
                str(mon_port),
                "-sd",
                store_dir,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        api_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            env = dict(os.environ)
            env["PYOCO_NATS_URL"] = f"nats://127.0.0.1:{nats_port}"

            api_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            base_url = f"http://127.0.0.1:{api_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            http_client = PyocoHttpClient(base_url)
            try:
                cfg = NatsBackendConfig(nats_url=env["PYOCO_NATS_URL"])

                async def kv_keys() -> list[str]:
                    nc = await nats.connect(cfg.nats_url, name="pyoco-test-kv")
                    js = nc.jetstream()
                    kv = await js.key_value(cfg.runs_kv_bucket)
                    try:
                        keys = await kv.keys()
                        return list(keys or [])
                    except Exception:
                        return []
                    finally:
                        await nc.close()

                keys_before = asyncio.run(kv_keys())

                # Force publish to fail by deleting the work stream while leaving KV intact.
                async def delete_work_stream_when_ready() -> None:
                    nc = await nats.connect(cfg.nats_url, name="pyoco-test-admin")
                    js = nc.jetstream()
                    try:
                        deadline = time.time() + 10.0
                        while True:
                            try:
                                await js.stream_info(cfg.work_stream)
                                break
                            except Exception:
                                if time.time() >= deadline:
                                    raise
                                await asyncio.sleep(0.05)
                        await js.delete_stream(cfg.work_stream)
                    finally:
                        await nc.close()

                asyncio.run(delete_work_stream_when_ready())

                import httpx

                try:
                    http_client.submit_run("main", params={}, tag="default", tags=["default"])
                    assert False, "expected HTTP 503 on publish failure"
                except httpx.HTTPStatusError as exc:
                    assert exc.response.status_code == 503

                # The server should best-effort delete the KV key to avoid orphan runs.
                keys_after = asyncio.run(kv_keys())
                assert sorted(keys_after) == sorted(keys_before)
            finally:
                http_client.close()
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


## NOTE: This file intentionally prefers real processes (nats-server/uvicorn) over mocks.
