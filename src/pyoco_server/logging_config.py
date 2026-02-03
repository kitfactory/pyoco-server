from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from typing import Any, Dict, Optional


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


class _JsonLogFormatter(logging.Formatter):
    """
    運用ログ向けの JSON Lines フォーマッタです。
    JSON Lines formatter for operational logs.

    要件（docs/spec.md, docs/architecture.md）：
    - エラー時は元例外（例外クラス/メッセージ/トレースバック）を記録する。
    - どのプログラム/どの場所か（logger名、ファイル/行/関数）を記録する。

    Requirements (docs/spec.md, docs/architecture.md):
    - On error, record original exception type/message/traceback.
    - Record program and location (logger, file, line, func).
    """

    def __init__(self, *, service: str, use_utc: bool, include_traceback: bool):
        super().__init__()
        self._service = service
        self._use_utc = use_utc
        self._include_traceback = include_traceback

    def _ts(self, created: float) -> str:
        if self._use_utc:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created))
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(created))

    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": self._ts(record.created),
            "service": self._service,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "pathname": record.pathname,
            "lineno": record.lineno,
            "func": record.funcName,
            "process": record.process,
            "thread": record.thread,
        }

        # Include structured context if provided via logger(..., extra={...}).
        for k, v in record.__dict__.items():
            if k.startswith("_"):
                continue
            if k in base:
                continue
            if k in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            }:
                continue
            # Avoid serialisation errors: fallback to str().
            try:
                json.dumps({k: v}, ensure_ascii=True)
                base[k] = v
            except Exception:
                base[k] = str(v)

        if record.exc_info:
            exc_type, exc, tb = record.exc_info
            base["exc_type"] = getattr(exc_type, "__name__", str(exc_type))
            base["exc_message"] = str(exc)
            if self._include_traceback and tb is not None:
                base["exc_traceback"] = "".join(traceback.format_exception(exc_type, exc, tb))
                # Provide a quick "origin" hint (where it was raised).
                frames = traceback.extract_tb(tb)
                if frames:
                    last = frames[-1]
                    base["exc_origin"] = {
                        "file": last.filename,
                        "line": last.lineno,
                        "func": last.name,
                    }

        return json.dumps(base, ensure_ascii=True, separators=(",", ":"))


class _TextLogFormatter(logging.Formatter):
    def __init__(self, *, service: str, include_traceback: bool):
        super().__init__()
        self._service = service
        self._include_traceback = include_traceback

    def format(self, record: logging.LogRecord) -> str:
        prefix = f"{record.levelname} {self._service} {record.name} {record.pathname}:{record.lineno} {record.funcName}"
        msg = record.getMessage()
        line = f"{prefix} - {msg}"

        # Attach common structured keys when present.
        keys = []
        for k in ("err_id", "msg_id", "run_id", "flow_name", "tag", "worker_id", "reason"):
            if hasattr(record, k):
                keys.append(f"{k}={getattr(record, k)}")
        if keys:
            line += " (" + ", ".join(keys) + ")"

        if record.exc_info and self._include_traceback:
            exc_type, exc, tb = record.exc_info
            line += "\n" + "".join(traceback.format_exception(exc_type, exc, tb))
        return line


def configure_logging(*, service: str) -> None:
    """
    env vars に基づき root logging を設定します。
    Configure root logging based on env vars.

    対応する env vars：
    - PYOCO_LOG_LEVEL: DEBUG|INFO|WARNING|ERROR (default: INFO)
    - PYOCO_LOG_FORMAT: json|text (default: json)
    - PYOCO_LOG_UTC: true|false (default: true)
    - PYOCO_LOG_INCLUDE_TRACEBACK: true|false (default: true)
    """

    level_name = _env("PYOCO_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = _env("PYOCO_LOG_FORMAT", "json").lower()
    use_utc = _env_bool("PYOCO_LOG_UTC", True)
    include_tb = _env_bool("PYOCO_LOG_INCLUDE_TRACEBACK", True)

    root = logging.getLogger()
    root.setLevel(level)

    # 同一プロセス内で複数回呼ばれても二重出力にならないようにします。
    # Avoid duplicate handlers if called multiple times in the same process.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    if fmt == "text":
        handler.setFormatter(_TextLogFormatter(service=service, include_traceback=include_tb))
    else:
        handler.setFormatter(_JsonLogFormatter(service=service, use_utc=use_utc, include_traceback=include_tb))
    root.addHandler(handler)
