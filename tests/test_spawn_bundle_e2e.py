import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import nats

from pyoco_server import NatsBackendConfig, PyocoHttpClient, PyocoNatsWorker


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


async def _worker_poll_loop(worker: PyocoNatsWorker, seen: list[str], stop: asyncio.Event) -> None:
    while not stop.is_set():
        run_id = await worker.run_once(timeout=0.3)
        if run_id:
            seen.append(run_id)


def test_bundle_submit_approval_and_spawn_e2e():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    bundle_yaml = """\
version: 1
workflows:
  study:
    tasks:
      prepare:
        callable: pyoco_server._workflow_test_tasks:add_one
      run_child:
        spawn: trial
        inputs:
          x: $node.prepare.output
      summarize:
        callable: pyoco_server._workflow_test_tasks:child_summary_text
    flow:
      graph: |
        prepare >> run_child >> summarize
  trial:
    tasks:
      add_one:
        callable: pyoco_server._workflow_test_tasks:add_one
      to_text:
        callable: pyoco_server._workflow_test_tasks:to_text
    flow:
      graph: |
        add_one >> to_text
submit:
  entry_workflow: study
  inputs:
    x: 1
"""

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
        http_client = None
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
            cfg = NatsBackendConfig(nats_url=env["PYOCO_NATS_URL"])

            def resolve_flow(name: str):
                raise KeyError(name)

            async def scenario():
                worker1 = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="w-bundle-1",
                    tags=["bundle"],
                )
                worker2 = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="w-bundle-2",
                    tags=["bundle"],
                )
                seen: list[str] = []
                stop = asyncio.Event()
                t1 = asyncio.create_task(_worker_poll_loop(worker1, seen, stop))
                t2 = asyncio.create_task(_worker_poll_loop(worker2, seen, stop))
                nc = await nats.connect(cfg.nats_url, name="pyoco-test-bundle")
                js = nc.jetstream()
                relations_kv = await js.key_value(cfg.run_relations_kv_bucket)
                try:
                    submitted = http_client.submit_bundle_yaml(bundle_yaml, tag="bundle")
                    root_run_id = submitted["run_id"]
                    assert submitted["status"] == "PENDING_APPROVAL"
                    assert submitted["bundle_hash"]

                    pending = http_client.get_run(root_run_id)
                    assert pending["status"] == "PENDING_APPROVAL"
                    assert pending["bundle_hash"] == submitted["bundle_hash"]

                    approved = http_client.approve_run(root_run_id, comment="ok")
                    assert approved["status"] == "PENDING"
                    assert approved["approval_status"] == "approved"

                    deadline = time.time() + 20.0
                    root = None
                    while time.time() < deadline:
                        root = http_client.get_run_with_records(root_run_id)
                        if root.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                            break
                        await asyncio.sleep(0.1)
                    assert root is not None
                    assert root["status"] == "COMPLETED"
                    assert root["child_run_ids"]
                    assert root["spawn_count"] == 1
                    assert root["task_records"]["summarize"]["output"] == "COMPLETED:v=3"

                    child_run_id = root["child_run_ids"][0]
                    child = http_client.get_run_with_records(child_run_id)
                    assert child["status"] == "COMPLETED"
                    assert child["root_run_id"] == root_run_id
                    assert child["parent_run_id"] == root_run_id
                    assert child["spawned_from_task"] == "run_child"
                    assert child["bundle_hash"] == submitted["bundle_hash"]
                    assert child["result_summary"]["outputs"]["to_text"] == "v=3"

                    rel_root = json.loads((await relations_kv.get(root_run_id)).value.decode("utf-8"))
                    rel_child = json.loads((await relations_kv.get(child_run_id)).value.decode("utf-8"))
                    assert rel_root["depth"] == 0
                    assert rel_child["depth"] == 1
                    assert rel_child["root_run_id"] == root_run_id
                    assert rel_child["parent_run_id"] == root_run_id
                    assert rel_child["spawned_from_task"] == "run_child"
                finally:
                    stop.set()
                    await asyncio.gather(t1, t2, return_exceptions=True)
                    await worker2.close()
                    await worker1.close()
                    await nc.close()

            asyncio.run(scenario())
        finally:
            if http_client is not None:
                http_client.close()
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_bundle_reject_and_child_respawn_rejection_e2e():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found"

    nats_port = _free_port()
    mon_port = _free_port()
    api_port = _free_port()

    reject_bundle = """\
version: 1
workflows:
  study:
    tasks:
      run_child:
        spawn: trial
    flow:
      graph: |
        run_child
  trial:
    tasks:
      add_one:
        callable: pyoco_server._workflow_test_tasks:add_one
    flow:
      graph: |
        add_one
submit:
  entry_workflow: study
  inputs: {}
"""

    respawn_bundle = """\
version: 1
workflows:
  study:
    tasks:
      run_child:
        spawn: trial
    flow:
      graph: |
        run_child
  trial:
    tasks:
      run_grandchild:
        spawn: grandchild
    flow:
      graph: |
        run_grandchild
  grandchild:
    tasks:
      add_one:
        callable: pyoco_server._workflow_test_tasks:add_one
    flow:
      graph: |
        add_one
submit:
  entry_workflow: study
  inputs: {}
"""

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
        http_client = None
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
            cfg = NatsBackendConfig(nats_url=env["PYOCO_NATS_URL"])

            def resolve_flow(name: str):
                raise KeyError(name)

            rejected = http_client.submit_bundle_yaml(reject_bundle, tag="bundle")
            rejected_snap = http_client.reject_run(rejected["run_id"], reason="not-now")
            assert rejected_snap["status"] == "CANCELLED"
            assert rejected_snap["approval_status"] == "rejected"
            assert rejected_snap["rejection_reason"] == "not-now"

            async def scenario():
                worker1 = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="w-respawn-1",
                    tags=["bundle"],
                )
                worker2 = await PyocoNatsWorker.connect(
                    config=cfg,
                    flow_resolver=resolve_flow,
                    worker_id="w-respawn-2",
                    tags=["bundle"],
                )
                seen: list[str] = []
                stop = asyncio.Event()
                t1 = asyncio.create_task(_worker_poll_loop(worker1, seen, stop))
                t2 = asyncio.create_task(_worker_poll_loop(worker2, seen, stop))
                try:
                    submitted = http_client.submit_bundle_yaml(respawn_bundle, tag="bundle")
                    root_run_id = submitted["run_id"]
                    http_client.approve_run(root_run_id, comment="go")

                    deadline = time.time() + 20.0
                    root = None
                    while time.time() < deadline:
                        root = http_client.get_run_with_records(root_run_id)
                        if root.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                            break
                        await asyncio.sleep(0.1)
                    assert root is not None
                    assert root["status"] == "COMPLETED"
                    assert root["child_run_ids"]

                    child_run_id = root["child_run_ids"][0]
                    child = http_client.get_run_with_records(child_run_id)
                    assert child["status"] == "FAILED"
                    assert "child_respawn_not_allowed" in (child.get("error") or "")
                    assert root["task_records"]["run_child"]["output"]["status"] == "FAILED"
                finally:
                    stop.set()
                    await asyncio.gather(t1, t2, return_exceptions=True)
                    await worker2.close()
                    await worker1.close()

            asyncio.run(scenario())
        finally:
            if http_client is not None:
                http_client.close()
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)
