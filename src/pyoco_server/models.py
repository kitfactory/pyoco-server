from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional

from pyoco.core.models import RunContext


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def compact_run_snapshot(snapshot: Dict[str, Any], *, max_bytes: int) -> Dict[str, Any]:
    """
    Keep KV snapshots bounded. If a snapshot is too large, drop `task_records`
    (tasks state stays) and mark `task_records_truncated=true`.
    """

    if max_bytes <= 0:
        return snapshot

    try:
        raw = __import__("json").dumps(snapshot, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
    except Exception:
        return snapshot

    if len(raw) <= max_bytes:
        snapshot.pop("task_records_truncated", None)
        return snapshot

    # Drop the heaviest field first.
    reduced = dict(snapshot)
    reduced["task_records"] = {}
    reduced["task_records_truncated"] = True

    # If it still exceeds, keep the flag anyway; callers may choose a higher cap.
    return reduced


def run_snapshot_from_context(run_ctx: RunContext, *, error: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a JSON-serializable "latest state" snapshot for status visibility.
    Intentionally keeps the payload small.
    """

    now = time.time()
    meta = getattr(run_ctx, "metadata", {}) or {}
    return {
        "run_id": run_ctx.run_id,
        "flow_name": run_ctx.flow_name,
        "tag": meta.get("tag"),
        "tags": meta.get("tags") or ([] if meta.get("tag") is None else [meta.get("tag")]),
        "tenant_id": meta.get("tenant_id"),
        "api_key_id": meta.get("api_key_id"),
        "workflow_yaml_sha256": meta.get("workflow_yaml_sha256"),
        "workflow_yaml_bytes": meta.get("workflow_yaml_bytes"),
        "status": _enum_value(run_ctx.status),
        "params": run_ctx.params or {},
        "tasks": {k: _enum_value(v) for k, v in (run_ctx.tasks or {}).items()},
        "task_records": run_ctx.serialize_task_records() if hasattr(run_ctx, "serialize_task_records") else {},
        "start_time": getattr(run_ctx, "start_time", None),
        "end_time": getattr(run_ctx, "end_time", None),
        "heartbeat_at": now,
        "updated_at": now,
        "error": error,
    }


@dataclass(frozen=True)
class RunJob:
    run_id: str
    flow_name: str
    tag: str
    tags: list[str]
    params: Dict[str, Any]
    submitted_at: float
    tenant_id: Optional[str] = None
    api_key_id: Optional[str] = None
    workflow_yaml: Optional[str] = None
    workflow_yaml_sha256: Optional[str] = None
    workflow_yaml_bytes: Optional[int] = None
