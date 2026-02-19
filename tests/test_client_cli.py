from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import httpx

from pyoco_server import client_cli


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, base_url: str, *, api_key: str | None = None, api_key_header: str = "X-API-Key"):
        self.base_url = base_url
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        _FakeClient.instances.append(self)

    def close(self) -> None:
        self.closed = True

    def submit_run(self, flow_name: str, params: dict[str, Any], *, tag: str | None, tags: list[str] | None):
        self.calls.append(("submit_run", {"flow_name": flow_name, "params": params, "tag": tag, "tags": tags}))
        return {"run_id": "r-submit", "status": "PENDING"}

    def submit_run_yaml(self, workflow_yaml: str, *, flow_name: str, tag: str):
        self.calls.append(("submit_run_yaml", {"workflow_yaml": workflow_yaml, "flow_name": flow_name, "tag": tag}))
        return {"run_id": "r-yaml", "status": "PENDING"}

    def get_run(self, run_id: str):
        self.calls.append(("get_run", {"run_id": run_id}))
        return {"run_id": run_id, "status": "RUNNING"}

    def get_run_with_records(self, run_id: str):
        self.calls.append(("get_run_with_records", {"run_id": run_id}))
        return {"run_id": run_id, "status": "RUNNING", "task_records": {}}

    def get_tasks(self, run_id: str):
        self.calls.append(("get_tasks", {"run_id": run_id}))
        return {"run_id": run_id, "tasks": {}}

    def list_runs(self, *, status=None, flow=None, tag=None, full=False, limit=None):
        self.calls.append(
            ("list_runs", {"status": status, "flow": flow, "tag": tag, "full": full, "limit": limit})
        )
        return [{"run_id": "r1"}]

    def list_runs_vnext(
        self,
        *,
        status=None,
        flow=None,
        tag=None,
        full=False,
        limit=None,
        updated_after=None,
        cursor=None,
        workflow_yaml_sha256=None,
    ):
        self.calls.append(
            (
                "list_runs_vnext",
                {
                    "status": status,
                    "flow": flow,
                    "tag": tag,
                    "full": full,
                    "limit": limit,
                    "updated_after": updated_after,
                    "cursor": cursor,
                    "workflow_yaml_sha256": workflow_yaml_sha256,
                },
            )
        )
        return {"items": [{"run_id": "r2"}], "next_cursor": "c1"}

    def watch_run(self, run_id: str, *, include_records=False, since=None, timeout_sec=None):
        self.calls.append(
            (
                "watch_run",
                {"run_id": run_id, "include_records": include_records, "since": since, "timeout_sec": timeout_sec},
            )
        )
        yield {"event": "snapshot", "data": {"snapshot": {"status": "RUNNING"}}}
        yield {"event": "snapshot", "data": {"snapshot": {"status": "COMPLETED"}}}

    def cancel_run(self, run_id: str, *, wait: bool = False, timeout_sec: int | None = None):
        self.calls.append(("cancel_run", {"run_id": run_id, "wait": wait, "timeout_sec": timeout_sec}))
        status = "CANCELLED" if wait else "CANCELLING"
        return {"run_id": run_id, "status": status}

    def get_workers(self):
        self.calls.append(("get_workers", {}))
        return [{"worker_id": "w1"}]

    def list_wheels(self):
        self.calls.append(("list_wheels", {}))
        return [{"name": "x.whl", "tags": ["cpu"]}]

    def list_wheel_history(
        self,
        *,
        limit: int | None = None,
        wheel_name: str | None = None,
        action: str | None = None,
    ):
        self.calls.append(
            (
                "list_wheel_history",
                {
                    "limit": limit,
                    "wheel_name": wheel_name,
                    "action": action,
                },
            )
        )
        return [
            {
                "event_id": "e1",
                "action": "upload",
                "wheel_name": "x.whl",
                "source": {"remote_addr": "127.0.0.1"},
            }
        ]

    def upload_wheel(
        self,
        *,
        filename: str,
        data: bytes,
        replace: bool = True,
        tags: list[str] | None = None,
    ):
        self.calls.append(
            (
                "upload_wheel",
                {
                    "filename": filename,
                    "size": len(data),
                    "replace": replace,
                    "tags": tags,
                },
            )
        )
        return {"name": filename, "tags": tags or []}

    def delete_wheel(self, wheel_name: str):
        self.calls.append(("delete_wheel", {"wheel_name": wheel_name}))
        return {"name": wheel_name, "deleted": True}

    def get_metrics(self):
        self.calls.append(("get_metrics", {}))
        return "pyoco_workers_alive_total 1\n"


def _reset_fake() -> None:
    _FakeClient.instances.clear()


