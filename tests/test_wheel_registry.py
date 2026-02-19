import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import types

import httpx
from nats.js import api
import pyoco

from pyoco_server import NatsBackendConfig, PyocoNatsWorker


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


def test_http_wheel_registry_endpoints_upload_list_download_delete():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    http_port = _free_port()
    wheel_name = "demo_pkg-0.1.0-py3-none-any.whl"
    wheel_bytes = b"fake-wheel-bytes-v1"

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
        http_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)
            env = {
                "PYOCO_NATS_URL": f"nats://127.0.0.1:{nats_port}",
                "PYOCO_LOAD_DOTENV": "0",
            }
            http_proc = subprocess.Popen(
                [
                    ".venv/bin/python",
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(http_port),
                    "--log-level",
                    "warning",
                ],
                env={**os.environ, **env},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            base_url = f"http://127.0.0.1:{http_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            with httpx.Client(base_url=base_url, timeout=5.0) as hc:
                resp = hc.post(
                    "/wheels",
                    files={"wheel": (wheel_name, wheel_bytes, "application/octet-stream")},
                    data={"replace": "true", "tags": "gpu,linux"},
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["name"] == wheel_name
                assert int(body["size_bytes"]) == len(wheel_bytes)
                assert body["tags"] == ["gpu", "linux"]

                history_after_upload = hc.get("/wheels/history")
                assert history_after_upload.status_code == 200, history_after_upload.text
                uploaded_items = history_after_upload.json()
                assert len(uploaded_items) >= 1
                uploaded_evt = uploaded_items[0]
                assert uploaded_evt["action"] == "upload"
                assert uploaded_evt["wheel_name"] == wheel_name
                assert uploaded_evt["tags"] == ["gpu", "linux"]
                assert uploaded_evt.get("source") is not None
                assert "remote_addr" in uploaded_evt["source"]

                listed = hc.get("/wheels")
                assert listed.status_code == 200, listed.text
                items = listed.json()
                assert len(items) == 1
                assert items[0]["name"] == wheel_name
                assert items[0]["tags"] == ["gpu", "linux"]

                downloaded = hc.get(f"/wheels/{wheel_name}")
                assert downloaded.status_code == 200, downloaded.text
                assert downloaded.content == wheel_bytes

                deleted = hc.delete(f"/wheels/{wheel_name}")
                assert deleted.status_code == 200, deleted.text
                assert deleted.json()["deleted"] is True

                history_after_delete = hc.get("/wheels/history", params={"wheel_name": wheel_name})
                assert history_after_delete.status_code == 200, history_after_delete.text
                history_items = history_after_delete.json()
                assert len(history_items) >= 2
                assert history_items[0]["action"] == "delete"
                assert history_items[0]["wheel_name"] == wheel_name
                assert history_items[1]["action"] == "upload"

                listed_after = hc.get("/wheels")
                assert listed_after.status_code == 200, listed_after.text
                assert listed_after.json() == []
        finally:
            if http_proc is not None:
                http_proc.terminate()
                http_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_http_wheel_registry_upload_requires_strict_version_bump():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    http_port = _free_port()

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
        http_proc = None
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)
            env = {
                "PYOCO_NATS_URL": f"nats://127.0.0.1:{nats_port}",
                "PYOCO_LOAD_DOTENV": "0",
            }
            http_proc = subprocess.Popen(
                [
                    ".venv/bin/python",
                    "-m",
                    "uvicorn",
                    "pyoco_server.http_api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(http_port),
                    "--log-level",
                    "warning",
                ],
                env={**os.environ, **env},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            base_url = f"http://127.0.0.1:{http_port}"
            _wait_http(f"{base_url}/health", timeout=15.0)

            with httpx.Client(base_url=base_url, timeout=5.0) as hc:
                v1_name = "demo_pkg-0.1.0-py3-none-any.whl"
                v1 = hc.post(
                    "/wheels",
                    files={"wheel": (v1_name, b"demo-v1", "application/octet-stream")},
                    data={"replace": "true", "tags": "cpu"},
                )
                assert v1.status_code == 200, v1.text

                same_version = hc.post(
                    "/wheels",
                    files={"wheel": ("demo_pkg-0.1.0-py3-none-any.whl", b"demo-v1b", "application/octet-stream")},
                    data={"replace": "true", "tags": "cpu"},
                )
                assert same_version.status_code == 409, same_version.text
                assert "bump version" in same_version.text.lower()

                older = hc.post(
                    "/wheels",
                    files={"wheel": ("demo_pkg-0.0.9-py3-none-any.whl", b"demo-v0", "application/octet-stream")},
                    data={"replace": "true", "tags": "cpu"},
                )
                assert older.status_code == 409, older.text
                assert "must be greater" in older.text.lower()

                v2_name = "demo_pkg-0.2.0-py3-none-any.whl"
                v2 = hc.post(
                    "/wheels",
                    files={"wheel": (v2_name, b"demo-v2", "application/octet-stream")},
                    data={"replace": "true", "tags": "cpu"},
                )
                assert v2.status_code == 200, v2.text

                listed = hc.get("/wheels")
                assert listed.status_code == 200, listed.text
                names = {item["name"] for item in listed.json()}
                assert names == {v1_name, v2_name}
        finally:
            if http_proc is not None:
                http_proc.terminate()
                http_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_worker_wheel_sync_downloads_only_tag_matched_latest_wheels():
    nats_server = shutil.which("nats-server")
    assert nats_server, "nats-server not found (expected via nats-server-bin)"

    nats_port = _free_port()
    mon_port = _free_port()
    wheel_cpu_old = "task_cpu-0.1.0-py3-none-any.whl"
    wheel_cpu_new = "task_cpu-0.2.0-py3-none-any.whl"
    wheel_cpu_incompatible = "task_cpu-0.4.0-cp312-cp312-win_amd64.whl"
    wheel_gpu = "task_gpu-0.1.0-py3-none-any.whl"
    wheel_shared = "task_shared-0.1.0-py3-none-any.whl"

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
        try:
            _wait_tcp("127.0.0.1", nats_port, timeout=10.0)

            def resolve_flow(name: str) -> pyoco.Flow:
                raise KeyError(name)

            with tempfile.TemporaryDirectory() as wheel_dir:
                cfg = NatsBackendConfig(
                    nats_url=f"nats://127.0.0.1:{nats_port}",
                    wheel_sync_enabled=True,
                    wheel_sync_dir=wheel_dir,
                    wheel_sync_interval_sec=0.1,
                )

                async def scenario() -> None:
                    worker = await PyocoNatsWorker.connect(
                        config=cfg,
                        flow_resolver=resolve_flow,
                        worker_id="wheel-sync",
                        tags=["cpu"],
                    )
                    installed: list[str] = []

                    async def fake_install(self, wheel_path: Path) -> None:
                        installed.append(wheel_path.name)

                    worker._install_wheel_file = types.MethodType(fake_install, worker)

                    await worker._wheel_store.put(
                        wheel_cpu_old,
                        b"wheel-cpu-v1",
                        meta=api.ObjectMeta(
                            name=wheel_cpu_old,
                            headers={"x-pyoco-wheel-tags": "cpu,linux"},
                        ),
                    )
                    await worker._wheel_store.put(
                        wheel_cpu_new,
                        b"wheel-cpu-v2",
                        meta=api.ObjectMeta(
                            name=wheel_cpu_new,
                            headers={"x-pyoco-wheel-tags": "cpu,linux"},
                        ),
                    )
                    await worker._wheel_store.put(
                        wheel_cpu_incompatible,
                        b"wheel-cpu-v4-win",
                        meta=api.ObjectMeta(
                            name=wheel_cpu_incompatible,
                            headers={"x-pyoco-wheel-tags": "cpu,linux"},
                        ),
                    )
                    await worker._wheel_store.put(
                        wheel_gpu,
                        b"wheel-gpu-v1",
                        meta=api.ObjectMeta(
                            name=wheel_gpu,
                            headers={"x-pyoco-wheel-tags": "gpu"},
                        ),
                    )
                    await worker._wheel_store.put(wheel_shared, b"wheel-shared-v1")
                    await worker._maybe_sync_wheels(force=True)
                    assert set(installed) == {wheel_cpu_new, wheel_shared}
                    assert wheel_cpu_old not in installed
                    assert wheel_cpu_incompatible not in installed

                    # No new matching revision -> no reinstall.
                    await worker._maybe_sync_wheels(force=True)
                    assert set(installed) == {wheel_cpu_new, wheel_shared}

                    # Non-matching wheel update should not install.
                    await worker._wheel_store.put(
                        wheel_gpu,
                        b"wheel-gpu-v2",
                        meta=api.ObjectMeta(
                            name=wheel_gpu,
                            headers={"x-pyoco-wheel-tags": "gpu"},
                        ),
                    )
                    await worker._maybe_sync_wheels(force=True)
                    assert installed.count(wheel_gpu) == 0

                    # Matching wheel update should install once more.
                    await worker._wheel_store.put(
                        "task_cpu-0.3.0-py3-none-any.whl",
                        b"wheel-cpu-v3",
                        meta=api.ObjectMeta(
                            name="task_cpu-0.3.0-py3-none-any.whl",
                            headers={"x-pyoco-wheel-tags": "cpu,linux"},
                        ),
                    )
                    await worker._maybe_sync_wheels(force=True)
                    assert installed.count(wheel_cpu_new) == 1
                    assert installed.count("task_cpu-0.3.0-py3-none-any.whl") == 1

                    wheel_old_path = Path(wheel_dir) / wheel_cpu_old
                    wheel_prev_path = Path(wheel_dir) / wheel_cpu_new
                    wheel_path = Path(wheel_dir) / "task_cpu-0.3.0-py3-none-any.whl"
                    assert not wheel_old_path.exists()
                    assert not wheel_prev_path.exists()
                    assert wheel_path.is_file()
                    assert wheel_path.read_bytes() == b"wheel-cpu-v3"

                    entry = await worker._workers_kv.get("wheel-sync")
                    worker_record = json.loads(entry.value.decode("utf-8"))
                    wheel_sync = worker_record.get("wheel_sync") or {}
                    assert wheel_sync.get("enabled") is True
                    assert wheel_sync.get("last_result") == "ok"
                    assert int(wheel_sync.get("skipped_incompatible_count") or 0) >= 1
                    skipped = wheel_sync.get("skipped_incompatible") or []
                    assert any(item.get("wheel_name") == wheel_cpu_incompatible for item in skipped)
                    installed_wheels = wheel_sync.get("installed_wheels") or []
                    assert any(item.get("wheel_name") == "task_cpu-0.3.0-py3-none-any.whl" for item in installed_wheels)

                    await worker.close()

                asyncio.run(scenario())
        finally:
            nats_proc.terminate()
            nats_proc.wait(timeout=5)
