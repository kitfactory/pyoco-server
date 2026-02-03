from __future__ import annotations

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
        return resp.json()

    def get_tasks(self, run_id: str) -> Dict[str, Any]:
        resp = self._client.get(f"/runs/{run_id}/tasks")
        resp.raise_for_status()
        return resp.json()
