from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional

from pyoco.core.models import RunContext

WORKER_STATE_RUNNING = "RUNNING"
WORKER_STATE_IDLE = "IDLE"
WORKER_STATE_STOPPED_GRACEFUL = "STOPPED_GRACEFUL"
WORKER_STATE_DISCONNECTED = "DISCONNECTED"

WORKER_STATES = {
    WORKER_STATE_RUNNING,
    WORKER_STATE_IDLE,
    WORKER_STATE_STOPPED_GRACEFUL,
    WORKER_STATE_DISCONNECTED,
}
WORKER_ACTIVE_STATES = {WORKER_STATE_RUNNING, WORKER_STATE_IDLE}


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
        "cancel_requested_at": meta.get("cancel_requested_at"),
        "cancel_requested_by": meta.get("cancel_requested_by"),
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


def normalize_worker_registry_record(
    raw: Dict[str, Any] | None,
    *,
    worker_id: str,
) -> Dict[str, Any]:
    """
    Worker registry レコードを互換入力から正規化します。
    Normalize worker registry records while keeping backward compatibility.
    """

    src = raw if isinstance(raw, dict) else {}
    out = dict(src)
    out["worker_id"] = str(src.get("worker_id") or worker_id)
    out["instance_id"] = str(src.get("instance_id") or out["worker_id"])

    state = str(src.get("state") or "").strip().upper()
    if state not in WORKER_STATES:
        # 旧フォーマット（heartbeat_atのみ）からの移行時は IDLE 扱いにする。
        # Fallback for legacy liveness-only records.
        state = WORKER_STATE_IDLE
    out["state"] = state

    heartbeat_at = float(src.get("heartbeat_at") or 0.0)
    last_seen_at = float(src.get("last_seen_at") or heartbeat_at or 0.0)
    last_heartbeat_at = float(src.get("last_heartbeat_at") or heartbeat_at or last_seen_at)
    out["last_seen_at"] = last_seen_at
    out["last_heartbeat_at"] = last_heartbeat_at
    # v0.4互換: 既存UI/テスト向けに heartbeat_at も維持する。
    # Backward compatibility alias for legacy clients/tests.
    out["heartbeat_at"] = last_heartbeat_at

    tags = src.get("tags")
    if isinstance(tags, list):
        out["tags"] = [str(t) for t in tags if str(t).strip()]
    else:
        out["tags"] = []
    out["hidden"] = bool(src.get("hidden") or False)

    out["current_run_id"] = src.get("current_run_id")
    out["last_run_id"] = src.get("last_run_id")
    out["last_run_status"] = src.get("last_run_status")
    out["last_run_started_at"] = src.get("last_run_started_at")
    out["last_run_finished_at"] = src.get("last_run_finished_at")
    out["stopped_at"] = src.get("stopped_at")
    out["stop_reason"] = src.get("stop_reason")
    out["updated_at"] = float(src.get("updated_at") or 0.0)
    return out


def derive_worker_effective_state(
    record: Dict[str, Any],
    *,
    now: Optional[float] = None,
    disconnect_timeout_sec: float = 20.0,
) -> str:
    """
    Worker の表示状態を導出する。
    Derive display state including disconnected interpretation.
    """

    current = str(record.get("state") or "").strip().upper()
    if current not in WORKER_STATES:
        current = WORKER_STATE_IDLE

    if current == WORKER_STATE_STOPPED_GRACEFUL:
        return WORKER_STATE_STOPPED_GRACEFUL

    if current == WORKER_STATE_DISCONNECTED:
        return WORKER_STATE_DISCONNECTED

    ts_now = float(now or time.time())
    try:
        last_seen_at = float(record.get("last_seen_at") or 0.0)
    except Exception:
        last_seen_at = 0.0
    timeout = float(disconnect_timeout_sec or 0.0)

    if timeout > 0.0 and (ts_now - last_seen_at) > timeout:
        return WORKER_STATE_DISCONNECTED
    return current


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
