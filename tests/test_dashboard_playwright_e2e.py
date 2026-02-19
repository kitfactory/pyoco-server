import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pyoco
import pytest

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


def test_dashboard_playwright_e2e_with_auth_and_watch():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

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
            env["PYOCO_WORKERS_KV_TTL_SEC"] = "10.0"
            env["PYOCO_RUN_HEARTBEAT_INTERVAL_SEC"] = "0.1"
            env["PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC"] = "0.2"
            env["PYOCO_DASHBOARD_LANG"] = "ja"

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

            created = subprocess.run(
                [sys.executable, "-m", "pyoco_server.admin_cli", "api-key", "create", "--tenant", "gui"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            created_body = json.loads(created.stdout)
            api_key = created_body["api_key"]

            import httpx

            run_tag = "guiauth"
            submit = httpx.post(
                f"{base_url}/runs",
                headers={"X-API-Key": api_key},
                json={"flow_name": "main", "params": {"v": 1}, "tag": run_tag, "tags": [run_tag]},
                timeout=5.0,
            )
            assert submit.status_code == 200
            run_id = submit.json()["run_id"]

            cfg = NatsBackendConfig(
                nats_url=env["PYOCO_NATS_URL"],
                workers_kv_ttl_sec=10.0,
                run_heartbeat_interval_sec=0.1,
                worker_heartbeat_interval_sec=0.2,
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

            def worker_thread() -> None:
                async def run_once() -> None:
                    worker = await PyocoNatsWorker.connect(
                        config=cfg,
                        flow_resolver=resolve_flow,
                        worker_id="w-gui-auth",
                        tags=[run_tag],
                    )
                    try:
                        processed = await worker.run_once(timeout=10.0)
                        assert processed == run_id
                    finally:
                        await worker.close()

                asyncio.run(run_once())

            t = threading.Thread(target=worker_thread, daemon=True)
            t.start()

            with sync_playwright() as p:
                try:
                    # WSL/headless 環境の安定化オプション / Stabilize WSL headless execution.
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                except PlaywrightError as exc:
                    pytest.skip(f"playwright chromium launch failed: {exc}")

                try:
                    context = browser.new_context(viewport={"width": 390, "height": 844})
                    page = context.new_page()
                    page.goto(f"{base_url}/", wait_until="networkidle")
                    assert "たのしい運用ルーム" in (page.text_content(".subtitle") or "")

                    page.click("#runsFilters button[type='submit']")
                    page.wait_for_timeout(300)
                    assert "401" in (page.text_content("#errorLine") or "")

                    page.fill("#apiHeader", "X-API-Key")
                    page.fill("#apiKey", api_key)
                    page.click("#saveAuth")
                    page.wait_for_timeout(600)

                    page.fill("#fTag", run_tag)
                    page.click("#runsFilters button[type='submit']")

                    page.wait_for_selector(f"#runsList li:has-text('{run_id}')", timeout=15000)
                    page.click(f"#runsList li:has-text('{run_id}')")

                    page.wait_for_function(
                        """() => {
                            const body = document.querySelector('#detailJson')?.textContent || '';
                            return body.includes('"run_id": "') && body.includes('"status": "COMPLETED"');
                        }""",
                        timeout=20000,
                    )

                    page.wait_for_selector("#workersList li:has-text('w-gui-auth')", timeout=10000)
                    assert page.locator("#workersList li:has-text('w-gui-auth') .worker-state").count() >= 1

                    # hide -> listから消える（既定 include_hidden=false）
                    page.click("#workersList li:has-text('w-gui-auth') .worker-toggle-hidden")
                    page.wait_for_timeout(400)
                    assert page.locator("#workersList li:has-text('w-gui-auth')").count() == 0

                    # include_hidden=true で再表示できること
                    page.check("#wIncludeHidden")
                    page.wait_for_selector("#workersList li:has-text('w-gui-auth')", timeout=10000)

                    page.wait_for_function(
                        """() => {
                            const running = (document.querySelector('#kpiRunning')?.textContent || '').trim();
                            const completed = (document.querySelector('#kpiCompletedToday')?.textContent || '').trim();
                            const failed = (document.querySelector('#kpiFailedToday')?.textContent || '').trim();
                            return running !== '' && running !== '-' &&
                                   completed !== '' && completed !== '-' &&
                                   failed !== '' && failed !== '-';
                        }""",
                        timeout=10000,
                    )
                    page.wait_for_function(
                        """() => {
                            const v = (document.querySelector('#kpiCompletedToday')?.textContent || '').trim();
                            return v !== '' && v !== '-';
                        }""",
                        timeout=10000,
                    )
                finally:
                    browser.close()

            t.join(timeout=10.0)
            assert not t.is_alive(), "worker thread did not finish"
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)


def test_dashboard_playwright_e2e_cancel_run():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

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
            env["PYOCO_WORKERS_KV_TTL_SEC"] = "10.0"
            env["PYOCO_RUN_HEARTBEAT_INTERVAL_SEC"] = "0.1"
            env["PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC"] = "0.2"
            env["PYOCO_DASHBOARD_LANG"] = "en"
            env["PYOCO_CANCEL_GRACE_PERIOD_SEC"] = "5.0"

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

            run_tag = "gui-cancel"
            submit = httpx.post(
                f"{base_url}/runs",
                json={"flow_name": "main", "params": {"v": 1}, "tag": run_tag, "tags": [run_tag]},
                timeout=5.0,
            )
            assert submit.status_code == 200
            run_id = submit.json()["run_id"]

            cfg = NatsBackendConfig(
                nats_url=env["PYOCO_NATS_URL"],
                workers_kv_ttl_sec=10.0,
                run_heartbeat_interval_sec=0.1,
                worker_heartbeat_interval_sec=0.2,
                cancel_grace_period_sec=5.0,
            )

            @pyoco.task
            def slow():
                time.sleep(4.0)
                return "ok"

            @pyoco.task
            def after(ctx):
                return str(ctx.results.get("slow"))

            flow = pyoco.Flow(name="main")
            flow.add_task(slow.task)
            flow.add_task(after.task)
            after.task.dependencies.add(slow.task)
            slow.task.dependents.add(after.task)

            def resolve_flow(name: str) -> pyoco.Flow:
                assert name == "main"
                return flow

            def worker_thread() -> None:
                async def run_once() -> None:
                    worker = await PyocoNatsWorker.connect(
                        config=cfg,
                        flow_resolver=resolve_flow,
                        worker_id="w-gui-cancel",
                        tags=[run_tag],
                    )
                    try:
                        processed = await worker.run_once(timeout=30.0)
                        assert processed == run_id
                    finally:
                        await worker.close()

                asyncio.run(run_once())

            t = threading.Thread(target=worker_thread, daemon=True)
            t.start()

            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                except PlaywrightError as exc:
                    pytest.skip(f"playwright chromium launch failed: {exc}")

                try:
                    context = browser.new_context(viewport={"width": 1366, "height": 768})
                    page = context.new_page()
                    page.goto(f"{base_url}/", wait_until="networkidle")

                    page.fill("#fTag", run_tag)
                    page.click("#runsFilters button[type='submit']")
                    page.wait_for_selector(f"#runsList li:has-text('{run_id}')", timeout=15000)
                    page.click(f"#runsList li:has-text('{run_id}')")

                    page.wait_for_function(
                        """() => {
                            const btn = document.querySelector('#detailCancel');
                            return !!btn && btn.disabled === false;
                        }""",
                        timeout=15000,
                    )
                    page.click("#detailCancel")

                    page.wait_for_function(
                        """() => {
                            const body = document.querySelector('#detailJson')?.textContent || '';
                            return body.includes('"status": "CANCELLING"') || body.includes('"status": "CANCELLED"');
                        }""",
                        timeout=15000,
                    )

                    deadline = time.time() + 30.0
                    terminal = None
                    while time.time() < deadline:
                        rr = httpx.get(f"{base_url}/runs/{run_id}", timeout=5.0)
                        assert rr.status_code == 200
                        terminal = rr.json()
                        if str(terminal.get("status") or "").upper() in {"COMPLETED", "FAILED", "CANCELLED"}:
                            break
                        time.sleep(0.1)
                    assert terminal is not None
                    assert terminal["status"] == "CANCELLED"

                    page.click("#runsFilters button[type='submit']")
                    page.wait_for_timeout(300)
                    page.click(f"#runsList li:has-text('{run_id}')")
                    page.wait_for_function(
                        """() => {
                            const body = document.querySelector('#detailJson')?.textContent || '';
                            return body.includes('"status": "CANCELLED"');
                        }""",
                        timeout=10000,
                    )
                finally:
                    browser.close()

            t.join(timeout=30.0)
            assert not t.is_alive(), "worker thread did not finish"
        finally:
            if api_proc is not None:
                api_proc.terminate()
                api_proc.wait(timeout=5)
            nats_proc.terminate()
            nats_proc.wait(timeout=5)