def test_client_cli_submit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)

    rc = client_cli.main(
        [
            "--server",
            "http://s",
            "submit",
            "--flow-name",
            "main",
            "--params",
            '{"x":1}',
            "--tag",
            "cpu",
            "--tags",
            "cpu,gpu",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert json.loads(out)["run_id"] == "r-submit"
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "submit_run"
    assert call[1]["params"] == {"x": 1}
    assert call[1]["tags"] == ["cpu", "gpu"]
    assert _FakeClient.instances[-1].closed is True


def test_client_cli_submit_with_params_file_and_param_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    params_file = tmp_path / "params.yaml"
    params_file.write_text("x: 1\ny: base\n", encoding="utf-8")

    rc = client_cli.main(
        [
            "submit",
            "--flow-name",
            "main",
            "--params-file",
            str(params_file),
            "--params",
            '{"y":"json","z":3}',
            "--param",
            "z=99",
            "--param",
            "name=alice",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert json.loads(out)["run_id"] == "r-submit"
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "submit_run"
    assert call[1]["params"] == {"x": 1, "y": "json", "z": 99, "name": "alice"}


def test_client_cli_submit_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    workflow = tmp_path / "flow.yaml"
    workflow.write_text("version: 1\nflow:\n  graph: |\n    a\n", encoding="utf-8")

    rc = client_cli.main(["submit-yaml", "--workflow-file", str(workflow), "--flow-name", "train", "--tag", "cpu"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert json.loads(out)["run_id"] == "r-yaml"
    assert _FakeClient.instances[-1].calls[0][0] == "submit_run_yaml"


def test_client_cli_watch_until_terminal(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)

    rc = client_cli.main(["watch", "r-watch", "--until-terminal"])
    out_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert rc == 0
    assert len(out_lines) == 2
    assert json.loads(out_lines[-1])["data"]["snapshot"]["status"] == "COMPLETED"
    assert _FakeClient.instances[-1].calls[0][0] == "watch_run"


def test_client_cli_workers_and_metrics(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc_workers = client_cli.main(["workers"])
    out_workers = capsys.readouterr().out.strip()
    assert rc_workers == 0
    assert json.loads(out_workers)[0]["worker_id"] == "w1"

    rc_metrics = client_cli.main(["metrics"])
    out_metrics = capsys.readouterr().out
    assert rc_metrics == 0
    assert "pyoco_workers_alive_total 1" in out_metrics


def test_client_cli_wheel_upload_with_tags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    wheel = tmp_path / "abc-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"123")

    rc = client_cli.main(["wheel-upload", "--wheel-file", str(wheel), "--tags", "cpu,gpu"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    body = json.loads(out)
    assert body["name"] == wheel.name
    assert body["tags"] == ["cpu", "gpu"]
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "upload_wheel"
    assert call[1]["tags"] == ["cpu", "gpu"]


def test_client_cli_wheel_history(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)

    rc = client_cli.main(["wheel-history", "--limit", "50", "--wheel-name", "x.whl", "--action", "upload"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    body = json.loads(out)
    assert body[0]["action"] == "upload"
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "list_wheel_history"
    assert call[1] == {"limit": 50, "wheel_name": "x.whl", "action": "upload"}


def test_client_cli_cancel(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)

    rc = client_cli.main(["cancel", "--run-id", "r-cancel", "--wait", "--timeout-sec", "12"])
    out = capsys.readouterr().out.strip()

    assert rc == 0
    body = json.loads(out)
    assert body["run_id"] == "r-cancel"
    assert body["status"] == "CANCELLED"
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "cancel_run"
    assert call[1] == {"run_id": "r-cancel", "wait": True, "timeout_sec": 12}


def test_client_cli_invalid_params(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(["submit", "--params", "[]"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERR-PYOCO-0018" in err
    assert "--params must be JSON object" in err


def test_client_cli_invalid_param_assignment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(["submit", "--param", "broken"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERR-PYOCO-0018" in err
    assert "--param must be key=value" in err


def test_client_cli_list_table_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(["list", "--output", "table"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run_id" in out
    assert "r1" in out


def test_client_cli_list_vnext_table_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(["list-vnext", "--output", "table"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run_id" in out
    assert "r2" in out
    assert "next_cursor: c1" in out


def test_client_cli_watch_status_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(["watch", "r-watch", "--output", "status", "--max-events", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "\tsnapshot\tRUNNING\t" in out


class _HttpStatusFailClient(_FakeClient):
    def get_tasks(self, run_id: str):
        req = httpx.Request("GET", f"{self.base_url}/runs/{run_id}/tasks")
        resp = httpx.Response(404, request=req, text='{"detail":"run not found"}')
        raise httpx.HTTPStatusError("boom", request=req, response=resp)


class _CancelTimeoutClient(_FakeClient):
    def cancel_run(self, run_id: str, *, wait: bool = False, timeout_sec: int | None = None):
        raise TimeoutError(f"cancel wait timeout for run_id={run_id}")


def test_client_cli_http_status_error_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _HttpStatusFailClient)
    rc = client_cli.main(["tasks", "missing"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERR-PYOCO-HTTP" in err
    assert "HTTP 404 GET /runs/missing/tasks" in err


def test_client_cli_cancel_timeout_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _CancelTimeoutClient)
    rc = client_cli.main(["cancel", "--run-id", "r-timeout", "--wait", "--timeout-sec", "1"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERR-PYOCO-CANCEL" in err
