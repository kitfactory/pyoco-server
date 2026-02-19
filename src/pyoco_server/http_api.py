from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import locale
import logging
import os
from pathlib import Path
import re
import time
import uuid
from typing import Any, Dict, Optional

import nats
from fastapi import Response
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import File, Form, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from nats.js import api
from pydantic import BaseModel, Field
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import Version
from nats.js.errors import KeyNotFoundError, NotFoundError, ObjectNotFoundError
from nats.errors import Error as NatsError

from .auth import ApiKeyError, ApiKeyRecord, make_kv_key_for_api_key_id, parse_api_key, verify_api_key
from .config import NatsBackendConfig
from .logging_config import configure_logging
from .models import (
    WORKER_ACTIVE_STATES,
    WORKER_STATES,
    derive_worker_effective_state,
    normalize_worker_registry_record,
)
from .resources import ensure_resources
from .workflow_yaml import WorkflowYamlValidationError, extract_flow_defaults, parse_workflow_yaml_bytes

_TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
_WHEEL_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+\.whl$")
_WHEEL_TAG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_WHEEL_TAGS_HEADER = "x-pyoco-wheel-tags"


def config_from_env() -> NatsBackendConfig:
    return NatsBackendConfig.from_env()


def _snapshot_sort_key(snap: Dict[str, Any]) -> tuple[float, str]:
    return (float(snap.get("updated_at") or 0.0), str(snap.get("run_id") or ""))


