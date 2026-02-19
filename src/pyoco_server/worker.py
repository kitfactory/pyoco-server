from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Optional
import uuid

import nats
import logging
from nats.errors import TimeoutError as NatsTimeoutError
from nats.errors import Error as NatsError
from nats.js import api
from nats.js.errors import BadRequestError
from packaging.tags import sys_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import Version

from pyoco.core.engine import Engine
from pyoco.core.models import Flow, RunContext, RunStatus

from .config import NatsBackendConfig
from .dlq import publish_dlq
from .models import (
    RunJob,
    WORKER_STATE_IDLE,
    WORKER_STATE_RUNNING,
    WORKER_STATE_STOPPED_GRACEFUL,
    compact_run_snapshot,
    normalize_worker_registry_record,
    run_snapshot_from_context,
)
from .resources import ensure_resources
from .trace import NatsKvTraceBackend
from .workflow_yaml import parse_workflow_yaml_bytes

_WHEEL_FILENAME_RE = re.compile(r"^[A-Za-z0-9._+-]+\.whl$")
_WHEEL_TAG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_WHEEL_TAGS_HEADER = "x-pyoco-wheel-tags"
_WHEEL_SYNC_STATUS_MAX_ITEMS = 50


class PyocoNatsWorker:
    _UNSET = object()

    def __init__(
        self,
        nc,
        *,
        config: NatsBackendConfig = NatsBackendConfig(),
        flow_resolver: Callable[[str], Flow],
        worker_id: str = "worker",
        tags: Optional[list[str]] = None,
    ):
        self._nc = nc
        self._config = config
        self._js = nc.jetstream()
        self._kv = None
        self._workers_kv = None
        self._wheel_store = None
        self._subs = {}
        self._flow_resolver = flow_resolver
        self._worker_id = worker_id
        self._instance_id = uuid.uuid4().hex
        self._registry_lock = asyncio.Lock()
        self._wheel_sync_lock = asyncio.Lock()
        self._registry_task: Optional[asyncio.Task] = None
        self._closed = False
        self._next_wheel_sync_at = 0.0
        self._wheel_sync_dir: Optional[Path] = None
        self._wheel_manifest_path: Optional[Path] = None
        self._supported_wheel_tags = frozenset(sys_tags())
        self._registry: dict[str, Any] = {
            "worker_id": self._worker_id,
            "instance_id": self._instance_id,
            "state": WORKER_STATE_IDLE,
            "hidden": False,
            "tags": [],
            "last_seen_at": 0.0,
            "last_heartbeat_at": 0.0,
            "heartbeat_at": 0.0,
            "current_run_id": None,
            "last_run_id": None,
            "last_run_status": None,
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "stopped_at": None,
            "stop_reason": None,
            "updated_at": 0.0,
            "wheel_sync": _build_initial_wheel_sync_state(enabled=self._wheel_sync_enabled()),
        }
        self._tags = [t.strip() for t in (tags or [config.default_tag]) if t and t.strip()]
        if not self._tags:
            self._tags = [config.default_tag]
        for t in self._tags:
            if "." in t:
                raise ValueError("tag must not contain '.'")

    @classmethod
    async def connect(
        cls,
        *,
        config: NatsBackendConfig = NatsBackendConfig(),
        flow_resolver: Callable[[str], Flow],
        worker_id: str = "worker",
        tags: Optional[list[str]] = None,
    ):
        nc = await nats.connect(config.nats_url, name=f"pyoco-nats-worker:{worker_id}")
        self = cls(nc, config=config, flow_resolver=flow_resolver, worker_id=worker_id, tags=tags)
        await self._init()
        return self

    async def _init(self) -> None:
        await ensure_resources(self._js, self._config)
        self._kv = await self._js.key_value(self._config.runs_kv_bucket)
        self._workers_kv = await self._js.key_value(self._config.workers_kv_bucket)
        self._wheel_store = await self._js.object_store(self._config.wheel_object_store_bucket)
        # Bind to per-tag durable consumers. Each consumer is shared among all workers
        # that can execute that tag (work-queue semantics).
        for tag in self._tags:
            durable = f"{self._config.consumer_prefix}_{tag}"
            subject = f"{self._config.work_subject_prefix}.{tag}"
            # Ensure consumer exists with our default contract (AckWait/MaxDeliver).
            # If it already exists, keep existing config (it may be environment-tuned).
            try:
                await self._js.add_consumer(
                    self._config.work_stream,
                    api.ConsumerConfig(
                        durable_name=durable,
                        filter_subject=subject,
                        ack_wait=float(self._config.consumer_ack_wait_sec),
                        max_deliver=int(self._config.consumer_max_deliver),
                        max_ack_pending=int(self._config.consumer_max_ack_pending),
                    ),
                )
            except BadRequestError:
                pass
            self._subs[tag] = await self._js.pull_subscribe(
                subject=subject,
                durable=durable,
                stream=self._config.work_stream,
            )

        # 起動直後に worker registry を初期化し、常時heartbeatタスクを開始する。
        # Initialize worker registry at startup and start the always-on heartbeat loop.
        await self._init_worker_registry()
        self._registry_task = asyncio.create_task(self._worker_registry_loop())
        self._init_wheel_sync_state()
        await self._maybe_sync_wheels(force=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._set_worker_registry(
                state=WORKER_STATE_STOPPED_GRACEFUL,
                current_run_id=None,
                stopped_at=time.time(),
                stop_reason="graceful_shutdown",
                touch=True,
            )
        except Exception:
            pass
        if self._registry_task is not None:
            self._registry_task.cancel()
            try:
                await self._registry_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._registry_task = None
        try:
            await self._nc.close()
        except Exception:
            # 接続断時の close 失敗は終了処理では致命にしない（best-effort）。
            # Ignore close-time transport errors on disconnected NATS sessions.
            pass

    async def run_once(self, timeout: float = 1.0) -> Optional[str]:
        """
        Fetch and process a single job. Returns run_id when a job was processed,
        or None when no message was available within timeout.
        """

        if not self._subs:
            return None
        await self._maybe_sync_wheels()

        deadline = time.time() + float(timeout)
        msg = None
        while time.time() < deadline and msg is None:
            remaining = deadline - time.time()
            slice_timeout = min(0.2, max(0.05, remaining))
            for tag, sub in list(self._subs.items()):
                try:
                    msgs = await sub.fetch(1, timeout=slice_timeout)
                except NatsTimeoutError:
                    continue
                if msgs:
                    msg = msgs[0]
                    break

        if msg is None:
            return None

        # Job decode errors are represented as ValueError by _decode_job().
        # Execution errors may also be ValueError, so keep this scope narrow.
        try:
            job = _decode_job(msg.data)
        except ValueError as exc:
            # Invalid job payload/schema: never retry; isolate to DLQ if possible.
            logging.getLogger("pyoco_server.worker").exception(
                "invalid job payload",
                extra={
                    "err_id": "ERR-PYOCO-0012",
                    "msg_id": "MSG-PYOCO-0012",
                    "reason": "invalid_job",
                    "tag": getattr(msg, "subject", "").split(".")[-1] if getattr(msg, "subject", "") else None,
                },
            )
            await self._dlq_invalid_msg(msg, error=str(exc))
            await msg.term()
            return None

        run_id = job.run_id
        progress_task = None
        try:
            progress_task = asyncio.create_task(self._ack_progress_loop(msg))
            await self._execute_job(job)
            await msg.ack()
            return run_id
        except NatsError:
            # Transient NATS errors (KV writes, etc.): request redelivery.
            # Best-effort NAK; if it fails, the message will be redelivered based on server policy.
            logging.getLogger("pyoco_server.worker").exception(
                "transient nats error during job processing",
                extra={"err_id": "ERR-PYOCO-0003", "msg_id": "MSG-PYOCO-0003", "run_id": run_id},
            )
            try:
                await self._set_worker_registry(
                    state=WORKER_STATE_IDLE,
                    current_run_id=None,
                    last_run_id=run_id,
                    last_run_status="FAILED",
                    last_run_finished_at=time.time(),
                    touch=True,
                )
            except Exception:
                pass
            try:
                await msg.nak(delay=2.0)
            except Exception:
                pass
            return run_id
        except Exception as exc:
            # Best-effort: mark failed and ACK to avoid redelivery loops in MVP.
            logging.getLogger("pyoco_server.worker").exception(
                "unexpected error during job processing",
                extra={"err_id": "ERR-PYOCO-0007", "msg_id": "MSG-PYOCO-0007", "run_id": run_id},
            )
            if run_id:
                try:
                    # Non-retryable failures default to terminalization + ACK.
                    run_ctx = RunContext(run_id=run_id, flow_name=getattr(job, "flow_name", "unknown"))
                    run_ctx.status = RunStatus.FAILED
                    await self._kv.put(
                        run_id,
                        json.dumps(
                            run_snapshot_from_context(run_ctx, error=str(exc)),
                            ensure_ascii=True,
                            separators=(",", ":"),
                        ).encode("utf-8"),
                    )
                except Exception:
                    # If we cannot record terminal state, request redelivery.
                    try:
                        await msg.nak(delay=2.0)
                    except Exception:
                        pass
                    return run_id
            try:
                await self._set_worker_registry(
                    state=WORKER_STATE_IDLE,
                    current_run_id=None,
                    last_run_id=run_id,
                    last_run_status="FAILED",
                    last_run_finished_at=time.time(),
                    touch=True,
                )
            except Exception:
                pass
            await msg.ack()
            return run_id
        finally:
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

    async def _init_worker_registry(self) -> None:
        assert self._workers_kv is not None
        now = time.time()
        hidden = False
        wheel_sync = _build_initial_wheel_sync_state(enabled=self._wheel_sync_enabled())
        try:
            entry = await self._workers_kv.get(self._worker_id)
            prev = json.loads(entry.value.decode("utf-8"))
            normalized = normalize_worker_registry_record(prev, worker_id=self._worker_id)
            hidden = bool(normalized.get("hidden") or False)
            wheel_sync = _coerce_wheel_sync_state(
                prev.get("wheel_sync"),
                enabled=self._wheel_sync_enabled(),
            )
        except Exception:
            hidden = False
            wheel_sync = _build_initial_wheel_sync_state(enabled=self._wheel_sync_enabled())

        self._registry = normalize_worker_registry_record(
            {
                **self._registry,
                "instance_id": self._instance_id,
                "state": WORKER_STATE_IDLE,
                "hidden": hidden,
                "tags": list(self._tags),
                "last_seen_at": now,
                "last_heartbeat_at": now,
                "heartbeat_at": now,
                "current_run_id": None,
                "stop_reason": None,
                "stopped_at": None,
                "updated_at": now,
                "wheel_sync": wheel_sync,
            },
            worker_id=self._worker_id,
        )
        await self._write_worker_registry(self._registry)

    async def _write_worker_registry(self, record: dict[str, Any]) -> None:
        assert self._workers_kv is not None
        preserved_hidden = record.get("hidden")
        try:
            entry = await self._workers_kv.get(self._worker_id)
            current = json.loads(entry.value.decode("utf-8"))
            current_norm = normalize_worker_registry_record(current, worker_id=self._worker_id)
            preserved_hidden = bool(current_norm.get("hidden") or False)
        except Exception:
            preserved_hidden = bool(record.get("hidden") or False)
        record = dict(record)
        record["hidden"] = preserved_hidden
        await self._workers_kv.put(
            self._worker_id,
            json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        )
        async with self._registry_lock:
            self._registry = dict(record)

    async def _set_worker_registry(
        self,
        *,
        state: Any = _UNSET,
        touch: bool = False,
        current_run_id: Any = _UNSET,
        last_run_id: Any = _UNSET,
        last_run_status: Any = _UNSET,
        last_run_started_at: Any = _UNSET,
        last_run_finished_at: Any = _UNSET,
        stopped_at: Any = _UNSET,
        stop_reason: Any = _UNSET,
        wheel_sync: Any = _UNSET,
    ) -> None:
        now = time.time()
        async with self._registry_lock:
            rec = dict(self._registry)
            if state is not self._UNSET:
                rec["state"] = state
            if current_run_id is not self._UNSET:
                rec["current_run_id"] = current_run_id
            if last_run_id is not self._UNSET:
                rec["last_run_id"] = last_run_id
            if last_run_status is not self._UNSET:
                rec["last_run_status"] = last_run_status
            if last_run_started_at is not self._UNSET:
                rec["last_run_started_at"] = last_run_started_at
            if last_run_finished_at is not self._UNSET:
                rec["last_run_finished_at"] = last_run_finished_at
            if stopped_at is not self._UNSET:
                rec["stopped_at"] = stopped_at
            if stop_reason is not self._UNSET:
                rec["stop_reason"] = stop_reason
            if wheel_sync is not self._UNSET:
                rec["wheel_sync"] = _coerce_wheel_sync_state(
                    wheel_sync,
                    enabled=self._wheel_sync_enabled(),
                )
            if touch:
                rec["last_seen_at"] = now
                rec["last_heartbeat_at"] = now
                rec["heartbeat_at"] = now
            rec["updated_at"] = now
            rec["instance_id"] = self._instance_id
            rec["worker_id"] = self._worker_id
            rec["tags"] = list(self._tags)
            normalized = normalize_worker_registry_record(rec, worker_id=self._worker_id)
            self._registry = normalized
        await self._write_worker_registry(normalized)

    async def _worker_registry_loop(self) -> None:
        interval = max(0.1, float(self._config.worker_heartbeat_interval_sec))
        logger = logging.getLogger("pyoco_server.worker")
        while not self._closed:
            try:
                await self._set_worker_registry(touch=True)
            except Exception:
                logger.exception(
                    "worker registry heartbeat failed",
                    extra={"worker_id": self._worker_id},
                )
            await asyncio.sleep(interval)

    async def _execute_job(self, job: RunJob) -> None:
        run_ctx = RunContext(run_id=job.run_id)
        run_ctx.flow_name = job.flow_name
        run_ctx.params = job.params or {}
        run_ctx.metadata["tag"] = job.tag
        run_ctx.metadata["tags"] = list(job.tags or ([job.tag] if job.tag else []))
        if job.tenant_id:
            run_ctx.metadata["tenant_id"] = job.tenant_id
        if job.api_key_id:
            run_ctx.metadata["api_key_id"] = job.api_key_id
        if job.workflow_yaml_sha256:
            run_ctx.metadata["workflow_yaml_sha256"] = job.workflow_yaml_sha256
        if job.workflow_yaml_bytes is not None:
            run_ctx.metadata["workflow_yaml_bytes"] = int(job.workflow_yaml_bytes)

        started_at = time.time()
        try:
            await self._set_worker_registry(
                state=WORKER_STATE_RUNNING,
                current_run_id=job.run_id,
                last_run_started_at=started_at,
                touch=True,
            )
        except Exception:
            # worker registry 更新失敗は実行本体を止めない（best-effort）。
            # Registry failure should not block task execution.
            pass

        try:
            flow = _resolve_flow_for_job(job, self._flow_resolver)
        except KeyError as exc:
            # Deterministic: the worker does not have the requested flow.
            logging.getLogger("pyoco_server.worker").exception(
                "flow not found",
                extra={
                    "err_id": "ERR-PYOCO-0006",
                    "msg_id": "MSG-PYOCO-0006",
                    "run_id": job.run_id,
                    "flow_name": job.flow_name,
                    "tag": job.tag,
                    "worker_id": self._worker_id,
                },
            )
            run_ctx.status = RunStatus.FAILED
            err = f"flow_not_found: {exc}"
            try:
                await publish_dlq(
                    js=self._js,
                    config=self._config,
                    tag=job.tag,
                    reason="flow_not_found",
                    error=err,
                    payload={
                        "run_id": job.run_id,
                        "flow_name": job.flow_name,
                        "tag": job.tag,
                        "tags": job.tags,
                        "tenant_id": job.tenant_id,
                        "api_key_id": job.api_key_id,
                        "worker_id": self._worker_id,
                    },
                )
            except Exception:
                pass
            await self._kv.put(
                job.run_id,
                json.dumps(
                    run_snapshot_from_context(run_ctx, error=err),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            try:
                await self._set_worker_registry(
                    state=WORKER_STATE_IDLE,
                    current_run_id=None,
                    last_run_id=job.run_id,
                    last_run_status="FAILED",
                    last_run_finished_at=time.time(),
                    stopped_at=None,
                    stop_reason=None,
                    touch=True,
                )
            except Exception:
                pass
            return

        # Use the resolved flow name as the canonical name (should match request).
        run_ctx.flow_name = flow.name

        loop = asyncio.get_running_loop()
        backend = NatsKvTraceBackend(
            loop=loop,
            kv=self._kv,
            run_ctx=run_ctx,
            max_snapshot_bytes=int(getattr(self._config, "max_run_snapshot_bytes", 0) or 0),
        )
        engine = Engine(trace_backend=backend)
        cancel_state: dict[str, Any] = {
            "requested": False,
            "requested_at": None,
            "requested_by": None,
            "timeout_logged": False,
        }

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_ctx, engine, cancel_state))

        # Mark worker ownership in snapshot (best-effort).
        snap = run_snapshot_from_context(run_ctx)
        snap["worker_id"] = self._worker_id
        snap = compact_run_snapshot(
            snap,
            max_bytes=int(getattr(self._config, "max_run_snapshot_bytes", 0) or 0),
        )
        await self._kv.put(
            job.run_id,
            json.dumps(snap, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        )

        try:
            # Run Pyoco in a worker thread so the asyncio loop can flush KV writes
            # (trace callbacks schedule coroutines on this loop).
            await asyncio.to_thread(engine.run, flow, job.params, run_ctx)
        except Exception as exc:
            status_now = str(getattr(run_ctx.status, "value", run_ctx.status)).upper()
            if status_now == "CANCELLED":
                backend.set_error(None)
                return
            logging.getLogger("pyoco_server.worker").exception(
                "execution error",
                extra={
                    "err_id": "ERR-PYOCO-0007",
                    "msg_id": "MSG-PYOCO-0007",
                    "run_id": job.run_id,
                    "flow_name": job.flow_name,
                    "tag": job.tag,
                    "worker_id": self._worker_id,
                },
            )
            run_ctx.status = RunStatus.FAILED
            backend.set_error(str(exc))
            # Best-effort DLQ: execution error. This is diagnostic; the run is
            # already terminalized as FAILED.
            if getattr(self._config, "dlq_publish_execution_error", True):
                try:
                    await publish_dlq(
                        js=self._js,
                        config=self._config,
                        tag=job.tag,
                        reason="execution_error",
                        error=str(exc),
                        payload={
                            "run_id": job.run_id,
                            "flow_name": job.flow_name,
                            "tag": job.tag,
                            "tags": job.tags,
                            "tenant_id": job.tenant_id,
                            "api_key_id": job.api_key_id,
                            "worker_id": self._worker_id,
                        },
                    )
                except Exception:
                    pass
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            if cancel_state.get("requested_at") is not None:
                run_ctx.metadata["cancel_requested_at"] = cancel_state["requested_at"]
            if cancel_state.get("requested_by") is not None:
                run_ctx.metadata["cancel_requested_by"] = cancel_state["requested_by"]
            # Ensure terminal snapshot after Engine returns/raises.
            terminal_status = str(getattr(run_ctx.status, "value", run_ctx.status))
            await self._kv.put(
                job.run_id,
                json.dumps(
                    compact_run_snapshot(
                        run_snapshot_from_context(run_ctx, error=backend.get_error()),
                        max_bytes=int(getattr(self._config, "max_run_snapshot_bytes", 0) or 0),
                    ),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            try:
                await self._set_worker_registry(
                    state=WORKER_STATE_IDLE,
                    current_run_id=None,
                    last_run_id=job.run_id,
                    last_run_status=terminal_status,
                    last_run_finished_at=time.time(),
                    stopped_at=None,
                    stop_reason=None,
                    touch=True,
                )
            except Exception:
                pass

    async def _heartbeat_loop(self, run_ctx: RunContext, engine: Engine, cancel_state: dict[str, Any]) -> None:
        assert self._kv is not None

        run_interval = max(0.1, float(self._config.run_heartbeat_interval_sec))
        last_run = 0.0
        cancel_grace_period = float(getattr(self._config, "cancel_grace_period_sec", 0.0) or 0.0)

        while True:
            now = time.time()

            if now - last_run >= run_interval:
                existing = None
                try:
                    entry = await self._kv.get(run_ctx.run_id)
                    existing = json.loads(entry.value.decode("utf-8"))
                except Exception:
                    existing = None

                existing_cancel_at, existing_cancel_by = _extract_cancel_request(existing)
                if existing_cancel_at is not None:
                    cancel_state["requested"] = True
                    cancel_state["requested_at"] = float(cancel_state.get("requested_at") or existing_cancel_at)
                    if existing_cancel_by:
                        cancel_state["requested_by"] = existing_cancel_by
                    run_ctx.metadata["cancel_requested_at"] = cancel_state["requested_at"]
                    if cancel_state.get("requested_by"):
                        run_ctx.metadata["cancel_requested_by"] = cancel_state["requested_by"]
                    try:
                        await asyncio.to_thread(engine.cancel, run_ctx.run_id)
                    except Exception:
                        pass

                status_now = str(getattr(run_ctx.status, "value", run_ctx.status)).upper()
                if (
                    cancel_state.get("requested")
                    and cancel_grace_period > 0.0
                    and not cancel_state.get("timeout_logged")
                    and status_now not in {"COMPLETED", "FAILED", "CANCELLED"}
                ):
                    requested_at = float(cancel_state.get("requested_at") or 0.0)
                    if requested_at > 0.0 and (now - requested_at) >= cancel_grace_period:
                        logging.getLogger("pyoco_server.worker").warning(
                            "cancel request timed out",
                            extra={
                                "err_id": "ERR-PYOCO-0021",
                                "msg_id": "MSG-PYOCO-0021",
                                "run_id": run_ctx.run_id,
                                "worker_id": self._worker_id,
                            },
                        )
                        cancel_state["timeout_logged"] = True

                # Run heartbeat ensures long-running tasks still show "alive" even
                # without task-level trace events.
                snap = run_snapshot_from_context(run_ctx)
                if cancel_state.get("requested"):
                    snap["cancel_requested_at"] = cancel_state.get("requested_at")
                    if cancel_state.get("requested_by"):
                        snap["cancel_requested_by"] = cancel_state.get("requested_by")
                    if str(snap.get("status") or "").upper() not in {"COMPLETED", "FAILED", "CANCELLED"}:
                        snap["status"] = "CANCELLING"
                await self._kv.put(
                    run_ctx.run_id,
                    json.dumps(
                        snap,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
                last_run = now

            await asyncio.sleep(0.1)

    async def _ack_progress_loop(self, msg) -> None:
        """
        Prevent redelivery for long-running runs by periodically sending
        an "in progress" ack to JetStream.
        """

        interval = float(getattr(self._config, "ack_progress_interval_sec", 0.0) or 0.0)
        if interval <= 0:
            return

        # Keep progress interval safely below the consumer AckWait.
        try:
            ack_wait = float(getattr(self._config, "consumer_ack_wait_sec", 0.0) or 0.0)
        except Exception:
            ack_wait = 0.0
        if ack_wait > 0 and interval >= ack_wait:
            interval = max(0.5, ack_wait / 2.0)

        # Send one immediately to reduce timing sensitivity when AckWait is small.
        try:
            await msg.in_progress()
        except Exception:
            return

        while True:
            await asyncio.sleep(interval)
            try:
                await msg.in_progress()
            except Exception:
                # If the message was acked/expired, stop.
                return

    def _wheel_sync_enabled(self) -> bool:
        return bool(getattr(self._config, "wheel_sync_enabled", False))

    def _init_wheel_sync_state(self) -> None:
        if not self._wheel_sync_enabled():
            return
        base = Path(str(getattr(self._config, "wheel_sync_dir", ".pyoco/wheels") or ".pyoco/wheels"))
        if not base.is_absolute():
            base = Path.cwd() / base
        base.mkdir(parents=True, exist_ok=True)
        self._wheel_sync_dir = base
        self._wheel_manifest_path = base / ".installed.json"

    def _load_wheel_manifest(self) -> dict[str, Any]:
        path = self._wheel_manifest_path
        if path is None or not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_wheel_manifest(self, manifest: dict[str, Any]) -> None:
        path = self._wheel_manifest_path
        if path is None:
            return
        path.write_text(
            json.dumps(manifest, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )

    async def _maybe_sync_wheels(self, *, force: bool = False) -> None:
        if not self._wheel_sync_enabled():
            return
        interval = max(0.1, float(getattr(self._config, "wheel_sync_interval_sec", 10.0) or 10.0))
        now = time.time()
        if not force and now < self._next_wheel_sync_at:
            return

        async with self._wheel_sync_lock:
            now_locked = time.time()
            if not force and now_locked < self._next_wheel_sync_at:
                return
            self._next_wheel_sync_at = now_locked + interval
            try:
                status = await self._sync_wheels_once(attempted_at=now_locked)
                await self._set_worker_registry(wheel_sync=status)
            except Exception as exc:
                logging.getLogger("pyoco_server.worker").exception(
                    "wheel sync failed",
                    extra={"worker_id": self._worker_id},
                )
                try:
                    await self._set_worker_registry(
                        wheel_sync=_build_wheel_sync_error_state(
                            previous=self._registry.get("wheel_sync"),
                            attempted_at=now_locked,
                            error=exc,
                        )
                    )
                except Exception:
                    pass

    async def _sync_wheels_once(self, *, attempted_at: Optional[float] = None) -> Dict[str, Any]:
        if self._wheel_store is None or self._wheel_sync_dir is None:
            return _build_initial_wheel_sync_state(enabled=self._wheel_sync_enabled())

        manifest = self._load_wheel_manifest()
        if not isinstance(manifest, dict):
            manifest = {}

        infos = await self._wheel_store.list(ignore_deletes=True)
        worker_tags = {str(tag).strip() for tag in list(self._tags or []) if str(tag).strip()}
        latest_by_package: dict[str, tuple[Version, str, Any]] = {}
        skipped_incompatible: list[dict[str, Any]] = []
        for info in list(infos or []):
            name = str(getattr(info, "name", "") or "")
            if not _WHEEL_FILENAME_RE.fullmatch(name):
                continue
            wheel_tags = _read_wheel_tags_from_info(info)
            if wheel_tags and worker_tags.isdisjoint(wheel_tags):
                continue
            try:
                package_name, package_version, file_tags = _parse_wheel_metadata(name)
            except ValueError:
                continue
            if file_tags and self._supported_wheel_tags.isdisjoint(file_tags):
                skipped_incompatible.append(
                    {
                        "wheel_name": name,
                        "package_name": package_name,
                        "package_version": str(package_version),
                        "reason": "unsupported_wheel_tags",
                    }
                )
                continue
            prev = latest_by_package.get(package_name)
            if prev is None or package_version > prev[0] or (package_version == prev[0] and name > prev[1]):
                latest_by_package[package_name] = (package_version, name, info)
        desired: dict[str, tuple[Any, str, Version]] = {}
        for package_name, (package_version, wheel_name, info) in latest_by_package.items():
            desired[wheel_name] = (info, package_name, package_version)

        changed = False
        removed_wheels: list[str] = []
        updated_wheels: list[str] = []

        # レジストリから消えた wheel はローカル同期ディレクトリからも除外します。
        # Remove local wheel files that are no longer present in the registry.
        for stale_name in [n for n in list(manifest.keys()) if n not in desired]:
            stale_path = self._wheel_sync_dir / stale_name
            try:
                if stale_path.exists():
                    stale_path.unlink()
            except Exception:
                pass
            manifest.pop(stale_name, None)
            removed_wheels.append(stale_name)
            changed = True

        for wheel_name, (info, package_name, package_version) in sorted(desired.items()):
            nuid = str(getattr(info, "nuid", "") or "")
            wheel_path = self._wheel_sync_dir / wheel_name
            current = manifest.get(wheel_name) if isinstance(manifest.get(wheel_name), dict) else {}
            if current and str(current.get("nuid") or "") == nuid and wheel_path.is_file():
                continue

            result = await self._wheel_store.get(wheel_name)
            wheel_bytes = bytes((result.data or b""))
            wheel_path.write_bytes(wheel_bytes)
            await self._install_wheel_file(wheel_path)
            manifest[wheel_name] = {
                "nuid": nuid,
                "package_name": package_name,
                "package_version": str(package_version),
                "size_bytes": int(len(wheel_bytes)),
                "sha256_hex": hashlib.sha256(wheel_bytes).hexdigest(),
                "tags": sorted(_read_wheel_tags_from_info(info)),
                "installed_at": time.time(),
            }
            updated_wheels.append(wheel_name)
            changed = True

        if changed:
            self._save_wheel_manifest(manifest)
        now = time.time()
        return {
            "enabled": True,
            "last_result": "ok",
            "last_attempt_at": float(attempted_at if attempted_at is not None else now),
            "last_success_at": now,
            "last_synced_at": now,
            "last_error": None,
            "selected_count": len(desired),
            "updated_count": len(updated_wheels),
            "removed_count": len(removed_wheels),
            "skipped_incompatible_count": len(skipped_incompatible),
            "selected_wheels": sorted(list(desired.keys()))[:_WHEEL_SYNC_STATUS_MAX_ITEMS],
            "updated_wheels": sorted(updated_wheels)[:_WHEEL_SYNC_STATUS_MAX_ITEMS],
            "removed_wheels": sorted(removed_wheels)[:_WHEEL_SYNC_STATUS_MAX_ITEMS],
            "skipped_incompatible": skipped_incompatible[:_WHEEL_SYNC_STATUS_MAX_ITEMS],
            "installed_wheels": _manifest_to_installed_wheels(manifest),
        }

    async def _install_wheel_file(self, wheel_path: Path) -> None:
        timeout = max(1.0, float(getattr(self._config, "wheel_install_timeout_sec", 180.0) or 180.0))
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--force-reinstall",
            str(wheel_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"wheel install timed out: {wheel_path.name}") from exc

        if proc.returncode != 0:
            detail = (err or out or b"").decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(
                f"wheel install failed (code={proc.returncode}): {wheel_path.name}: {detail}"
            )


    async def _dlq_invalid_msg(self, msg, *, error: str) -> None:
        try:
            subject = getattr(msg, "subject", "") or ""
            tag = subject.split(".")[-1] if subject else "unknown"
            await publish_dlq(
                js=self._js,
                config=self._config,
                tag=tag,
                reason="invalid_job",
                error=error,
                payload={
                    "subject": subject,
                    "worker_id": self._worker_id,
                    "num_delivered": getattr(getattr(msg, "metadata", None), "num_delivered", None),
                    "payload": (msg.data or b"")[:4096].decode("utf-8", errors="replace"),
                },
            )
        except Exception:
            pass


def _extract_cancel_request(snapshot: Any) -> tuple[Optional[float], Optional[str]]:
    if not isinstance(snapshot, dict):
        return None, None
    status = str(snapshot.get("status") or "").upper()
    requested_at = snapshot.get("cancel_requested_at")
    if requested_at is None and status not in {"CANCELLING", "CANCELLED"}:
        return None, None
    try:
        ts = float(requested_at) if requested_at is not None else 0.0
    except Exception:
        ts = 0.0
    if ts <= 0.0:
        ts = time.time()
    requested_by = snapshot.get("cancel_requested_by")
    return ts, (str(requested_by) if requested_by else None)


def _build_initial_wheel_sync_state(*, enabled: bool) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "last_result": ("idle" if enabled else "disabled"),
        "last_attempt_at": None,
        "last_success_at": None,
        "last_synced_at": None,
        "last_error": None,
        "selected_count": 0,
        "updated_count": 0,
        "removed_count": 0,
        "skipped_incompatible_count": 0,
        "selected_wheels": [],
        "updated_wheels": [],
        "removed_wheels": [],
        "skipped_incompatible": [],
        "installed_wheels": [],
    }


def _coerce_wheel_sync_state(raw: Any, *, enabled: bool) -> dict[str, Any]:
    base = _build_initial_wheel_sync_state(enabled=enabled)
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    out["enabled"] = bool(enabled)
    raw_result = str(raw.get("last_result") or out["last_result"]).strip().lower()
    if raw_result not in {"disabled", "idle", "ok", "error"}:
        raw_result = out["last_result"]
    out["last_result"] = raw_result

    for key in ("last_attempt_at", "last_success_at", "last_synced_at"):
        value = raw.get(key)
        if value is None:
            out[key] = None
            continue
        try:
            out[key] = float(value)
        except Exception:
            out[key] = None

    err = raw.get("last_error")
    out["last_error"] = (str(err)[:2000] if err else None)

    for key in ("selected_count", "updated_count", "removed_count", "skipped_incompatible_count"):
        try:
            out[key] = max(0, int(raw.get(key) or 0))
        except Exception:
            out[key] = 0

    for key in ("selected_wheels", "updated_wheels", "removed_wheels", "installed_wheels", "skipped_incompatible"):
        value = raw.get(key)
        if isinstance(value, list):
            out[key] = list(value)[:_WHEEL_SYNC_STATUS_MAX_ITEMS]
        else:
            out[key] = []
    return out


def _build_wheel_sync_error_state(*, previous: Any, attempted_at: float, error: Exception) -> dict[str, Any]:
    out = _coerce_wheel_sync_state(previous, enabled=True)
    out["enabled"] = True
    out["last_result"] = "error"
    out["last_attempt_at"] = float(attempted_at)
    out["last_error"] = str(error)[:2000]
    return out


def _manifest_to_installed_wheels(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for wheel_name in sorted(manifest.keys()):
        meta = manifest.get(wheel_name)
        if not isinstance(meta, dict):
            continue
        package_name = meta.get("package_name")
        package_version = meta.get("package_version")
        if not package_name or not package_version:
            try:
                package_name_i, package_version_i = _parse_wheel_identity(wheel_name)
                package_name = package_name or package_name_i
                package_version = package_version or str(package_version_i)
            except ValueError:
                pass
        items.append(
            {
                "wheel_name": wheel_name,
                "package_name": (str(package_name) if package_name else None),
                "package_version": (str(package_version) if package_version else None),
                "installed_at": meta.get("installed_at"),
                "nuid": meta.get("nuid"),
            }
        )
        if len(items) >= _WHEEL_SYNC_STATUS_MAX_ITEMS:
            break
    return items


def _parse_wheel_metadata(wheel_name: str) -> tuple[str, Version, frozenset[Any]]:
    try:
        dist_name, version, _, tags = parse_wheel_filename(wheel_name)
    except InvalidWheelFilename as exc:
        raise ValueError("invalid wheel filename") from exc
    return str(dist_name), version, frozenset(tags)


def _parse_wheel_identity(wheel_name: str) -> tuple[str, Version]:
    package_name, package_version, _ = _parse_wheel_metadata(wheel_name)
    return package_name, package_version


def _parse_wheel_tags_csv(raw: Any) -> set[str]:
    if raw is None:
        return set()
    parts = [str(p).strip() for p in str(raw).split(",") if str(p).strip()]
    out: set[str] = set()
    for tag in parts:
        if _WHEEL_TAG_RE.fullmatch(tag):
            out.add(tag)
    return out


def _read_wheel_tags_from_info(info: Any) -> set[str]:
    headers = getattr(info, "headers", None)
    if not isinstance(headers, dict):
        return set()
    raw = headers.get(_WHEEL_TAGS_HEADER)
    if raw is None:
        raw = headers.get(_WHEEL_TAGS_HEADER.title())
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    return _parse_wheel_tags_csv(raw)


def _decode_job(raw: bytes) -> RunJob:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid_schema")
    if "run_id" not in data or "flow_name" not in data:
        raise ValueError("missing_fields")
    return RunJob(
        run_id=data["run_id"],
        flow_name=data["flow_name"],
        tag=(data.get("tag") or "default"),
        tags=list(data.get("tags") or []),
        params=data.get("params") or {},
        submitted_at=float(data.get("submitted_at") or 0.0),
        tenant_id=data.get("tenant_id"),
        api_key_id=data.get("api_key_id"),
        workflow_yaml=data.get("workflow_yaml"),
        workflow_yaml_sha256=data.get("workflow_yaml_sha256"),
        workflow_yaml_bytes=data.get("workflow_yaml_bytes"),
    )


def _resolve_flow_for_job(job: RunJob, flow_resolver: Callable[[str], Flow]) -> Flow:
    """
    Resolve a Flow for a job.

    - Normal path: flow_resolver(flow_name)
    - YAML path: build Flow from embedded flow.yaml (Phase 4)
    """

    if not job.workflow_yaml:
        return flow_resolver(job.flow_name)

    # YAML-defined single-flow config uses a canonical name ("main").
    from pyoco.core.models import Flow as PyocoFlow
    from pyoco.discovery.loader import TaskLoader
    from pyoco.dsl.syntax import TaskWrapper, switch

    parsed = parse_workflow_yaml_bytes(job.workflow_yaml.encode("utf-8"), require_flow=True)
    cfg = parsed.config
    flow_conf = cfg.flow
    if flow_conf is None:
        raise KeyError("missing_flow")

    loader = TaskLoader(cfg)
    loader.load()

    flow = PyocoFlow(name=(job.flow_name or "main"))
    for t in loader.tasks.values():
        flow.add_task(t)

    eval_context = {name: TaskWrapper(task) for name, task in loader.tasks.items()}
    eval_context["switch"] = switch
    eval_context["flow"] = flow

    # Graph evaluation wires dependencies between tasks.
    exec(flow_conf.graph, {}, eval_context)
    return flow
