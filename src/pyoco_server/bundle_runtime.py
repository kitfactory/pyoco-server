from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import threading
import time
import uuid
from typing import Any, Dict, Optional

from nats.js.errors import KeyNotFoundError

from .config import NatsBackendConfig
from .models import RunJob
from .workflow_yaml import parse_workflow_bundle_bytes

RUN_STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


@dataclass(frozen=True)
class RunRelationRecord:
    run_id: str
    root_run_id: str
    parent_run_id: Optional[str]
    workflow_name: str
    bundle_hash: str
    spawned_from_task: Optional[str]
    depth: int
    entry_workflow: str
    submitted_at: float


def serialize_run_job(job: RunJob) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "run_id": job.run_id,
        "flow_name": job.flow_name,
        "tag": job.tag,
        "tags": list(job.tags or []),
        "params": job.params or {},
        "submitted_at": float(job.submitted_at or 0.0),
    }
    if job.tenant_id:
        payload["tenant_id"] = job.tenant_id
    if job.api_key_id:
        payload["api_key_id"] = job.api_key_id
    if job.workflow_yaml:
        payload["workflow_yaml"] = job.workflow_yaml
    if job.workflow_yaml_sha256:
        payload["workflow_yaml_sha256"] = job.workflow_yaml_sha256
    if job.workflow_yaml_bytes is not None:
        payload["workflow_yaml_bytes"] = int(job.workflow_yaml_bytes)
    if job.workflow_bundle:
        payload["workflow_bundle"] = job.workflow_bundle
    if job.workflow_bundle_sha256:
        payload["workflow_bundle_sha256"] = job.workflow_bundle_sha256
        payload["bundle_hash"] = job.workflow_bundle_sha256
    if job.workflow_bundle_bytes is not None:
        payload["workflow_bundle_bytes"] = int(job.workflow_bundle_bytes)
    if job.root_run_id:
        payload["root_run_id"] = job.root_run_id
    if job.parent_run_id:
        payload["parent_run_id"] = job.parent_run_id
    if job.spawned_from_task:
        payload["spawned_from_task"] = job.spawned_from_task
    if job.spawn_depth is not None:
        payload["spawn_depth"] = int(job.spawn_depth)
    if job.entry_workflow:
        payload["entry_workflow"] = job.entry_workflow
    return payload


