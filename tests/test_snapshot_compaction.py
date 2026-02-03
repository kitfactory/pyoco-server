from pyoco_server.models import compact_run_snapshot


def test_compact_run_snapshot_drops_task_records_when_oversize():
    snap = {
        "run_id": "r1",
        "flow_name": "main",
        "status": "RUNNING",
        "params": {},
        "tasks": {"t1": "RUNNING"},
        "task_records": {"t1": {"traceback": "x" * 2000}},
        "heartbeat_at": 0.0,
        "updated_at": 0.0,
        "error": None,
    }
    out = compact_run_snapshot(snap, max_bytes=200)
    assert out.get("task_records_truncated") is True
    assert out.get("task_records") == {}

