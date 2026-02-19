from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest

from pyoco_server import server_cli


class _FakeProc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_server_cli_legacy_flat_args_sets_env_and_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(server_cli.uvicorn, "run", _fake_run)
    monkeypatch.delenv("PYOCO_NATS_URL", raising=False)
    monkeypatch.delenv("PYOCO_DASHBOARD_LANG", raising=False)

    rc = server_cli.main(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
            "--nats-url",
            "nats://example:4222",
            "--dashboard-lang",
            "ja",
        ]
    )

    assert rc == 0
    assert os.environ.get("PYOCO_NATS_URL") == "nats://example:4222"
    assert os.environ.get("PYOCO_DASHBOARD_LANG") == "ja"
    assert called["args"] == ("pyoco_server.http_api:create_app",)
    assert called["kwargs"] == {
        "factory": True,
        "host": "0.0.0.0",
        "port": 9001,
        "log_level": "warning",
    }


def test_server_cli_defaults_to_up_when_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(server_cli.uvicorn, "run", _fake_run)
    rc = server_cli.main([])
    assert rc == 0
    assert called["args"] == ("pyoco_server.http_api:create_app",)
    assert called["kwargs"]["host"] == "127.0.0.1"
    assert called["kwargs"]["port"] == 8000


def test_server_cli_with_nats_bootstrap_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_cli, "_find_nats_bootstrap", lambda: None)
    rc = server_cli.main(["up", "--with-nats-bootstrap"])
    assert rc == 1


def test_server_cli_with_nats_bootstrap_starts_and_stops_child(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_proc = _FakeProc()
    popen_calls: list[list[str]] = []
    port_checks = iter([False, False, True])
    called: dict[str, Any] = {}

    def _fake_popen(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        popen_calls.append([str(x) for x in cmd])
        return fake_proc

    def _fake_port_is_open(host: str, port: int, timeout_sec: float = 0.2) -> bool:
        del host, port, timeout_sec
        return next(port_checks)

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(server_cli, "_find_nats_bootstrap", lambda: "/bin/nats-bootstrap")
    monkeypatch.setattr(server_cli.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(server_cli, "_port_is_open", _fake_port_is_open)
    monkeypatch.setattr(server_cli.uvicorn, "run", _fake_run)
    monkeypatch.delenv("PYOCO_NATS_URL", raising=False)

    rc = server_cli.main(
        [
            "up",
            "--with-nats-bootstrap",
            "--nats-listen-host",
            "127.0.0.1",
            "--nats-client-port",
            "4222",
            "--nats-http-port",
            "8222",
        ]
    )

    assert rc == 0
    assert os.environ.get("PYOCO_NATS_URL") == "nats://127.0.0.1:4222"
    assert fake_proc.terminated is True
    assert popen_calls == [
        ["/bin/nats-bootstrap", "up", "--", "-js", "-a", "127.0.0.1", "-p", "4222", "-m", "8222"]
    ]
    assert called["args"] == ("pyoco_server.http_api:create_app",)


def test_server_cli_with_nats_bootstrap_port_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_cli, "_find_nats_bootstrap", lambda: "/bin/nats-bootstrap")
    monkeypatch.setattr(server_cli, "_port_is_open", lambda host, port, timeout_sec=0.2: True)
    rc = server_cli.main(["up", "--with-nats-bootstrap"])
    assert rc == 1


def test_server_cli_with_nats_bootstrap_rejects_mismatched_nats_url(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = server_cli.main(
        [
            "up",
            "--with-nats-bootstrap",
            "--nats-url",
            "nats://127.0.0.1:5000",
            "--nats-client-port",
            "4222",
        ]
    )
    assert rc == 1


def test_server_cli_stops_child_even_when_uvicorn_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_proc = _FakeProc()
    port_checks = iter([False, False, True])

    def _fake_popen(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        del cmd, args, kwargs
        return fake_proc

    def _fake_port_is_open(host: str, port: int, timeout_sec: float = 0.2) -> bool:
        del host, port, timeout_sec
        return next(port_checks)

    def _fake_uvicorn_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(server_cli, "_find_nats_bootstrap", lambda: "/bin/nats-bootstrap")
    monkeypatch.setattr(server_cli.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(server_cli, "_port_is_open", _fake_port_is_open)
    monkeypatch.setattr(server_cli.uvicorn, "run", _fake_uvicorn_run)

    with pytest.raises(RuntimeError, match="boom"):
        server_cli.main(["up", "--with-nats-bootstrap"])

    assert fake_proc.terminated is True


def test_server_cli_kills_child_when_terminate_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc()
    calls = {"n": 0}

    def _wait_timeout(timeout: float | None = None) -> int:
        del timeout
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="x", timeout=1.0)
        return 0

    monkeypatch.setattr(proc, "wait", _wait_timeout)
    server_cli._stop_process(proc)
    assert proc.killed is True
