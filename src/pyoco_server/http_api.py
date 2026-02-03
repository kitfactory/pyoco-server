from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Optional

import nats
from fastapi import Response
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, Field
from nats.js.errors import KeyNotFoundError
from nats.errors import Error as NatsError

from .auth import ApiKeyError, ApiKeyRecord, make_kv_key_for_api_key_id, parse_api_key, verify_api_key
from .config import NatsBackendConfig
from .logging_config import configure_logging
from .resources import ensure_resources
from .workflow_yaml import WorkflowYamlValidationError, extract_flow_defaults, parse_workflow_yaml_bytes


def config_from_env() -> NatsBackendConfig:
    return NatsBackendConfig.from_env()


class RunSubmitRequest(BaseModel):
    flow_name: str = Field(..., min_length=1)
    params: Dict[str, Any] = Field(default_factory=dict)
    # tag is used as a single subject token: <prefix>.<tag>
    # Therefore it must not contain '.'.
    tag: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    tags: list[str] = Field(default_factory=list)


class RunSubmitResponse(BaseModel):
    run_id: str
    status: str


@dataclass(frozen=True)
class _AuthContext:
    tenant_id: str
    api_key_id: str


def _filter_snapshot_for_http(
    snap: Dict[str, Any],
    *,
    include: set[str],
    mode: str,
) -> Dict[str, Any]:
    """
    Keep HTTP responses small by default.

    mode:
      - "run": GET /runs/{run_id}
      - "list": GET /runs
    """

    include_all = "all" in include or "full" in include
    include_records = include_all or ("records" in include) or ("task_records" in include)

    if mode == "list" and not include_all:
        # Summary-only list items.
        keys = {
            "run_id",
            "flow_name",
            "tag",
            "tags",
            "tenant_id",
            "api_key_id",
            "status",
            "updated_at",
            "heartbeat_at",
            "worker_id",
            "error",
        }
        snap = {k: snap.get(k) for k in keys if k in snap}

    if not include_records:
        snap.pop("task_records", None)
        snap.pop("task_records_truncated", None)

    return snap


