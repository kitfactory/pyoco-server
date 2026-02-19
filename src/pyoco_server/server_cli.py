from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional

import uvicorn


class _CliError(RuntimeError):
    pass


def _print_cli_error(message: str) -> None:
    print(f"[pyoco-server][ERR-PYOCO-0018] {message}", file=sys.stderr)


def _normalize_argv(argv: Optional[list[str]]) -> list[str]:
    """
    互換性のため、旧フラット形式を `up` サブコマンド形式に正規化します。
    Normalize legacy flat arguments into `up` subcommand form for compatibility.
    """

    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        return ["up"]
    if raw[0] in {"-h", "--help", "up"}:
        return raw
    if raw[0].startswith("-"):
        return ["up", *raw]
    return raw


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pyoco-server")
    sub = p.add_subparsers(dest="command")

    up = sub.add_parser("up", help="Start HTTP Gateway")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=8000)
    up.add_argument("--log-level", default="warning")
    up.add_argument("--nats-url", default=None, help="Override PYOCO_NATS_URL")
    up.add_argument(
        "--dashboard-lang",
        choices=["auto", "ja", "en"],
        default=None,
        help="Override dashboard locale policy (PYOCO_DASHBOARD_LANG).",
    )
    up.add_argument(
        "--with-nats-bootstrap",
        action="store_true",
        help="Start local NATS via nats-bootstrap (single-node) before server startup.",
    )
    up.add_argument("--nats-listen-host", default="127.0.0.1")
    up.add_argument("--nats-client-port", type=int, default=4222)
    up.add_argument("--nats-http-port", type=int, default=8222)
    return p


def _find_nats_bootstrap() -> Optional[str]:
    return shutil.which("nats-bootstrap")


def _port_is_open(host: str, port: int, timeout_sec: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(float(timeout_sec))
        try:
            s.connect((host, int(port)))
            return True
        except OSError:
            return False


def _ensure_port_available(host: str, port: int, *, label: str) -> None:
    if _port_is_open(host, port, timeout_sec=0.2):
        raise _CliError(f"{label} port is already in use: {host}:{port}")


def _wait_for_port_open(
    host: str,
    port: int,
    *,
    proc: subprocess.Popen[bytes],
    timeout_sec: float = 10.0,
) -> None:
    deadline = time.time() + float(timeout_sec)
    while time.time() < deadline:
        if proc.poll() is not None:
            raise _CliError(f"nats-bootstrap exited early with code {proc.returncode}")
        if _port_is_open(host, port, timeout_sec=0.2):
            return
        time.sleep(0.05)
    raise _CliError(f"timeout waiting for NATS startup: {host}:{port}")


def _stop_process(proc: subprocess.Popen[bytes], timeout_sec: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=float(timeout_sec))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)


def _managed_nats_url(host: str, port: int) -> str:
    return f"nats://{host}:{port}"


def _start_managed_nats(args: argparse.Namespace) -> subprocess.Popen[bytes]:
    nats_bootstrap = _find_nats_bootstrap()
    if not nats_bootstrap:
        raise _CliError(
            "nats-bootstrap is required for --with-nats-bootstrap. "
            "Install dev dependencies (e.g. `uv sync --group dev`)."
        )

    _ensure_port_available(args.nats_listen_host, args.nats_client_port, label="NATS client")
    _ensure_port_available(args.nats_listen_host, args.nats_http_port, label="NATS monitor")

    cmd = [
        nats_bootstrap,
        "up",
        "--",
        "-js",
        "-a",
        str(args.nats_listen_host),
        "-p",
        str(args.nats_client_port),
        "-m",
        str(args.nats_http_port),
    ]
    proc = subprocess.Popen(cmd)
    try:
        _wait_for_port_open(
            args.nats_listen_host,
            args.nats_client_port,
            proc=proc,
            timeout_sec=10.0,
        )
    except Exception:
        _stop_process(proc)
        raise
    return proc


def _run_up(args: argparse.Namespace) -> int:
    managed_proc: Optional[subprocess.Popen[bytes]] = None
    try:
        if args.with_nats_bootstrap:
            managed_url = _managed_nats_url(args.nats_listen_host, args.nats_client_port)
            if args.nats_url and str(args.nats_url).strip() and str(args.nats_url).strip() != managed_url:
                raise _CliError(
                    f"--nats-url mismatch with managed NATS: expected {managed_url}, got {args.nats_url}"
                )
            os.environ["PYOCO_NATS_URL"] = managed_url
            managed_proc = _start_managed_nats(args)
        elif args.nats_url:
            os.environ["PYOCO_NATS_URL"] = str(args.nats_url)

        if args.dashboard_lang:
            os.environ["PYOCO_DASHBOARD_LANG"] = str(args.dashboard_lang)

        uvicorn.run(
            "pyoco_server.http_api:create_app",
            factory=True,
            host=args.host,
            port=int(args.port),
            log_level=str(args.log_level),
        )
        return 0
    except _CliError as exc:
        _print_cli_error(str(exc))
        return 1
    finally:
        if managed_proc is not None:
            _stop_process(managed_proc)


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    normalized = _normalize_argv(argv)
    try:
        args = parser.parse_args(normalized)
    except SystemExit as exc:
        return int(exc.code)

    if not getattr(args, "command", None):
        args.command = "up"

    if args.command == "up":
        return _run_up(args)

    _print_cli_error(f"unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