def build_initial_run_snapshot(
    job: RunJob,
    *,
    status: str,
    approval_required: bool = False,
    approval_status: Optional[str] = None,
    approval_requested_at: Optional[float] = None,
    approved_at: Optional[float] = None,
    approved_by: Optional[str] = None,
    approval_comment: Optional[str] = None,
    rejected_at: Optional[float] = None,
    rejected_by: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    now = time.time()
    return {
        "run_id": job.run_id,
        "flow_name": job.flow_name,
        "tag": job.tag,
        "tags": list(job.tags or ([job.tag] if job.tag else [])),
        "tenant_id": job.tenant_id,
        "api_key_id": job.api_key_id,
        "workflow_yaml_sha256": job.workflow_yaml_sha256,
        "workflow_yaml_bytes": job.workflow_yaml_bytes,
        "bundle_hash": job.workflow_bundle_sha256,
        "workflow_bundle_bytes": job.workflow_bundle_bytes,
        "root_run_id": job.root_run_id,
        "parent_run_id": job.parent_run_id,
        "spawned_from_task": job.spawned_from_task,
        "spawn_depth": int(job.spawn_depth or 0),
        "entry_workflow": job.entry_workflow,
        "approval_required": bool(approval_required),
        "approval_status": approval_status,
        "approval_requested_at": approval_requested_at,
        "approved_at": approved_at,
        "approved_by": approved_by,
        "approval_comment": approval_comment,
        "rejected_at": rejected_at,
        "rejected_by": rejected_by,
        "rejection_reason": rejection_reason,
        "status": str(status),
        "params": dict(job.params or {}),
        "tasks": {},
        "task_records": {},
        "start_time": None,
        "end_time": None,
        "heartbeat_at": now,
        "updated_at": now,
        "error": None,
        "child_run_ids": [],
        "spawn_count": 0,
        "result_summary": None,
    }


def build_run_relation_record(job: RunJob) -> Optional[RunRelationRecord]:
    if not job.workflow_bundle_sha256:
        return None
    return RunRelationRecord(
        run_id=job.run_id,
        root_run_id=(job.root_run_id or job.run_id),
        parent_run_id=job.parent_run_id,
        workflow_name=job.flow_name,
        bundle_hash=job.workflow_bundle_sha256,
        spawned_from_task=job.spawned_from_task,
        depth=int(job.spawn_depth or 0),
        entry_workflow=(job.entry_workflow or job.flow_name),
        submitted_at=float(job.submitted_at or time.time()),
    )


def build_child_run_result_summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    task_records = snapshot.get("task_records") or {}
    outputs: Dict[str, Any] = {}
    metrics: Dict[str, float] = {}
    artifacts: list[Dict[str, Any]] = []

    if isinstance(task_records, dict):
        for task_name, record in task_records.items():
            if not isinstance(record, dict):
                continue
            if "output" in record:
                outputs[str(task_name)] = record.get("output")
                for key, value in _extract_numeric_metrics(task_name, record.get("output")).items():
                    metrics[key] = value
            task_artifacts = record.get("artifacts") or {}
            if isinstance(task_artifacts, dict):
                for artifact_name, artifact_value in task_artifacts.items():
                    artifacts.append(
                        {
                            "task": str(task_name),
                            "name": str(artifact_name),
                            "value": artifact_value,
                        }
                    )

    return {
        "run_id": snapshot.get("run_id"),
        "status": snapshot.get("status"),
        "outputs": outputs,
        "summary_metrics": metrics,
        "artifacts": artifacts,
        "error_summary": snapshot.get("error"),
    }


def run_job_from_snapshot(snapshot: Dict[str, Any], *, workflow_bundle: Optional[str] = None) -> RunJob:
    return RunJob(
        run_id=str(snapshot.get("run_id") or ""),
        flow_name=str(snapshot.get("flow_name") or ""),
        tag=str(snapshot.get("tag") or "default"),
        tags=list(snapshot.get("tags") or []),
        params=dict(snapshot.get("params") or {}),
        submitted_at=float(snapshot.get("updated_at") or time.time()),
        tenant_id=snapshot.get("tenant_id"),
        api_key_id=snapshot.get("api_key_id"),
        workflow_yaml_sha256=snapshot.get("workflow_yaml_sha256"),
        workflow_yaml_bytes=snapshot.get("workflow_yaml_bytes"),
        workflow_bundle=workflow_bundle,
        workflow_bundle_sha256=snapshot.get("bundle_hash"),
        workflow_bundle_bytes=snapshot.get("workflow_bundle_bytes"),
        root_run_id=snapshot.get("root_run_id"),
        parent_run_id=snapshot.get("parent_run_id"),
        spawned_from_task=snapshot.get("spawned_from_task"),
        spawn_depth=int(snapshot.get("spawn_depth") or 0),
        entry_workflow=snapshot.get("entry_workflow"),
    )


async def store_workflow_bundle(bundle_kv: Any, *, bundle_hash: str, raw: bytes) -> None:
    await bundle_kv.put(str(bundle_hash), bytes(raw))


async def load_workflow_bundle(bundle_kv: Any, *, bundle_hash: str) -> str:
    entry = await bundle_kv.get(str(bundle_hash))
    return entry.value.decode("utf-8")


async def put_run_relation(relations_kv: Any, relation: RunRelationRecord) -> None:
    await relations_kv.put(
        relation.run_id,
        json.dumps(asdict(relation), ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
    )


async def delete_run_relation(relations_kv: Any, run_id: str) -> None:
    try:
        await relations_kv.delete(run_id)
    except Exception:
        pass


async def create_run_record(
    *,
    js: Any,
    runs_kv: Any,
    relations_kv: Any,
    config: NatsBackendConfig,
    job: RunJob,
    status: str,
    approval_required: bool = False,
    approval_status: Optional[str] = None,
    approval_requested_at: Optional[float] = None,
    approved_at: Optional[float] = None,
    approved_by: Optional[str] = None,
    approval_comment: Optional[str] = None,
    rejected_at: Optional[float] = None,
    rejected_by: Optional[str] = None,
    rejection_reason: Optional[str] = None,
    publish: bool = True,
) -> Dict[str, Any]:
    snapshot = build_initial_run_snapshot(
        job,
        status=status,
        approval_required=approval_required,
        approval_status=approval_status,
        approval_requested_at=approval_requested_at,
        approved_at=approved_at,
        approved_by=approved_by,
        approval_comment=approval_comment,
        rejected_at=rejected_at,
        rejected_by=rejected_by,
        rejection_reason=rejection_reason,
    )
    relation = build_run_relation_record(job)

    await runs_kv.put(
        job.run_id,
        json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
    )
    try:
        if relation is not None:
            await put_run_relation(relations_kv, relation)
        if publish:
            await js.publish(
                subject=f"{config.work_subject_prefix}.{job.tag}",
                payload=json.dumps(serialize_run_job(job), ensure_ascii=True, separators=(",", ":")).encode(
                    "utf-8"
                ),
                stream=config.work_stream,
            )
    except Exception:
        try:
            await runs_kv.delete(job.run_id)
        except Exception:
            pass
        if relation is not None:
            await delete_run_relation(relations_kv, job.run_id)
        raise
    return snapshot


class SpawnOrchestrator:
    """
    親 run から child run を起動し、完了待機と結果要約取得を行います。
    Spawn child runs from a parent run and wait for their terminal summary.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        js: Any,
        runs_kv: Any,
        relations_kv: Any,
        config: NatsBackendConfig,
        parent_job: RunJob,
    ):
        self._loop = loop
        self._js = js
        self._runs_kv = runs_kv
        self._relations_kv = relations_kv
        self._config = config
        self._parent_job = parent_job
        self._spawn_count = 0
        self._active_children: set[str] = set()
        self._lock = threading.Lock()

    def make_task_callable(self, *, task_name: str, child_workflow_name: str):
        def _spawn_callable(ctx=None, **kwargs):
            return self.spawn(
                ctx=ctx,
                task_name=task_name,
                child_workflow_name=child_workflow_name,
                child_params=kwargs,
            )

        return _spawn_callable

    def spawn(
        self,
        *,
        ctx: Any,
        task_name: str,
        child_workflow_name: str,
        child_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        if ctx is None or getattr(ctx, "run_context", None) is None:
            raise RuntimeError("spawn_task_requires_run_context")

        parent_run_ctx = ctx.run_context
        if int(self._parent_job.spawn_depth or 0) >= 1:
            raise RuntimeError("child_respawn_not_allowed")

        with self._lock:
            max_children = int(getattr(self._config, "spawn_max_child_runs", 0) or 0)
            if max_children > 0 and self._spawn_count >= max_children:
                raise RuntimeError("spawn_max_child_runs_exceeded")
            max_parallel = int(getattr(self._config, "spawn_max_parallel_child_runs", 0) or 0)
            if max_parallel > 0 and len(self._active_children) >= max_parallel:
                raise RuntimeError("spawn_max_parallel_child_runs_exceeded")
            self._spawn_count += 1

        merged_params = dict(getattr(ctx, "params", {}) or {})
        merged_params.update(dict(child_params or {}))

        child_run_id = ""
        try:
            child_run_id = asyncio.run_coroutine_threadsafe(
                self._submit_child_run(
                    parent_run_ctx=parent_run_ctx,
                    task_name=task_name,
                    child_workflow_name=child_workflow_name,
                    child_params=merged_params,
                ),
                self._loop,
            ).result()
            with self._lock:
                self._active_children.add(child_run_id)
            self._record_parent_child(parent_run_ctx=parent_run_ctx, child_run_id=child_run_id)
            summary = asyncio.run_coroutine_threadsafe(
                self._wait_for_child(child_run_id=child_run_id, parent_run_ctx=parent_run_ctx),
                self._loop,
            ).result()
            return summary
        finally:
            if child_run_id:
                with self._lock:
                    self._active_children.discard(child_run_id)

    async def _submit_child_run(
        self,
        *,
        parent_run_ctx: Any,
        task_name: str,
        child_workflow_name: str,
        child_params: Dict[str, Any],
    ) -> str:
        child_run_id = str(uuid.uuid4())
        child_tag = (
            str(getattr(self._config, "spawn_child_tag", "") or "").strip() or self._parent_job.tag or "default"
        )
        submitted_at = time.time()
        child_job = RunJob(
            run_id=child_run_id,
            flow_name=child_workflow_name,
            tag=child_tag,
            tags=[child_tag],
            params=dict(child_params or {}),
            submitted_at=submitted_at,
            tenant_id=self._parent_job.tenant_id,
            api_key_id=self._parent_job.api_key_id,
            workflow_bundle=self._parent_job.workflow_bundle,
            workflow_bundle_sha256=self._parent_job.workflow_bundle_sha256,
            workflow_bundle_bytes=self._parent_job.workflow_bundle_bytes,
            root_run_id=(self._parent_job.root_run_id or self._parent_job.run_id),
            parent_run_id=str(parent_run_ctx.run_id),
            spawned_from_task=task_name,
            spawn_depth=int(self._parent_job.spawn_depth or 0) + 1,
            entry_workflow=(self._parent_job.entry_workflow or self._parent_job.flow_name),
        )
        await create_run_record(
            js=self._js,
            runs_kv=self._runs_kv,
            relations_kv=self._relations_kv,
            config=self._config,
            job=child_job,
            status="PENDING",
            approval_required=False,
            approval_status="not_required",
            publish=True,
        )
        return child_run_id

    async def _wait_for_child(self, *, child_run_id: str, parent_run_ctx: Any) -> Dict[str, Any]:
        timeout_sec = float(getattr(self._config, "spawn_timeout_sec", 0.0) or 0.0)
        poll_interval_sec = max(
            0.05,
            float(getattr(self._config, "spawn_poll_interval_sec", 0.2) or 0.2),
        )
        deadline = (time.time() + timeout_sec) if timeout_sec > 0.0 else None

        while True:
            if deadline is not None and time.time() >= deadline:
                raise RuntimeError("child_wait_timeout")
            parent_status = str(getattr(parent_run_ctx.status, "value", parent_run_ctx.status)).upper()
            if parent_status in {"CANCELLING", "CANCELLED"}:
                raise RuntimeError("parent_cancelled_during_child_wait")

            try:
                entry = await self._runs_kv.get(child_run_id)
            except KeyNotFoundError:
                await asyncio.sleep(poll_interval_sec)
                continue
            snapshot = json.loads(entry.value.decode("utf-8"))
            status = str(snapshot.get("status") or "").upper()
            if status in TERMINAL_RUN_STATUSES:
                summary = snapshot.get("result_summary")
                if not isinstance(summary, dict):
                    summary = build_child_run_result_summary(snapshot)
                return summary
            await asyncio.sleep(poll_interval_sec)

    def _record_parent_child(self, *, parent_run_ctx: Any, child_run_id: str) -> None:
        meta = getattr(parent_run_ctx, "metadata", None)
        if not isinstance(meta, dict):
            return
        child_run_ids = meta.get("child_run_ids")
        if not isinstance(child_run_ids, list):
            child_run_ids = []
        child_run_ids.append(child_run_id)
        meta["child_run_ids"] = child_run_ids
        meta["spawn_count"] = len(child_run_ids)


def _extract_numeric_metrics(task_name: str, value: Any) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    if isinstance(value, bool):
        return metrics
    if isinstance(value, (int, float)):
        metrics[str(task_name)] = float(value)
        return metrics
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                metrics[f"{task_name}.{key}"] = float(item)
    return metrics


def build_flow_from_bundle_job(job: RunJob, *, spawn_orchestrator: Optional[SpawnOrchestrator] = None):
    if not job.workflow_bundle:
        raise KeyError("missing_workflow_bundle")

    parsed = parse_workflow_bundle_bytes(job.workflow_bundle.encode("utf-8"))
    workflow = parsed.workflows.get(job.flow_name)
    if workflow is None:
        raise KeyError(job.flow_name)
    if int(job.spawn_depth or 0) >= 1 and workflow.reachable_spawn_task_names:
        raise RuntimeError("child_respawn_not_allowed")

    from pyoco.core.models import Flow as PyocoFlow
    from pyoco.core.models import Task as PyocoTask
    from pyoco.dsl.syntax import TaskWrapper, switch

    tasks: Dict[str, Any] = {}
    for task_name, task_conf in workflow.tasks.items():
        if task_conf.is_spawn:
            if spawn_orchestrator is None:
                raise RuntimeError("spawn_orchestrator_required")
            func = spawn_orchestrator.make_task_callable(
                task_name=task_name,
                child_workflow_name=str(task_conf.spawn),
            )
        else:
            func = _load_task_callable(str(task_conf.callable))
        task = PyocoTask(func=func, name=task_name)
        task.inputs = dict(task_conf.inputs or {})
        task.outputs = list(task_conf.outputs or [])
        tasks[task_name] = task

    flow = PyocoFlow(name=(job.flow_name or workflow.name))
    for task in tasks.values():
        flow.add_task(task)

    eval_context = {name: TaskWrapper(task) for name, task in tasks.items()}
    eval_context["switch"] = switch
    eval_context["flow"] = flow
    exec(workflow.flow.graph, {}, eval_context)
    return flow


def _load_task_callable(callable_path: str):
    import importlib

    from pyoco.core.models import Task as PyocoTask
    from pyoco.dsl.syntax import TaskWrapper

    module_path, func_name = callable_path.split(":", 1)
    mod = importlib.import_module(module_path)
    obj = getattr(mod, func_name)
    if isinstance(obj, TaskWrapper):
        return obj.task.func
    if isinstance(obj, PyocoTask):
        return obj.func
    return obj
