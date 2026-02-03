import json
import logging

from pyoco_server import configure_logging


def _flush_root_handlers() -> None:
    root = logging.getLogger()
    for h in root.handlers:
        try:
            h.flush()
        except Exception:
            pass


def test_configure_logging_json_includes_exception_origin(monkeypatch, capsys):
    root = logging.getLogger()
    prev_level = root.level
    prev_handlers = list(root.handlers)

    try:
        monkeypatch.setenv("PYOCO_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("PYOCO_LOG_FORMAT", "json")
        monkeypatch.setenv("PYOCO_LOG_UTC", "true")
        monkeypatch.setenv("PYOCO_LOG_INCLUDE_TRACEBACK", "true")

        configure_logging(service="pyoco-server:test")

        log = logging.getLogger("tests.logging")

        def raise_original():
            raise RuntimeError("boom")

        try:
            raise_original()
        except Exception:
            log.exception(
                "something failed",
                extra={
                    "err_id": "ERR-PYOCO-0007",
                    "msg_id": "MSG-PYOCO-0007",
                    "run_id": "r1",
                    "flow_name": "main",
                    "tag": "default",
                    "worker_id": "w1",
                },
            )

        _flush_root_handlers()
        out = capsys.readouterr().out.strip().splitlines()
        assert out, "expected a log line on stdout"

        rec = json.loads(out[-1])
        # Base fields
        assert rec["service"] == "pyoco-server:test"
        assert rec["level"] == "ERROR"
        assert rec["logger"] == "tests.logging"
        assert rec["message"] == "something failed"
        assert "pathname" in rec and "lineno" in rec and "func" in rec
        # Context fields (extra)
        assert rec["err_id"] == "ERR-PYOCO-0007"
        assert rec["msg_id"] == "MSG-PYOCO-0007"
        assert rec["run_id"] == "r1"
        assert rec["flow_name"] == "main"
        assert rec["tag"] == "default"
        assert rec["worker_id"] == "w1"

        # Exception fields
        assert rec["exc_type"] == "RuntimeError"
        assert rec["exc_message"] == "boom"
        assert "exc_traceback" in rec and "RuntimeError" in rec["exc_traceback"]
        assert "exc_origin" in rec
        assert rec["exc_origin"]["func"] == "raise_original"
    finally:
        # Restore global logging to avoid leaking state into other tests.
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in prev_handlers:
            root.addHandler(h)
        root.setLevel(prev_level)
