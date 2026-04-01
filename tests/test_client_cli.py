from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import zipfile

import pytest
import httpx

from pyoco_server import client_cli


def _write_test_wheel(
    path: Path,
    *,
    with_entry_points: bool = True,
    with_usage_doc: bool = True,
) -> None:
    dist_info = "demo_ext-0.1.0.dist-info"
    metadata_lines = [
        "Metadata-Version: 2.1",
        "Name: demo_ext",
        "Version: 0.1.0",
        "Summary: demo extension",
    ]
    if with_usage_doc:
        metadata_lines.extend(
            [
                "Project-URL: Documentation, https://example.com/demo_ext",
                "",
                "This package provides demo extension usage guidance for operators.",
            ]
        )
    metadata_text = "\n".join(metadata_lines) + "\n"

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{dist_info}/METADATA", metadata_text)
        zf.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        if with_entry_points:
            zf.writestr(f"{dist_info}/entry_points.txt", "[console_scripts]\ndemo-ext = demo_ext.cli:main\n")


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

    def create_yaml_schedule(
        self,
        workflow_yaml: str,
        *,
        flow_name: str,
        tag: str,
        run_at: str | None = None,
        interval_seconds: float | None = None,
        start_at: str | None = None,
    ):
        self.calls.append(
            (
                "create_yaml_schedule",
                {
                    "workflow_yaml": workflow_yaml,
                    "flow_name": flow_name,
                    "tag": tag,
                    "run_at": run_at,
                    "interval_seconds": interval_seconds,
                    "start_at": start_at,
                },
            )
        )
        return {
            "schedule_id": "sch-1",
            "status": "ACTIVE",
            "schedule_type": ("once" if run_at else "interval"),
            "next_run_at": 123.0,
            "flow_name": flow_name,
            "tag": tag,
            "workflow_yaml_bytes": len(workflow_yaml.encode("utf-8")),
            "created_at": 1.0,
            "updated_at": 1.0,
            "dispatch_count": 0,
        }

    def list_schedules(self):
        self.calls.append(("list_schedules", {}))
        return [{"schedule_id": "sch-1", "status": "ACTIVE"}]

    def list_schedule_runs(self, schedule_id: str, *, include_records: bool = False, limit: int | None = None):
        self.calls.append(
            (
                "list_schedule_runs",
                {"schedule_id": schedule_id, "include_records": include_records, "limit": limit},
            )
        )
        return [{"run_id": "r-sch-1", "schedule_id": schedule_id, "status": "COMPLETED"}]

    def delete_schedule(self, schedule_id: str):
        self.calls.append(("delete_schedule", {"schedule_id": schedule_id}))
        return {"schedule_id": schedule_id, "deleted": True}

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

    def get_workers(
        self,
        *,
        scope=None,
        state=None,
        include_hidden=None,
        limit=None,
    ):
        self.calls.append(
            (
                "get_workers",
                {"scope": scope, "state": state, "include_hidden": include_hidden, "limit": limit},
            )
        )
        return [
            {
                "worker_id": "w1",
                "state": "IDLE",
                "tags": ["cpu", "linux"],
                "wheel_sync": {
                    "installed_wheels": [
                        {
                            "package_name": "demo_ext",
                            "package_version": "0.1.0",
                            "wheel_name": "demo_ext-0.1.0-py3-none-any.whl",
                        }
                    ]
                },
            }
        ]

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


def test_client_cli_schedule_yaml_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    workflow = tmp_path / "flow.yaml"
    workflow.write_text("version: 1\nflow:\n  graph: |\n    a\n", encoding="utf-8")

    rc = client_cli.main(
        [
            "schedule-yaml",
            "--workflow-file",
            str(workflow),
            "--flow-name",
            "train",
            "--tag",
            "cpu",
            "--run-at",
            "2026-04-02T10:00:00+09:00",
        ]
    )
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert json.loads(out)["schedule_id"] == "sch-1"
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "create_yaml_schedule"
    assert call[1]["run_at"] == "2026-04-02T10:00:00+09:00"
    assert call[1]["interval_seconds"] is None


def test_client_cli_schedule_list_and_delete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)

    rc_list = client_cli.main(["schedules"])
    out_list = capsys.readouterr().out.strip()
    assert rc_list == 0
    assert json.loads(out_list)[0]["schedule_id"] == "sch-1"

    rc_delete = client_cli.main(["schedule-delete", "--schedule-id", "sch-1"])
    out_delete = capsys.readouterr().out.strip()
    assert rc_delete == 0
    assert json.loads(out_delete)["deleted"] is True


def test_client_cli_schedule_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)

    rc = client_cli.main(["schedule-runs", "--schedule-id", "sch-1", "--limit", "10", "--records"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert json.loads(out)[0]["run_id"] == "r-sch-1"
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "list_schedule_runs"
    assert call[1] == {"schedule_id": "sch-1", "include_records": True, "limit": 10}


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


def test_client_cli_workers_table_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(["workers", "--output", "table"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "worker_id" in out
    assert "plugin_preview" in out
    assert "demo_ext@0.1.0" in out


def test_client_cli_workers_plugins_output_with_filters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    rc = client_cli.main(
        [
            "workers",
            "--scope",
            "all",
            "--state",
            "IDLE",
            "--include-hidden",
            "--limit",
            "10",
            "--output",
            "plugins",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "wheel_name" in out
    assert "demo_ext-0.1.0-py3-none-any.whl" in out
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "get_workers"
    assert call[1] == {"scope": "all", "state": "IDLE", "include_hidden": True, "limit": 10}


def test_client_cli_wheel_upload_with_tags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    wheel = tmp_path / "abc-0.1.0-py3-none-any.whl"
    _write_test_wheel(wheel)

    rc = client_cli.main(["wheel-upload", "--wheel-file", str(wheel), "--tags", "cpu,gpu"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    body = json.loads(out)
    assert body["name"] == wheel.name
    assert body["tags"] == ["cpu", "gpu"]
    call = _FakeClient.instances[-1].calls[0]
    assert call[0] == "upload_wheel"
    assert call[1]["tags"] == ["cpu", "gpu"]


def test_client_cli_wheel_upload_preflight_missing_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    wheel = tmp_path / "abc-0.1.0-py3-none-any.whl"
    _write_test_wheel(wheel, with_entry_points=False)

    rc = client_cli.main(["wheel-upload", "--wheel-file", str(wheel)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "wheel preflight failed" in err
    assert "entry_points are missing" in err
    assert _FakeClient.instances[-1].calls == []


def test_client_cli_wheel_upload_preflight_warn_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reset_fake()
    monkeypatch.setattr(client_cli, "PyocoHttpClient", _FakeClient)
    wheel = tmp_path / "abc-0.1.0-py3-none-any.whl"
    _write_test_wheel(wheel, with_entry_points=False, with_usage_doc=False)

    rc = client_cli.main(["wheel-upload", "--wheel-file", str(wheel), "--preflight", "warn"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    body = json.loads(out)
    assert body["name"] == wheel.name


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