def create_app() -> FastAPI:
    """
    FastAPI gateway that hides NATS from Pyoco users.

    Use with uvicorn:
      uvicorn pyoco_server.http_api:create_app --factory --host 0.0.0.0 --port 8000
    """

    configure_logging(service="pyoco-server:http")
    config = config_from_env()
    app = FastAPI(title="pyoco-server (HTTP gateway)", version="0.4.0")
    logger = logging.getLogger("pyoco_server.http_api")

    def _auth_enabled() -> bool:
        return str(getattr(app.state, "config", config).http_auth_mode or "none").strip().lower() == "api_key"

    async def _require_auth(request: Request) -> Optional[_AuthContext]:
        """
        Opt-in auth. When disabled, return None.
        opt-in 認証。無効な場合は None を返す。
        """

        if not _auth_enabled():
            return None

        cfg: NatsBackendConfig = app.state.config
        header = (cfg.http_api_key_header or "X-API-Key").strip() or "X-API-Key"
        presented = request.headers.get(header)
        if not presented:
            logger.info(
                "auth failed: missing api key",
                extra={"err_id": "ERR-PYOCO-0014", "msg_id": "MSG-PYOCO-0014"},
            )
            raise HTTPException(status_code=401, detail="api key required")

        try:
            key_id, _ = parse_api_key(presented)
        except ApiKeyError:
            logger.info(
                "auth failed: invalid api key format",
                extra={"err_id": "ERR-PYOCO-0015", "msg_id": "MSG-PYOCO-0015"},
            )
            raise HTTPException(status_code=403, detail="invalid api key")

        auth_kv = app.state.auth_kv
        try:
            entry = await auth_kv.get(make_kv_key_for_api_key_id(key_id))
        except KeyNotFoundError:
            logger.info(
                "auth failed: unknown api key",
                extra={"err_id": "ERR-PYOCO-0015", "msg_id": "MSG-PYOCO-0015", "api_key_id": key_id},
            )
            raise HTTPException(status_code=403, detail="invalid api key")
        except NatsError as exc:
            logger.exception(
                "auth failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003"},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        try:
            record = ApiKeyRecord.from_json_bytes(entry.value)
        except Exception:
            logger.info(
                "auth failed: corrupt api key record",
                extra={"err_id": "ERR-PYOCO-0015", "msg_id": "MSG-PYOCO-0015", "api_key_id": key_id},
            )
            raise HTTPException(status_code=403, detail="invalid api key")

        if not verify_api_key(presented, record=record, pepper=cfg.auth_pepper):
            logger.info(
                "auth failed: api key mismatch/revoked",
                extra={"err_id": "ERR-PYOCO-0015", "msg_id": "MSG-PYOCO-0015", "api_key_id": key_id},
            )
            raise HTTPException(status_code=403, detail="invalid api key")

        return _AuthContext(tenant_id=record.tenant_id, api_key_id=record.key_id)

    @app.on_event("startup")
    async def _startup() -> None:
        nc = await nats.connect(config.nats_url, name="pyoco-http-api")
        js = nc.jetstream()
        await ensure_resources(js, config)
        app.state.nc = nc
        app.state.js = js
        app.state.runs_kv = await js.key_value(config.runs_kv_bucket)
        app.state.workers_kv = await js.key_value(config.workers_kv_bucket)
        app.state.auth_kv = await js.key_value(config.auth_kv_bucket)
        app.state.config = config

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        nc = getattr(app.state, "nc", None)
        if nc is not None:
            await nc.close()

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Response:
        """
        Minimal Prometheus-style metrics endpoint.

        This is intentionally best-effort and derived from JetStream state (KV + stream info).
        """

        js = app.state.js
        runs_kv = app.state.runs_kv
        workers_kv = app.state.workers_kv

        try:
            run_keys = await runs_kv.keys()
        except NatsError as exc:
            logger.exception(
                "metrics failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003"},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        except Exception:
            run_keys = []

        # Count runs by status from snapshots.
        status_counts: dict[str, int] = {}
        for key in list(run_keys or []):
            try:
                entry = await runs_kv.get(key)
            except KeyNotFoundError:
                continue
            snap = json.loads(entry.value.decode("utf-8"))
            st = str(snap.get("status") or "UNKNOWN")
            status_counts[st] = status_counts.get(st, 0) + 1

        # Count active workers by TTL-KV keys.
        try:
            worker_keys = await workers_kv.keys()
        except Exception:
            worker_keys = []
        workers_alive = len(list(worker_keys or []))

        # DLQ total messages (not per-reason; reasons live in payload).
        dlq_msgs_total = None
        try:
            info = await js.stream_info(app.state.config.dlq_stream)
            dlq_msgs_total = int(getattr(getattr(info, "state", None), "messages", 0) or 0)
        except Exception:
            dlq_msgs_total = None

        lines: list[str] = []
        lines.append("# HELP pyoco_runs_total Count of runs by status (best-effort from KV).")
        lines.append("# TYPE pyoco_runs_total gauge")
        for st, n in sorted(status_counts.items()):
            lines.append(f'pyoco_runs_total{{status="{st}"}} {int(n)}')

        lines.append("# HELP pyoco_workers_alive_total Count of workers present in TTL KV (best-effort).")
        lines.append("# TYPE pyoco_workers_alive_total gauge")
        lines.append(f"pyoco_workers_alive_total {int(workers_alive)}")

        lines.append("# HELP pyoco_dlq_messages_total Total DLQ messages in the DLQ stream (best-effort).")
        lines.append("# TYPE pyoco_dlq_messages_total gauge")
        if dlq_msgs_total is not None:
            lines.append(f"pyoco_dlq_messages_total {int(dlq_msgs_total)}")

        body = "\n".join(lines) + "\n"
        return Response(content=body, media_type="text/plain; version=0.0.4")

    @app.get("/workers")
    async def list_workers() -> list[Dict[str, Any]]:
        workers_kv = app.state.workers_kv
        try:
            keys = await workers_kv.keys()
        except NatsError as exc:
            logger.exception(
                "workers failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003"},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        except Exception:
            keys = []

        out: list[Dict[str, Any]] = []
        for key in list(keys or []):
            try:
                entry = await workers_kv.get(key)
            except KeyNotFoundError:
                continue
            try:
                winfo = json.loads(entry.value.decode("utf-8"))
            except Exception:
                continue
            out.append(
                {
                    "worker_id": winfo.get("worker_id") or key,
                    "heartbeat_at": winfo.get("heartbeat_at"),
                    "tags": winfo.get("tags") or [],
                }
            )
        out.sort(key=lambda w: float(w.get("heartbeat_at") or 0.0), reverse=True)
        return out

    @app.post("/runs", response_model=RunSubmitResponse)
    async def submit_run(req: RunSubmitRequest, request: Request) -> RunSubmitResponse:
        js = app.state.js
        kv = app.state.runs_kv
        cfg: NatsBackendConfig = app.state.config
        auth = await _require_auth(request)

        run_id = str(uuid.uuid4())
        now = time.time()
        routing_tag = (req.tag or cfg.default_tag).strip()
        if not routing_tag:
            routing_tag = cfg.default_tag
        stored_tags = req.tags or [routing_tag]

        try:
            # Initial snapshot (client should be able to observe the run immediately).
            await kv.put(
                run_id,
                json.dumps(
                    {
                        "run_id": run_id,
                        "flow_name": req.flow_name,
                        "tag": routing_tag,
                        "tags": stored_tags,
                        "tenant_id": (auth.tenant_id if auth else None),
                        "api_key_id": (auth.api_key_id if auth else None),
                        "status": "PENDING",
                        "params": req.params or {},
                        "tasks": {},
                        "task_records": {},
                        "start_time": None,
                        "end_time": None,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "error": None,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )

            await js.publish(
                subject=f"{cfg.work_subject_prefix}.{routing_tag}",
                payload=json.dumps(
                    {
                        "run_id": run_id,
                        "flow_name": req.flow_name,
                        "tag": routing_tag,
                        "tags": stored_tags,
                        "tenant_id": (auth.tenant_id if auth else None),
                        "api_key_id": (auth.api_key_id if auth else None),
                        "params": req.params or {},
                        "submitted_at": now,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                stream=cfg.work_stream,
            )
        except NatsError as exc:
            logger.exception(
                "submit failed: nats unavailable",
                extra={
                    "err_id": "ERR-PYOCO-0003",
                    "msg_id": "MSG-PYOCO-0003",
                    "flow_name": req.flow_name,
                    "tag": routing_tag,
                    "run_id": run_id,
                },
            )
            # Best-effort cleanup to avoid orphan snapshots on submit failure.
            try:
                await kv.delete(run_id)
            except Exception:
                pass
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        return RunSubmitResponse(run_id=run_id, status="PENDING")

    @app.post("/runs/yaml", response_model=RunSubmitResponse)
    async def submit_run_yaml(
        request: Request,
        workflow: UploadFile = File(...),
        flow_name: str = Form(...),
        tag: Optional[str] = Form(default=None),
    ) -> RunSubmitResponse:
        """
        Submit a single-flow workflow (flow.yaml) as a run.
        単体flow（flow.yaml）を run として投入します。
        """

        js = app.state.js
        kv = app.state.runs_kv
        cfg: NatsBackendConfig = app.state.config
        auth = await _require_auth(request)

        routing_tag = (tag or cfg.default_tag).strip()
        if not routing_tag:
            routing_tag = cfg.default_tag
        if "." in routing_tag or not re.fullmatch(r"[A-Za-z0-9_-]+", routing_tag or ""):
            logger.info(
                "submit yaml failed: invalid tag",
                extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "tag": routing_tag},
            )
            raise HTTPException(status_code=422, detail="invalid tag")

        raw = await workflow.read()
        if len(raw) > int(cfg.workflow_yaml_max_bytes or 0):
            logger.info(
                "submit yaml failed: workflow too large",
                extra={
                    "err_id": "ERR-PYOCO-0016",
                    "msg_id": "MSG-PYOCO-0016",
                    "tag": routing_tag,
                    "size_bytes": len(raw),
                },
            )
            raise HTTPException(status_code=413, detail="workflow too large")

        try:
            parsed = parse_workflow_yaml_bytes(raw, require_flow=True)
        except WorkflowYamlValidationError as exc:
            logger.info(
                "submit yaml failed: invalid workflow yaml",
                extra={
                    "err_id": "ERR-PYOCO-0002",
                    "msg_id": "MSG-PYOCO-0002",
                    "tag": routing_tag,
                    "reason": getattr(exc, "reason", str(exc)),
                },
            )
            raise HTTPException(status_code=422, detail="invalid workflow yaml")

        # params は flow.defaults を正本とする（上書きI/Fは提供しない）。
        params = extract_flow_defaults(parsed)

        run_id = str(uuid.uuid4())
        now = time.time()
        stored_tags = [routing_tag]
        flow_name = (flow_name or "").strip()
        if not flow_name:
            logger.info(
                "submit yaml failed: missing flow_name",
                extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "tag": routing_tag},
            )
            raise HTTPException(status_code=422, detail="missing flow_name")

        try:
            await kv.put(
                run_id,
                json.dumps(
                    {
                        "run_id": run_id,
                        "flow_name": flow_name,
                        "tag": routing_tag,
                        "tags": stored_tags,
                        "tenant_id": (auth.tenant_id if auth else None),
                        "api_key_id": (auth.api_key_id if auth else None),
                        "workflow_yaml_sha256": parsed.sha256,
                        "workflow_yaml_bytes": parsed.size_bytes,
                        "status": "PENDING",
                        "params": params,
                        "tasks": {},
                        "task_records": {},
                        "start_time": None,
                        "end_time": None,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "error": None,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )

            await js.publish(
                subject=f"{cfg.work_subject_prefix}.{routing_tag}",
                payload=json.dumps(
                    {
                        "run_id": run_id,
                        "flow_name": flow_name,
                        "tag": routing_tag,
                        "tags": stored_tags,
                        "tenant_id": (auth.tenant_id if auth else None),
                        "api_key_id": (auth.api_key_id if auth else None),
                        "params": params,
                        "workflow_yaml": raw.decode("utf-8"),
                        "workflow_yaml_sha256": parsed.sha256,
                        "workflow_yaml_bytes": parsed.size_bytes,
                        "submitted_at": now,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                stream=cfg.work_stream,
            )
        except NatsError as exc:
            logger.exception(
                "submit yaml failed: nats unavailable",
                extra={
                    "err_id": "ERR-PYOCO-0003",
                    "msg_id": "MSG-PYOCO-0003",
                    "flow_name": flow_name,
                    "tag": routing_tag,
                    "run_id": run_id,
                },
            )
            try:
                await kv.delete(run_id)
            except Exception:
                pass
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        return RunSubmitResponse(run_id=run_id, status="PENDING")

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str, request: Request, include: list[str] = Query(default=[])) -> Dict[str, Any]:
        runs_kv = app.state.runs_kv
        workers_kv = app.state.workers_kv
        auth = await _require_auth(request)

        try:
            entry = await runs_kv.get(run_id)
        except KeyNotFoundError:
            logger.info(
                "run not found",
                extra={"err_id": "ERR-PYOCO-0005", "msg_id": "MSG-PYOCO-0005", "run_id": run_id},
            )
            raise HTTPException(status_code=404, detail="run not found")
        except NatsError as exc:
            logger.exception(
                "get_run failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "run_id": run_id},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        snap = json.loads(entry.value.decode("utf-8"))
        if auth is not None:
            # Hide cross-tenant existence by returning 404.
            if snap.get("tenant_id") != auth.tenant_id:
                raise HTTPException(status_code=404, detail="run not found")

        # Enrich with worker liveness if we can.
        worker_id = snap.get("worker_id")
        if worker_id:
            try:
                w = await workers_kv.get(worker_id)
                winfo = json.loads(w.value.decode("utf-8"))
                snap["worker_alive"] = True
                snap["worker_heartbeat_at"] = winfo.get("heartbeat_at")
                if "tags" in winfo:
                    snap["worker_tags"] = winfo.get("tags")
            except KeyNotFoundError:
                snap["worker_alive"] = False
                snap["worker_heartbeat_at"] = None
            except NatsError:
                # If NATS is unavailable, keep the run snapshot but omit liveness enrichment.
                pass

        return _filter_snapshot_for_http(snap, include=set(include or []), mode="run")

    @app.get("/runs/{run_id}/tasks")
    async def get_run_tasks(run_id: str, request: Request) -> Dict[str, Any]:
        runs_kv = app.state.runs_kv
        auth = await _require_auth(request)
        try:
            entry = await runs_kv.get(run_id)
        except KeyNotFoundError:
            logger.info(
                "run not found (tasks)",
                extra={"err_id": "ERR-PYOCO-0005", "msg_id": "MSG-PYOCO-0005", "run_id": run_id},
            )
            raise HTTPException(status_code=404, detail="run not found")
        except NatsError as exc:
            logger.exception(
                "get_tasks failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "run_id": run_id},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        snap = json.loads(entry.value.decode("utf-8"))
        if auth is not None:
            if snap.get("tenant_id") != auth.tenant_id:
                raise HTTPException(status_code=404, detail="run not found")
        return {
            "run_id": snap.get("run_id"),
            "flow_name": snap.get("flow_name"),
            "status": snap.get("status"),
            "tasks": snap.get("tasks") or {},
            "task_records": snap.get("task_records") or {},
            "task_records_truncated": bool(snap.get("task_records_truncated") or False),
        }

    @app.get("/runs")
    async def list_runs(
        request: Request,
        status: Optional[str] = None,
        flow: Optional[str] = None,
        tag: Optional[str] = None,
        include: list[str] = Query(default=[]),
        limit: Optional[int] = Query(default=50, ge=1, le=200),
    ) -> list[Dict[str, Any]]:
        kv = app.state.runs_kv
        auth = await _require_auth(request)
        try:
            keys = await kv.keys()
        except NatsError as exc:
            logger.exception(
                "list_runs failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003"},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        except Exception:
            keys = []

        if not keys:
            return []

        # Newest-first isn't guaranteed in KV; we do best-effort by sorting on updated_at.
        snaps: list[Dict[str, Any]] = []
        for key in keys:
            try:
                entry = await kv.get(key)
            except KeyNotFoundError:
                continue
            snap = json.loads(entry.value.decode("utf-8"))
            if auth is not None and snap.get("tenant_id") != auth.tenant_id:
                continue
            if status and snap.get("status") != status:
                continue
            if flow and snap.get("flow_name") != flow:
                continue
            if tag and snap.get("tag") != tag:
                continue
            snaps.append(_filter_snapshot_for_http(snap, include=set(include or []), mode="list"))

        snaps.sort(key=lambda s: float(s.get("updated_at") or 0.0), reverse=True)
        return snaps[: int(limit)]

    return app
