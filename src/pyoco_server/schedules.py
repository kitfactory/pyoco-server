from __future__ import annotations

from datetime import datetime
import math
import time
from typing import Any, Dict, Optional


SCHEDULE_TYPE_ONCE = "once"
SCHEDULE_TYPE_INTERVAL = "interval"
SCHEDULE_STATUS_ACTIVE = "ACTIVE"
SCHEDULE_STATUS_COMPLETED = "COMPLETED"
SCHEDULE_STATUSES = {SCHEDULE_STATUS_ACTIVE, SCHEDULE_STATUS_COMPLETED}
SCHEDULE_TYPES = {SCHEDULE_TYPE_ONCE, SCHEDULE_TYPE_INTERVAL}


def parse_schedule_datetime(raw: str, *, field_name: str) -> float:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone offset")
    return float(parsed.timestamp())


def compute_interval_next_run_at(anchor_at: float, interval_seconds: float, *, now: Optional[float] = None) -> float:
    base = float(anchor_at)
    interval = float(interval_seconds)
    ts_now = float(time.time() if now is None else now)
    if interval <= 0.0:
        raise ValueError("interval_seconds must be positive")
    if base > ts_now:
        return base
    steps = math.floor((ts_now - base) / interval) + 1
    return base + (steps * interval)


def build_schedule_record(
    *,
    schedule_id: str,
    flow_name: str,
    tag: str,
    workflow_yaml: str,
    workflow_yaml_sha256: str,
    workflow_yaml_bytes: int,
    params: Dict[str, Any],
    created_at: float,
    schedule_type: str,
    tenant_id: Optional[str],
    api_key_id: Optional[str],
    run_at: Optional[float] = None,
    interval_seconds: Optional[float] = None,
    start_at: Optional[float] = None,
) -> Dict[str, Any]:
    type_name = str(schedule_type or "").strip().lower()
    if type_name not in SCHEDULE_TYPES:
        raise ValueError("invalid schedule_type")

    record: Dict[str, Any] = {
        "schedule_id": str(schedule_id),
        "flow_name": str(flow_name),
        "tag": str(tag),
        "status": SCHEDULE_STATUS_ACTIVE,
        "schedule_type": type_name,
        "workflow_yaml": str(workflow_yaml),
        "workflow_yaml_sha256": str(workflow_yaml_sha256),
        "workflow_yaml_bytes": int(workflow_yaml_bytes),
        "params": dict(params or {}),
        "tenant_id": tenant_id,
        "api_key_id": api_key_id,
        "created_at": float(created_at),
        "updated_at": float(created_at),
        "last_submitted_at": None,
        "last_run_id": None,
        "dispatch_count": 0,
        "last_error": None,
        "lease_until": None,
    }

    if type_name == SCHEDULE_TYPE_ONCE:
        if run_at is None:
            raise ValueError("run_at is required for once schedule")
        record["run_at"] = float(run_at)
        record["next_run_at"] = float(run_at)
        record["interval_seconds"] = None
        record["start_at"] = None
        return record

    if interval_seconds is None:
        raise ValueError("interval_seconds is required for interval schedule")
    interval = float(interval_seconds)
    if interval <= 0.0:
        raise ValueError("interval_seconds must be positive")
    anchor = float(start_at if start_at is not None else (float(created_at) + interval))
    record["run_at"] = None
    record["interval_seconds"] = interval
    record["start_at"] = anchor
    record["next_run_at"] = compute_interval_next_run_at(anchor, interval, now=(created_at - 0.000001))
    return record


def normalize_schedule_record(raw: Dict[str, Any] | None, *, schedule_id: str) -> Dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    record: Dict[str, Any] = dict(src)
    record["schedule_id"] = str(src.get("schedule_id") or schedule_id)
    record["flow_name"] = str(src.get("flow_name") or "")
    record["tag"] = str(src.get("tag") or "")

    schedule_type = str(src.get("schedule_type") or SCHEDULE_TYPE_ONCE).strip().lower()
    if schedule_type not in SCHEDULE_TYPES:
        schedule_type = SCHEDULE_TYPE_ONCE
    record["schedule_type"] = schedule_type

    status = str(src.get("status") or SCHEDULE_STATUS_ACTIVE).strip().upper()
    if status not in SCHEDULE_STATUSES:
        status = SCHEDULE_STATUS_ACTIVE
    record["status"] = status

    for key in (
        "workflow_yaml_sha256",
        "workflow_yaml",
        "tenant_id",
        "api_key_id",
        "last_run_id",
        "last_error",
    ):
        record[key] = src.get(key)

    record["workflow_yaml_bytes"] = int(src.get("workflow_yaml_bytes") or 0)
    record["params"] = dict(src.get("params") or {})

    for key in (
        "created_at",
        "updated_at",
        "last_submitted_at",
        "run_at",
        "next_run_at",
        "interval_seconds",
        "start_at",
        "lease_until",
    ):
        value = src.get(key)
        record[key] = (float(value) if value is not None else None)

    record["dispatch_count"] = int(src.get("dispatch_count") or 0)
    return record


def claim_is_active(record: Dict[str, Any], *, now: Optional[float] = None) -> bool:
    lease_until = record.get("lease_until")
    if lease_until is None:
        return False
    ts_now = float(time.time() if now is None else now)
    return float(lease_until) > ts_now


def is_schedule_due(record: Dict[str, Any], *, now: Optional[float] = None) -> bool:
    if str(record.get("status") or "").upper() != SCHEDULE_STATUS_ACTIVE:
        return False
    next_run_at = record.get("next_run_at")
    if next_run_at is None:
        return False
    ts_now = float(time.time() if now is None else now)
    return float(next_run_at) <= ts_now and not claim_is_active(record, now=ts_now)


def advance_schedule_after_dispatch(record: Dict[str, Any], *, submitted_at: float) -> Dict[str, Any]:
    updated = dict(record)
    updated["updated_at"] = float(submitted_at)
    updated["last_submitted_at"] = float(submitted_at)
    updated["dispatch_count"] = int(updated.get("dispatch_count") or 0) + 1
    updated["last_error"] = None
    updated["lease_until"] = None

    schedule_type = str(updated.get("schedule_type") or "").strip().lower()
    if schedule_type == SCHEDULE_TYPE_ONCE:
        updated["status"] = SCHEDULE_STATUS_COMPLETED
        updated["next_run_at"] = None
        return updated

    start_at = float(updated.get("start_at") or submitted_at)
    interval_seconds = float(updated.get("interval_seconds") or 0.0)
    updated["next_run_at"] = compute_interval_next_run_at(start_at, interval_seconds, now=submitted_at)
    return updated


def schedule_record_for_http(record: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "schedule_id",
        "flow_name",
        "tag",
        "status",
        "schedule_type",
        "workflow_yaml_sha256",
        "workflow_yaml_bytes",
        "tenant_id",
        "api_key_id",
        "created_at",
        "updated_at",
        "run_at",
        "next_run_at",
        "interval_seconds",
        "start_at",
        "last_submitted_at",
        "last_run_id",
        "dispatch_count",
        "last_error",
    )
    return {key: record.get(key) for key in keys}
