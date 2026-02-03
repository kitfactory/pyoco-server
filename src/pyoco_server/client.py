from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

import nats
from nats.js.errors import KeyNotFoundError

from .config import NatsBackendConfig
from .models import RunJob
from .resources import ensure_resources


class PyocoNatsClient:
    def __init__(self, nc, config: NatsBackendConfig = NatsBackendConfig()):
        self._nc = nc
        self._config = config
        self._js = nc.jetstream()
        self._kv = None

    @classmethod
    async def connect(cls, config: NatsBackendConfig = NatsBackendConfig()):
        nc = await nats.connect(config.nats_url, name="pyoco-nats-client")
        self = cls(nc, config)
        await self._init()
        return self

    async def _init(self) -> None:
        await ensure_resources(self._js, self._config)
        self._kv = await self._js.key_value(self._config.runs_kv_bucket)

    async def close(self) -> None:
        await self._nc.close()

    async def submit_run(
        self,
        flow_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        tag: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        routing_tag = (tag or self._config.default_tag).strip()
        if not routing_tag:
            routing_tag = self._config.default_tag
        if "." in routing_tag:
            raise ValueError("tag must not contain '.'")
        if not all(c.isalnum() or c in "_-" for c in routing_tag):
            raise ValueError("tag must match [A-Za-z0-9_-]+")
        stored_tags = tags or ([routing_tag] if routing_tag else [])
        job = RunJob(
            run_id=run_id,
            flow_name=flow_name,
            tag=routing_tag,
            tags=stored_tags,
            params=params or {},
            submitted_at=time.time(),
        )

        # Write initial snapshot as PENDING (worker will transition to RUNNING).
        await self._kv.put(
            run_id,
            json.dumps(
                {
                    "run_id": run_id,
                    "flow_name": flow_name,
                    "tag": routing_tag,
                    "tags": stored_tags,
                    "status": "PENDING",
                    "params": job.params,
                    "tasks": {},
                    "task_records": {},
                    "start_time": None,
                    "end_time": None,
                    "heartbeat_at": time.time(),
                    "updated_at": time.time(),
                    "error": None,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )

        await self._js.publish(
            subject=f"{self._config.work_subject_prefix}.{routing_tag}",
            payload=json.dumps(
                {
                    "run_id": job.run_id,
                    "flow_name": job.flow_name,
                    "tag": routing_tag,
                    "tags": stored_tags,
                    "params": job.params,
                    "submitted_at": job.submitted_at,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            stream=self._config.work_stream,
        )
        return run_id

    async def get_run(self, run_id: str) -> Dict[str, Any]:
        try:
            entry = await self._kv.get(run_id)
        except KeyNotFoundError:
            raise KeyError(run_id)
        raw = entry.value.decode("utf-8")
        return json.loads(raw)
