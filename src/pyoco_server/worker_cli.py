from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from pyoco.core.models import Flow

from .config import NatsBackendConfig
from .logging_config import configure_logging
from .worker import PyocoNatsWorker

_ERR_ID = "ERR-PYOCO-0018"
_ERR_MSG = "CLI引数が不正です（入力形式を確認してください）"


class _CliInputError(ValueError):
    pass


class _WorkerArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        usage = self.format_usage().strip()
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: {message}\n"
            f"- usage: {usage}\n"
            "- hint: pyoco-worker --help"
        )


def _flow_resolver_hint() -> str:
    return (
        "example:\n"
        "  pyoco-worker --flow-resolver examples/hello_flow.py:resolve_flow\n"
        "  pyoco-worker --flow-resolver mypkg.flows:resolve_flow"
    )


def _build_parser() -> argparse.ArgumentParser:
    p = _WorkerArgumentParser(
        prog="pyoco-worker",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=_flow_resolver_hint(),
    )
    p.add_argument("--nats-url", default=None, help="Override PYOCO_NATS_URL")
    p.add_argument("--tags", default="default", help="comma-separated tags (OR)")
    p.add_argument("--worker-id", default="worker")
    p.add_argument(
        "--flow-resolver",
        default=None,
        help="module:function or path/to/file.py:function",
    )
    p.add_argument("--wheel-sync", dest="wheel_sync", action="store_true", default=None)
    p.add_argument("--no-wheel-sync", dest="wheel_sync", action="store_false")
    p.add_argument("--wheel-sync-dir", default=None, help="local wheel sync directory")
    p.add_argument("--wheel-sync-interval-sec", type=float, default=None)
    p.add_argument("--wheel-install-timeout-sec", type=float, default=None)
    p.add_argument("--poll-timeout", type=float, default=1.0)
    p.add_argument("--run-once", action="store_true")
    return p


def _resolve_attr(obj: Any, attr_path: str) -> Any:
    cur = obj
    for name in attr_path.split("."):
        cur = getattr(cur, name)
    return cur


def _load_flow_resolver(spec: str) -> Callable[[str], Flow]:
    if ":" not in spec:
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: --flow-resolver must be module:function or file.py:function ({spec!r})\n"
            "- hint: pyoco-worker --flow-resolver examples/hello_flow.py:resolve_flow"
        )

    module_spec, attr = spec.split(":", 1)
    module_spec = module_spec.strip()
    attr = attr.strip()
    if not module_spec or not attr:
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: --flow-resolver must include module/file and callable ({spec!r})\n"
            "- hint: pyoco-worker --flow-resolver mypkg.flows:resolve_flow"
        )

    if module_spec.endswith(".py") or "/" in module_spec or "\\" in module_spec:
        path = Path(module_spec).expanduser().resolve()
        if not path.exists():
            raise _CliInputError(
                f"{_ERR_ID}: {_ERR_MSG}\n"
                f"- reason: flow_resolver file not found: {path}\n"
                "- hint: check file path or use module:function format"
            )
        module_name = f"pyoco_worker_resolver_{path.stem}"
        module_loader = importlib.util.spec_from_file_location(module_name, str(path))
        if module_loader is None or module_loader.loader is None:
            raise _CliInputError(
                f"{_ERR_ID}: {_ERR_MSG}\n"
                f"- reason: failed to load resolver module from: {path}\n"
                "- hint: ensure the file is valid Python module"
            )
        module = importlib.util.module_from_spec(module_loader)
        module_loader.loader.exec_module(module)
    else:
        module = importlib.import_module(module_spec)

    resolver = _resolve_attr(module, attr)
    if not callable(resolver):
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: flow_resolver is not callable: {spec}\n"
            "- hint: target must be a function: module:function"
        )
    return resolver


def _yaml_only_resolver(flow_name: str) -> Flow:
    raise KeyError(flow_name)


async def _run(args: argparse.Namespace) -> int:
    configure_logging(service="pyoco-server:worker")

    cfg = NatsBackendConfig.from_env()
    overrides: dict[str, Any] = {}
    if args.nats_url:
        overrides["nats_url"] = args.nats_url
    if args.wheel_sync is not None:
        overrides["wheel_sync_enabled"] = bool(args.wheel_sync)
    if args.wheel_sync_dir:
        overrides["wheel_sync_dir"] = str(args.wheel_sync_dir)
    if args.wheel_sync_interval_sec is not None:
        overrides["wheel_sync_interval_sec"] = float(args.wheel_sync_interval_sec)
    if args.wheel_install_timeout_sec is not None:
        overrides["wheel_install_timeout_sec"] = float(args.wheel_install_timeout_sec)
    if overrides:
        cfg = NatsBackendConfig(**{**cfg.__dict__, **overrides})

    tags = [t.strip() for t in str(args.tags).split(",") if t.strip()]
    if not tags:
        tags = [cfg.default_tag]

    flow_resolver = _yaml_only_resolver
    if args.flow_resolver:
        flow_resolver = _load_flow_resolver(args.flow_resolver)

    worker = await PyocoNatsWorker.connect(
        config=cfg,
        flow_resolver=flow_resolver,
        worker_id=str(args.worker_id),
        tags=tags,
    )
    try:
        if args.run_once:
            await worker.run_once(timeout=float(args.poll_timeout))
            return 0
        while True:
            await worker.run_once(timeout=float(args.poll_timeout))
    finally:
        await worker.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _CliInputError as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        return asyncio.run(_run(args))
    except _CliInputError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"{_ERR_ID}: {_ERR_MSG}\n- reason: {exc}\n- hint: pyoco-worker --help", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
