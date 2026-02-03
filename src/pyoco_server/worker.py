from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, Optional

import nats
import logging
from nats.errors import TimeoutError as NatsTimeoutError
from nats.errors import Error as NatsError
from nats.js import api
from nats.js.errors import BadRequestError

from pyoco.core.engine import Engine
from pyoco.core.models import Flow, RunContext, RunStatus

from .config import NatsBackendConfig
from .dlq import publish_dlq
from .models import RunJob, compact_run_snapshot, run_snapshot_from_context
from .resources import ensure_resources
from .trace import NatsKvTraceBackend
from .workflow_yaml import parse_workflow_yaml_bytes


class PyocoNatsWorker:
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
        self._subs = {}
        self._flow_resolver = flow_resolver
        self._worker_id = worker_id
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

    async def close(self) -> None:
        await self._nc.close()

    async def run_once(self, timeout: float = 1.0) -> Optional[str]:
        """
        Fetch and process a single job. Returns run_id when a job was processed,
        or None when no message was available within timeout.
        """

        if not self._subs:
            return None

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
            await msg.ack()
            return run_id
        finally:
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

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

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_ctx))

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
            # Ensure terminal snapshot after Engine returns/raises.
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

    async def _heartbeat_loop(self, run_ctx: RunContext) -> None:
        assert self._kv is not None
        assert self._workers_kv is not None

        run_interval = float(self._config.run_heartbeat_interval_sec)
        worker_interval = float(self._config.worker_heartbeat_interval_sec)
        last_run = 0.0
        last_worker = 0.0

        while True:
            now = time.time()

            if now - last_worker >= worker_interval:
                # Worker liveness (TTL-based bucket).
                await self._workers_kv.put(
                    self._worker_id,
                    json.dumps(
                        {"worker_id": self._worker_id, "heartbeat_at": now, "tags": list(self._tags)},
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
                last_worker = now

            if now - last_run >= run_interval:
                # Run heartbeat ensures long-running tasks still show "alive" even
                # without task-level trace events.
                await self._kv.put(
                    run_ctx.run_id,
                    json.dumps(
                        run_snapshot_from_context(run_ctx),
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
