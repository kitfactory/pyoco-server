from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import httpx


class PyocoHttpClient:
    def __init__(self, base_url: str, *, api_key: Optional[str] = None, api_key_header: str = "X-API-Key"):
        headers = {}
        if api_key:
            headers[api_key_header] = api_key
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers)

    def close(self) -> None:
        self._client.close()

    def submit_run(
        self,
        flow_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        tag: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"flow_name": flow_name, "params": params or {}}
        if tag is not None:
            payload["tag"] = tag
        if tags is not None:
            payload["tags"] = tags
        resp = self._client.post("/runs", json=payload)
        resp.raise_for_status()
        return resp.json()

    def submit_run_yaml(
        self,
        workflow_yaml: str,
        *,
        flow_name: str,
        tag: str,
    ) -> Dict[str, Any]:
        """
        Submit a single-flow workflow YAML (flow.yaml) as a run.
        単体flowのYAML（flow.yaml）を run として投入します。
        """

        files = {"workflow": ("flow.yaml", workflow_yaml.encode("utf-8"), "application/x-yaml")}
        data = {"flow_name": flow_name, "tag": tag}
        resp = self._client.post("/runs/yaml", files=files, data=data)
        resp.raise_for_status()
        return resp.json()

    def get_run(self, run_id: str) -> Dict[str, Any]:
        resp = self._client.get(f"/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()

    def cancel_run(
        self,
        run_id: str,
        *,
        wait: bool = False,
        timeout_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        resp = self._client.post(f"/runs/{run_id}/cancel")
        resp.raise_for_status()
        snap = resp.json()

        if not wait:
            return snap

        timeout = int(timeout_sec) if timeout_sec is not None else 30
        deadline = time.time() + max(1, timeout)
        while True:
            status = str((snap or {}).get("status") or "").upper()
            if status in {"COMPLETED", "FAILED", "CANCELLED"}:
                return snap
            if time.time() >= deadline:
                raise TimeoutError(f"cancel wait timeout for run_id={run_id}")
            time.sleep(0.25)
            snap = self.get_run(run_id)

    def get_run_with_records(self, run_id: str) -> Dict[str, Any]:
        resp = self._client.get(f"/runs/{run_id}", params={"include": "records"})
        resp.raise_for_status()
        return resp.json()

    def list_runs(
        self,
        *,
        status: Optional[str] = None,
        flow: Optional[str] = None,
        tag: Optional[str] = None,
        full: bool = False,
        limit: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        if flow:
            params["flow"] = flow
        if tag:
            params["tag"] = tag
        if full:
            params["include"] = "full"
        if limit is not None:
            params["limit"] = limit
        resp = self._client.get("/runs", params=params)
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict):
            items = body.get("items")
            if isinstance(items, list):
                return items
            return []
        return body

    def list_runs_vnext(
        self,
        *,
        status: Optional[str] = None,
        flow: Optional[str] = None,
        tag: Optional[str] = None,
        full: bool = False,
        limit: Optional[int] = None,
        updated_after: Optional[float] = None,
        cursor: Optional[str] = None,
        workflow_yaml_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        if flow:
            params["flow"] = flow
        if tag:
            params["tag"] = tag
        if full:
            params["include"] = "full"
        if limit is not None:
            params["limit"] = limit
        if updated_after is not None:
            params["updated_after"] = updated_after
        if cursor:
            params["cursor"] = cursor
        if workflow_yaml_sha256:
            params["workflow_yaml_sha256"] = workflow_yaml_sha256
        resp = self._client.get("/runs", params=params)
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, list):
            return {"items": body, "next_cursor": None}
        return body

    def watch_run(
        self,
        run_id: str,
        *,
        include_records: bool = False,
        since: Optional[float] = None,
        timeout_sec: Optional[int] = None,
    ):
        params: Dict[str, Any] = {}
        if include_records:
            params["include"] = "records"
        if since is not None:
            params["since"] = since
        if timeout_sec is not None:
            params["timeout_sec"] = timeout_sec

        with self._client.stream("GET", f"/runs/{run_id}/watch", params=params) as resp:
            resp.raise_for_status()
            event_name: Optional[str] = None
            data_lines: list[str] = []
            for line in resp.iter_lines():
                if line == "":
                    if data_lines:
                        payload_raw = "\n".join(data_lines)
                        try:
                            payload = json.loads(payload_raw)
                        except Exception:
                            payload = {"raw": payload_raw}
                        yield {"event": event_name or "message", "data": payload}
                    event_name = None
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())

    def get_tasks(self, run_id: str) -> Dict[str, Any]:
        resp = self._client.get(f"/runs/{run_id}/tasks")
        resp.raise_for_status()
        return resp.json()

    def get_workers(
        self,
        *,
        scope: Optional[str] = None,
        state: Optional[str] = None,
        include_hidden: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if scope:
            params["scope"] = scope
        if state:
            params["state"] = state
        if include_hidden is not None:
            params["include_hidden"] = bool(include_hidden)
        if limit is not None:
            params["limit"] = int(limit)
        resp = self._client.get("/workers", params=params)
        resp.raise_for_status()
        return resp.json()

    def patch_worker_hidden(self, worker_id: str, *, hidden: bool) -> Dict[str, Any]:
        resp = self._client.patch(f"/workers/{worker_id}", json={"hidden": bool(hidden)})
        resp.raise_for_status()
        return resp.json()

    def list_wheels(self) -> list[Dict[str, Any]]:
        resp = self._client.get("/wheels")
        resp.raise_for_status()
        return resp.json()

    def list_wheel_history(
        self,
        *,
        limit: Optional[int] = None,
        wheel_name: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = int(limit)
        if wheel_name:
            params["wheel_name"] = str(wheel_name)
        if action:
            params["action"] = str(action)
        resp = self._client.get("/wheels/history", params=params)
        resp.raise_for_status()
        return resp.json()

    def upload_wheel(
        self,
        *,
        filename: str,
        data: bytes,
        replace: bool = True,
        tags: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        files = {"wheel": (filename, data, "application/octet-stream")}
        form = {"replace": "true" if replace else "false"}
        if tags:
            form["tags"] = ",".join(str(t).strip() for t in tags if str(t).strip())
        resp = self._client.post("/wheels", files=files, data=form)
        resp.raise_for_status()
        return resp.json()

    def delete_wheel(self, wheel_name: str) -> Dict[str, Any]:
        resp = self._client.delete(f"/wheels/{wheel_name}")
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self) -> str:
        resp = self._client.get("/metrics")
        resp.raise_for_status()
        return resp.text
