from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Optional

from pyoco.core.models import RunContext, RunStatus, TaskState
from pyoco.trace.backend import TraceBackend

from .models import compact_run_snapshot, run_snapshot_from_context


class NatsKvTraceBackend(TraceBackend):
    """
    Bridge Pyoco's synchronous TraceBackend API to async JetStream KV writes.

    Engine callbacks can happen from worker threads (ThreadPoolExecutor), so we
    schedule async KV writes on the worker's asyncio loop.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        kv,
        run_ctx: RunContext,
        flush_interval_sec: float = 0.25,
        max_snapshot_bytes: int = 0,
    ):
        self._loop = loop
        self._kv = kv
        self._run_ctx = run_ctx
        self._flush_interval_sec = flush_interval_sec
        self._max_snapshot_bytes = int(max_snapshot_bytes or 0)

        self._lock = threading.Lock()
        self._scheduled = False
        self._dirty = False
        self._last_flush = 0.0
        self._error: Optional[str] = None

    def set_error(self, error: Optional[str]) -> None:
        self._error = error

    def get_error(self) -> Optional[str]:
        return self._error

    def _mark_dirty(self) -> None:
        with self._lock:
            if self._scheduled:
                self._dirty = True
                return
            self._scheduled = True
        asyncio.run_coroutine_threadsafe(self._flush_runner(), self._loop)

    async def _flush_runner(self) -> None:
        try:
            while True:
                # Coalesce updates and enforce a minimum flush interval.
                now = time.time()
                wait = self._flush_interval_sec - (now - self._last_flush)
                if wait > 0:
                    await asyncio.sleep(wait)
                await self._flush_once()
                with self._lock:
                    if self._dirty:
                        self._dirty = False
                        continue
                    self._scheduled = False
                    return
        except Exception:
            with self._lock:
                self._scheduled = False
            raise

    async def _flush_once(self) -> None:
        self._last_flush = time.time()
        snap = run_snapshot_from_context(self._run_ctx, error=self._error)
        snap = compact_run_snapshot(snap, max_bytes=self._max_snapshot_bytes)
        await self._kv.put(
            self._run_ctx.run_id,
            json.dumps(snap, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        )

    # TraceBackend interface ----------------------------------------------
    def on_flow_start(self, flow_name: str, run_id: str = None):
        # Ensure RUNNING is visible as soon as the worker starts.
        self._run_ctx.status = RunStatus.RUNNING
        self._mark_dirty()

    def on_flow_end(self, flow_name: str):
        # Engine sets COMPLETED after calling on_flow_end; we want the snapshot
        # to become terminal ASAP.
        if self._run_ctx.status == RunStatus.RUNNING:
            self._run_ctx.status = RunStatus.COMPLETED
        self._mark_dirty()

    def on_node_start(self, node_name: str):
        self._run_ctx.tasks[node_name] = TaskState.RUNNING
        self._mark_dirty()

    def on_node_end(self, node_name: str, duration_ms: float):
        self._run_ctx.tasks[node_name] = TaskState.SUCCEEDED
        self._mark_dirty()

    def on_node_error(self, node_name: str, error: Exception):
        self._run_ctx.tasks[node_name] = TaskState.FAILED
        self.set_error(str(error))
        self._mark_dirty()