def _encode_runs_cursor(updated_at: float, run_id: str) -> str:
    raw = json.dumps(
        {"u": float(updated_at), "r": str(run_id)},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_runs_cursor(token: str) -> tuple[float, str]:
    try:
        padded = token + ("=" * ((4 - (len(token) % 4)) % 4))
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        obj = json.loads(raw.decode("utf-8"))
        return (float(obj["u"]), str(obj["r"]))
    except Exception as exc:
        raise ValueError("invalid_cursor") from exc


def _sse_pack(event: str, data: Dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _normalize_worker_for_http(
    raw: Dict[str, Any],
    *,
    worker_id: str,
    disconnect_timeout_sec: float,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    rec = normalize_worker_registry_record(raw, worker_id=worker_id)
    rec["state"] = derive_worker_effective_state(
        rec,
        now=(time.time() if now is None else now),
        disconnect_timeout_sec=disconnect_timeout_sec,
    )
    rec["heartbeat_at"] = rec.get("last_heartbeat_at")
    return rec


def _normalize_dashboard_lang(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("ja"):
        return "ja"
    if raw.startswith("en"):
        return "en"
    if raw in {"auto", "server", "system", "default"}:
        return None
    return None


def _normalize_wheel_name(raw: str) -> str:
    name = str(raw or "").strip()
    if not _WHEEL_NAME_RE.fullmatch(name):
        raise ValueError("invalid wheel name")
    return name


def _parse_wheel_identity(wheel_name: str) -> tuple[str, Version]:
    try:
        dist_name, version, _, _ = parse_wheel_filename(wheel_name)
    except InvalidWheelFilename as exc:
        raise ValueError("invalid wheel filename") from exc
    return str(dist_name), version


def _parse_wheel_tags_csv(raw: Optional[str]) -> list[str]:
    if raw is None:
        return []
    parts = [str(p).strip() for p in str(raw).split(",") if str(p).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for tag in parts:
        if not _WHEEL_TAG_RE.fullmatch(tag):
            raise ValueError("invalid wheel tags")
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _read_wheel_tags_from_headers(headers: Any) -> list[str]:
    if not isinstance(headers, dict):
        return []
    raw = headers.get(_WHEEL_TAGS_HEADER)
    if raw is None:
        raw = headers.get(_WHEEL_TAGS_HEADER.title())
    if raw is None:
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return _parse_wheel_tags_csv(str(raw))
    except ValueError:
        return []


def _read_wheel_sha256_from_headers(headers: Any) -> Optional[str]:
    if not isinstance(headers, dict):
        return None
    raw = headers.get("sha256")
    if raw is None:
        raw = headers.get("Sha256")
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    value = str(raw).strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    return None


def _wheel_info_to_http(info: Any) -> Dict[str, Any]:
    digest = str(getattr(info, "digest", "") or "")
    return {
        "name": str(getattr(info, "name", "")),
        "size_bytes": int(getattr(info, "size", 0) or 0),
        "digest": digest,
        "sha256_b64": (digest.split("=", 1)[1] if digest.startswith("SHA-256=") else None),
        "mtime": str(getattr(info, "mtime", "") or ""),
        "nuid": str(getattr(info, "nuid", "") or ""),
        "tags": _read_wheel_tags_from_headers(getattr(info, "headers", None)),
    }


def _detect_server_locale_lang() -> str:
    candidates = [
        os.environ.get("LC_ALL"),
        os.environ.get("LANGUAGE"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
    ]
    try:
        loc = locale.getlocale()
        if loc and loc[0]:
            candidates.append(loc[0])
    except Exception:
        pass
    for raw in candidates:
        normalized = _normalize_dashboard_lang(raw)
        if normalized:
            return normalized
    return "en"


def _resolve_dashboard_lang(config: NatsBackendConfig) -> str:
    explicit = _normalize_dashboard_lang(config.dashboard_lang)
    if explicit:
        return explicit
    return _detect_server_locale_lang()


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


class WorkerPatchRequest(BaseModel):
    hidden: bool


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
    app = FastAPI(title="pyoco-server (HTTP gateway)", version="0.5.0")
    logger = logging.getLogger("pyoco_server.http_api")
    static_dir = Path(__file__).resolve().parent / "static"
    dashboard_lang = _resolve_dashboard_lang(config)
    index_template_text: Optional[str] = None

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        index_path = static_dir / "index.html"
        if index_path.exists():
            index_template_text = index_path.read_text(encoding="utf-8")

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

    def _extract_request_source(request: Request) -> Dict[str, Any]:
        client_host = None
        if getattr(request, "client", None) is not None:
            client_host = getattr(request.client, "host", None)
        return {
            "remote_addr": str(client_host) if client_host else None,
            "x_forwarded_for": (request.headers.get("x-forwarded-for") or None),
            "x_real_ip": (request.headers.get("x-real-ip") or None),
            "user_agent": (request.headers.get("user-agent") or None),
            "host": (request.headers.get("host") or None),
            "scheme": str(getattr(request.url, "scheme", "") or "") or None,
        }

    async def _append_wheel_history(
        request: Request,
        *,
        action: str,
        wheel_name: str,
        auth: Optional[_AuthContext],
        tags: Optional[list[str]] = None,
        size_bytes: Optional[int] = None,
        sha256_hex: Optional[str] = None,
        replace: Optional[bool] = None,
    ) -> None:
        history_kv = app.state.wheel_history_kv
        now = time.time()
        event_id = uuid.uuid4().hex
        key = f"{int(now * 1000):013d}_{event_id}"
        evt = {
            "event_id": event_id,
            "occurred_at": now,
            "action": str(action).strip().lower(),
            "wheel_name": str(wheel_name),
            "tags": list(tags or []),
            "size_bytes": (int(size_bytes) if size_bytes is not None else None),
            "sha256_hex": (str(sha256_hex).lower() if sha256_hex else None),
            "replace": (bool(replace) if replace is not None else None),
            "actor": {
                "tenant_id": (auth.tenant_id if auth is not None else None),
                "api_key_id": (auth.api_key_id if auth is not None else None),
            },
            "source": _extract_request_source(request),
        }
        await history_kv.put(
            key,
            json.dumps(evt, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        )

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
        app.state.wheel_store = await js.object_store(config.wheel_object_store_bucket)
        app.state.wheel_history_kv = await js.key_value(config.wheel_history_kv_bucket)
        app.state.config = config
        app.state.dashboard_lang = dashboard_lang

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        nc = getattr(app.state, "nc", None)
        if nc is not None:
            await nc.close()

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def dashboard_index() -> HTMLResponse:
        if not static_dir.exists() or not index_template_text:
            raise HTTPException(status_code=404, detail="dashboard not found")
        lang = str(getattr(app.state, "dashboard_lang", dashboard_lang) or "en")
        body = index_template_text.replace("__PYOCO_DASHBOARD_LANG_VALUE__", lang)
        return HTMLResponse(content=body)

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
        today_status_counts: dict[str, int] = {}
        today_local = datetime.now().astimezone().date()
        for key in list(run_keys or []):
            try:
                entry = await runs_kv.get(key)
            except KeyNotFoundError:
                continue
            snap = json.loads(entry.value.decode("utf-8"))
            st = str(snap.get("status") or "UNKNOWN")
            status_counts[st] = status_counts.get(st, 0) + 1
            try:
                updated_at = float(snap.get("updated_at") or 0.0)
            except Exception:
                updated_at = 0.0
            if updated_at > 0:
                try:
                    if datetime.fromtimestamp(updated_at).astimezone().date() == today_local:
                        today_status_counts[st] = today_status_counts.get(st, 0) + 1
                except Exception:
                    pass

        # Count active workers by registry state (best-effort).
        try:
            worker_keys = await workers_kv.keys()
        except Exception:
            worker_keys = []
        now = time.time()
        workers_alive = 0
        for key in list(worker_keys or []):
            try:
                entry = await workers_kv.get(key)
            except KeyNotFoundError:
                continue
            except Exception:
                continue
            try:
                raw = json.loads(entry.value.decode("utf-8"))
            except Exception:
                continue
            rec = _normalize_worker_for_http(
                raw,
                worker_id=key,
                disconnect_timeout_sec=float(app.state.config.worker_disconnect_timeout_sec),
                now=now,
            )
            if str(rec.get("state") or "").upper() in WORKER_ACTIVE_STATES:
                workers_alive += 1

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

        lines.append("# HELP pyoco_runs_today_total Count of runs updated today by status (best-effort from KV).")
        lines.append("# TYPE pyoco_runs_today_total gauge")
        for st, n in sorted(today_status_counts.items()):
            lines.append(f'pyoco_runs_today_total{{status="{st}"}} {int(n)}')

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
    async def list_workers(
        scope: str = Query(default="active"),
        state: Optional[str] = Query(default=None),
        include_hidden: bool = Query(default=False),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[Dict[str, Any]]:
        scope_norm = str(scope or "active").strip().lower()
        if scope_norm not in {"active", "all"}:
            logger.info(
                "workers failed: invalid scope",
                extra={"err_id": "ERR-PYOCO-0019", "msg_id": "MSG-PYOCO-0019", "scope": scope},
            )
            raise HTTPException(status_code=422, detail="invalid workers request")

        state_norm = None
        if state is not None and str(state).strip() != "":
            state_norm = str(state).strip().upper()
            if state_norm not in WORKER_STATES:
                logger.info(
                    "workers failed: invalid state filter",
                    extra={"err_id": "ERR-PYOCO-0019", "msg_id": "MSG-PYOCO-0019", "state": state},
                )
                raise HTTPException(status_code=422, detail="invalid workers request")

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

        now = time.time()
        disconnect_timeout = float(app.state.config.worker_disconnect_timeout_sec)
        out: list[Dict[str, Any]] = []
        for key in list(keys or []):
            try:
                entry = await workers_kv.get(key)
            except KeyNotFoundError:
                continue
            try:
                raw = json.loads(entry.value.decode("utf-8"))
            except Exception:
                continue

            rec = _normalize_worker_for_http(
                raw,
                worker_id=key,
                disconnect_timeout_sec=disconnect_timeout,
                now=now,
            )
            worker_state = str(rec.get("state") or "").upper()
            if not include_hidden and bool(rec.get("hidden") or False):
                continue
            if scope_norm == "active" and worker_state not in WORKER_ACTIVE_STATES:
                continue
            if state_norm is not None and worker_state != state_norm:
                continue
            out.append(rec)

        out.sort(key=lambda w: float(w.get("last_seen_at") or 0.0), reverse=True)
        return out[: int(limit)]

    @app.patch("/workers/{worker_id}")
    async def patch_worker(worker_id: str, req: WorkerPatchRequest) -> Dict[str, Any]:
        workers_kv = app.state.workers_kv
        try:
            entry = await workers_kv.get(worker_id)
        except KeyNotFoundError:
            logger.info(
                "worker not found",
                extra={"err_id": "ERR-PYOCO-0020", "msg_id": "MSG-PYOCO-0020", "worker_id": worker_id},
            )
            raise HTTPException(status_code=404, detail="worker not found")
        except NatsError as exc:
            logger.exception(
                "patch worker failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "worker_id": worker_id},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        try:
            raw = json.loads(entry.value.decode("utf-8"))
        except Exception:
            raw = {"worker_id": worker_id}

        rec = normalize_worker_registry_record(raw, worker_id=worker_id)
        rec["heartbeat_at"] = rec.get("last_heartbeat_at")
        now = time.time()
        rec["hidden"] = bool(req.hidden)
        rec["updated_at"] = now
        try:
            await workers_kv.put(
                worker_id,
                json.dumps(rec, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
            )
        except NatsError as exc:
            logger.exception(
                "patch worker failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "worker_id": worker_id},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        return {"worker_id": worker_id, "hidden": bool(req.hidden), "updated_at": now}

    @app.get("/wheels")
    async def list_wheels(request: Request) -> list[Dict[str, Any]]:
        await _require_auth(request)
        store = app.state.wheel_store
        try:
            infos = await store.list(ignore_deletes=True)
        except (ObjectNotFoundError, NotFoundError):
            return []
        except NatsError as exc:
            logger.exception(
                "list wheels failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003"},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        except Exception:
            infos = []

        items: list[Dict[str, Any]] = []
        for info in list(infos or []):
            name = str(getattr(info, "name", "") or "")
            if not _WHEEL_NAME_RE.fullmatch(name):
                continue
            items.append(_wheel_info_to_http(info))
        items.sort(key=lambda x: str(x.get("name") or ""))
        return items

    @app.post("/wheels")
    async def upload_wheel(
        request: Request,
        wheel: UploadFile = File(...),
        replace: bool = Form(default=True),
        tags: Optional[str] = Form(default=None),
    ) -> Dict[str, Any]:
        auth = await _require_auth(request)
        cfg: NatsBackendConfig = app.state.config
        store = app.state.wheel_store

        try:
            wheel_name = _normalize_wheel_name(wheel.filename or "")
        except ValueError:
            logger.info(
                "upload wheel failed: invalid wheel name",
                extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "wheel_name": wheel.filename},
            )
            raise HTTPException(status_code=422, detail="invalid wheel name")
        try:
            wheel_package, wheel_version = _parse_wheel_identity(wheel_name)
        except ValueError:
            logger.info(
                "upload wheel failed: invalid wheel filename",
                extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "wheel_name": wheel_name},
            )
            raise HTTPException(status_code=422, detail="invalid wheel filename")

        try:
            wheel_tags = _parse_wheel_tags_csv(tags)
        except ValueError:
            logger.info(
                "upload wheel failed: invalid wheel tags",
                extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "tags": tags},
            )
            raise HTTPException(status_code=422, detail="invalid wheel tags")

        raw = await wheel.read()
        max_bytes = int(getattr(cfg, "wheel_max_bytes", 0) or 0)
        if max_bytes > 0 and len(raw) > max_bytes:
            logger.info(
                "upload wheel failed: wheel too large",
                extra={
                    "err_id": "ERR-PYOCO-0002",
                    "msg_id": "MSG-PYOCO-0002",
                    "wheel_name": wheel_name,
                    "size_bytes": len(raw),
                    "max_bytes": max_bytes,
                },
            )
            raise HTTPException(status_code=413, detail="wheel too large")

        try:
            infos = await store.list(ignore_deletes=True)
        except (ObjectNotFoundError, NotFoundError):
            infos = []
        except NatsError as exc:
            logger.exception(
                "upload wheel failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "wheel_name": wheel_name},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        except Exception:
            infos = []

        newest_existing_version: Optional[Version] = None
        for info in list(infos or []):
            existing_name = str(getattr(info, "name", "") or "")
            if not _WHEEL_NAME_RE.fullmatch(existing_name):
                continue
            try:
                existing_package, existing_version = _parse_wheel_identity(existing_name)
            except ValueError:
                continue
            if existing_package != wheel_package:
                continue
            if newest_existing_version is None or existing_version > newest_existing_version:
                newest_existing_version = existing_version
            if existing_version == wheel_version:
                raise HTTPException(status_code=409, detail="wheel version already exists; bump version")

        if newest_existing_version is not None and wheel_version < newest_existing_version:
            raise HTTPException(status_code=409, detail="wheel version must be greater than existing latest version")

        if not bool(replace):
            try:
                await store.get_info(wheel_name)
                raise HTTPException(status_code=409, detail="wheel already exists")
            except (ObjectNotFoundError, NotFoundError):
                pass

        sha256_hex = hashlib.sha256(raw).hexdigest()
        meta_headers = {
            "content-type": str(wheel.content_type or "application/octet-stream"),
            "sha256": sha256_hex,
        }
        if wheel_tags:
            meta_headers[_WHEEL_TAGS_HEADER] = ",".join(wheel_tags)
        try:
            info = await store.put(
                wheel_name,
                raw,
                meta=api.ObjectMeta(
                    name=wheel_name,
                    headers=meta_headers,
                ),
            )
        except NatsError as exc:
            logger.exception(
                "upload wheel failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "wheel_name": wheel_name},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        out = _wheel_info_to_http(info)
        out["sha256_hex"] = sha256_hex
        out["tags"] = list(wheel_tags)
        try:
            await _append_wheel_history(
                request,
                action="upload",
                wheel_name=wheel_name,
                auth=auth,
                tags=wheel_tags,
                size_bytes=len(raw),
                sha256_hex=sha256_hex,
                replace=bool(replace),
            )
        except Exception:
            logger.exception("append wheel history failed", extra={"wheel_name": wheel_name, "action": "upload"})
        return out

    @app.get("/wheels/history")
    async def list_wheel_history(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        wheel_name: Optional[str] = Query(default=None),
        action: Optional[str] = Query(default=None),
    ) -> list[Dict[str, Any]]:
        await _require_auth(request)
        history_kv = app.state.wheel_history_kv

        wheel_name_norm: Optional[str] = None
        if wheel_name is not None and str(wheel_name).strip() != "":
            try:
                wheel_name_norm = _normalize_wheel_name(wheel_name)
            except ValueError:
                logger.info(
                    "wheel history failed: invalid wheel name filter",
                    extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "wheel_name": wheel_name},
                )
                raise HTTPException(status_code=422, detail="invalid wheel name")

        action_norm: Optional[str] = None
        if action is not None and str(action).strip() != "":
            action_norm = str(action).strip().lower()
            if action_norm not in {"upload", "delete"}:
                logger.info(
                    "wheel history failed: invalid action filter",
                    extra={"err_id": "ERR-PYOCO-0002", "msg_id": "MSG-PYOCO-0002", "action": action},
                )
                raise HTTPException(status_code=422, detail="invalid action")

        try:
            keys = await history_kv.keys()
        except NatsError as exc:
            logger.exception(
                "wheel history failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003"},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        except Exception:
            keys = []

        out: list[Dict[str, Any]] = []
        for key in list(keys or []):
            try:
                entry = await history_kv.get(key)
            except KeyNotFoundError:
                continue
            except Exception:
                continue
            try:
                item = json.loads(entry.value.decode("utf-8"))
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if wheel_name_norm is not None and str(item.get("wheel_name") or "") != wheel_name_norm:
                continue
            action_value = str(item.get("action") or "").lower()
            if action_norm is not None and action_value != action_norm:
                continue
            out.append(item)

        out.sort(
            key=lambda x: (
                float(x.get("occurred_at") or 0.0),
                str(x.get("event_id") or ""),
            ),
            reverse=True,
        )
        return out[: int(limit)]

    @app.get("/wheels/{wheel_name}")
    async def download_wheel(wheel_name: str, request: Request) -> Response:
        await _require_auth(request)
        try:
            wheel_name = _normalize_wheel_name(wheel_name)
        except ValueError:
            raise HTTPException(status_code=404, detail="wheel not found")

        store = app.state.wheel_store
        try:
            result = await store.get(wheel_name)
        except ObjectNotFoundError:
            raise HTTPException(status_code=404, detail="wheel not found")
        except NatsError as exc:
            logger.exception(
                "download wheel failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "wheel_name": wheel_name},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        data = (result.data or b"") if result is not None else b""
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{wheel_name}"'},
        )

    @app.delete("/wheels/{wheel_name}")
    async def delete_wheel(wheel_name: str, request: Request) -> Dict[str, Any]:
        auth = await _require_auth(request)
        try:
            wheel_name = _normalize_wheel_name(wheel_name)
        except ValueError:
            raise HTTPException(status_code=404, detail="wheel not found")

        store = app.state.wheel_store
        try:
            info = await store.get_info(wheel_name)
        except (ObjectNotFoundError, NotFoundError):
            raise HTTPException(status_code=404, detail="wheel not found")
        except NatsError as exc:
            logger.exception(
                "delete wheel failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "wheel_name": wheel_name},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        try:
            await store.delete(wheel_name)
        except NatsError as exc:
            logger.exception(
                "delete wheel failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "wheel_name": wheel_name},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")
        try:
            await _append_wheel_history(
                request,
                action="delete",
                wheel_name=wheel_name,
                auth=auth,
                tags=_read_wheel_tags_from_headers(getattr(info, "headers", None)),
                size_bytes=int(getattr(info, "size", 0) or 0),
                sha256_hex=_read_wheel_sha256_from_headers(getattr(info, "headers", None)),
                replace=None,
            )
        except Exception:
            logger.exception("append wheel history failed", extra={"wheel_name": wheel_name, "action": "delete"})
        return {"name": wheel_name, "deleted": True}

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
                raw = json.loads(w.value.decode("utf-8"))
                winfo = _normalize_worker_for_http(
                    raw,
                    worker_id=str(worker_id),
                    disconnect_timeout_sec=float(app.state.config.worker_disconnect_timeout_sec),
                )
                state = str(winfo.get("state") or "").upper()
                snap["worker_alive"] = state in WORKER_ACTIVE_STATES
                snap["worker_state"] = state
                snap["worker_heartbeat_at"] = winfo.get("last_heartbeat_at")
                snap["worker_hidden"] = bool(winfo.get("hidden") or False)
                if "tags" in winfo:
                    snap["worker_tags"] = winfo.get("tags")
            except KeyNotFoundError:
                snap["worker_alive"] = False
                snap["worker_state"] = "DISCONNECTED"
                snap["worker_heartbeat_at"] = None
            except NatsError:
                # If NATS is unavailable, keep the run snapshot but omit liveness enrichment.
                pass

        return _filter_snapshot_for_http(snap, include=set(include or []), mode="run")

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request) -> Dict[str, Any]:
        runs_kv = app.state.runs_kv
        auth = await _require_auth(request)

        try:
            entry = await runs_kv.get(run_id)
        except KeyNotFoundError:
            logger.info(
                "run not found (cancel)",
                extra={"err_id": "ERR-PYOCO-0005", "msg_id": "MSG-PYOCO-0005", "run_id": run_id},
            )
            raise HTTPException(status_code=404, detail="run not found")
        except NatsError as exc:
            logger.exception(
                "cancel failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "run_id": run_id},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        snap = json.loads(entry.value.decode("utf-8"))
        if auth is not None and snap.get("tenant_id") != auth.tenant_id:
            raise HTTPException(status_code=404, detail="run not found")

        status = str(snap.get("status") or "").upper()
        if status not in _TERMINAL_RUN_STATUSES:
            now = time.time()
            snap["status"] = "CANCELLING"
            snap["cancel_requested_at"] = float(snap.get("cancel_requested_at") or now)
            if auth is not None:
                snap["cancel_requested_by"] = f"api_key:{auth.api_key_id}"
            snap["updated_at"] = now
            try:
                await runs_kv.put(
                    run_id,
                    json.dumps(snap, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
                )
            except NatsError as exc:
                logger.exception(
                    "cancel failed: nats unavailable",
                    extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "run_id": run_id},
                )
                raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        return _filter_snapshot_for_http(snap, include=set(), mode="run")

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

    @app.get("/runs/{run_id}/watch")
    async def watch_run(
        run_id: str,
        request: Request,
        include: list[str] = Query(default=[]),
        since: Optional[float] = None,
        timeout_sec: int = Query(default=60, ge=1, le=600),
    ) -> StreamingResponse:
        runs_kv = app.state.runs_kv
        auth = await _require_auth(request)

        try:
            entry = await runs_kv.get(run_id)
        except KeyNotFoundError:
            logger.info(
                "run not found (watch)",
                extra={"err_id": "ERR-PYOCO-0005", "msg_id": "MSG-PYOCO-0005", "run_id": run_id},
            )
            raise HTTPException(status_code=404, detail="run not found")
        except NatsError as exc:
            logger.exception(
                "watch failed: nats unavailable",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "run_id": run_id},
            )
            raise HTTPException(status_code=503, detail=f"nats unavailable: {exc.__class__.__name__}")

        first = json.loads(entry.value.decode("utf-8"))
        if auth is not None and first.get("tenant_id") != auth.tenant_id:
            raise HTTPException(status_code=404, detail="run not found")

        include_set = set(include or [])
        first_filtered = _filter_snapshot_for_http(dict(first), include=include_set, mode="run")
        first_updated_at = float(first_filtered.get("updated_at") or 0.0)
        first_payload = json.dumps(first_filtered, ensure_ascii=True, separators=(",", ":"))
        first_revision = getattr(entry, "revision", None)

        async def _stream():
            last_payload = first_payload
            last_revision = first_revision
            last_heartbeat = time.time()
            heartbeat_interval = 5.0
            deadline = time.time() + float(timeout_sec)

            try:
                if since is None or first_updated_at >= float(since):
                    yield _sse_pack(
                        "snapshot",
                        {"run_id": run_id, "snapshot": first_filtered, "ts": time.time()},
                    )

                while time.time() < deadline:
                    if await request.is_disconnected():
                        return

                    await asyncio.sleep(0.5)
                    now = time.time()

                    try:
                        latest_entry = await runs_kv.get(run_id)
                    except KeyNotFoundError:
                        return
                    except NatsError:
                        return

                    latest = json.loads(latest_entry.value.decode("utf-8"))
                    if auth is not None and latest.get("tenant_id") != auth.tenant_id:
                        return

                    latest_filtered = _filter_snapshot_for_http(dict(latest), include=include_set, mode="run")
                    latest_payload = json.dumps(latest_filtered, ensure_ascii=True, separators=(",", ":"))
                    latest_revision = getattr(latest_entry, "revision", None)

                    changed = latest_payload != last_payload
                    if latest_revision is not None and last_revision is not None:
                        changed = int(latest_revision) != int(last_revision)

                    if changed:
                        updated_at = float(latest_filtered.get("updated_at") or 0.0)
                        if since is None or updated_at >= float(since):
                            yield _sse_pack(
                                "snapshot",
                                {"run_id": run_id, "snapshot": latest_filtered, "ts": now},
                            )
                        last_payload = latest_payload
                        last_revision = latest_revision
                        last_heartbeat = now
                        continue

                    if now - last_heartbeat >= heartbeat_interval:
                        yield _sse_pack("heartbeat", {"run_id": run_id, "ts": now})
                        last_heartbeat = now
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/runs")
    async def list_runs(
        request: Request,
        status: Optional[str] = None,
        flow: Optional[str] = None,
        tag: Optional[str] = None,
        updated_after: Optional[float] = None,
        cursor: Optional[str] = None,
        workflow_yaml_sha256: Optional[str] = None,
        include: list[str] = Query(default=[]),
        limit: Optional[int] = Query(default=50, ge=1, le=200),
    ) -> Any:
        kv = app.state.runs_kv
        auth = await _require_auth(request)
        any_vnext = (updated_after is not None) or (cursor is not None) or bool(workflow_yaml_sha256)

        cursor_key: Optional[tuple[float, str]] = None
        if cursor:
            try:
                cursor_key = _decode_runs_cursor(cursor)
            except ValueError:
                logger.info(
                    "list_runs failed: invalid cursor",
                    extra={"err_id": "ERR-PYOCO-0017", "msg_id": "MSG-PYOCO-0017"},
                )
                raise HTTPException(status_code=422, detail="invalid list query")

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
            if any_vnext:
                return {"items": [], "next_cursor": None}
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
            if workflow_yaml_sha256 and snap.get("workflow_yaml_sha256") != workflow_yaml_sha256:
                continue
            snaps.append(_filter_snapshot_for_http(snap, include=set(include or []), mode="list"))

        snaps.sort(key=_snapshot_sort_key, reverse=True)

        if updated_after is not None:
            snaps = [s for s in snaps if float(s.get("updated_at") or 0.0) > float(updated_after)]

        if cursor_key is not None:
            snaps = [s for s in snaps if _snapshot_sort_key(s) < cursor_key]

        page_size = int(limit)
        page = snaps[:page_size]
        if not any_vnext:
            return page

        next_cursor = None
        if len(snaps) > page_size and page:
            cursor_updated_at, cursor_run_id = _snapshot_sort_key(page[-1])
            next_cursor = _encode_runs_cursor(cursor_updated_at, cursor_run_id)
        return {"items": page, "next_cursor": next_cursor}

    return app
