from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from .http_client import PyocoHttpClient


_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
_ERR_ID = "ERR-PYOCO-0018"
_ERR_MSG = "CLI引数が不正です（入力形式を確認してください）"


class _CliInputError(ValueError):
    pass


class _ClientArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        usage = self.format_usage().strip()
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: {message}\n"
            f"- usage: {usage}\n"
            f"- hint: pyoco-client <subcommand> -h"
        )


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _parse_json_object(raw: str, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be JSON object")
    return value


def _parse_param_assignments(items: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in items:
        if "=" not in raw:
            raise _CliInputError(
                f"{_ERR_ID}: {_ERR_MSG}\n"
                f"- reason: --param must be key=value ({raw!r})\n"
                "- hint: pyoco-client submit --param x=1 --param name=alice"
            )
        key, value_text = raw.split("=", 1)
        key = key.strip()
        value_text = value_text.strip()
        if not key:
            raise _CliInputError(
                f"{_ERR_ID}: {_ERR_MSG}\n"
                f"- reason: --param key is empty ({raw!r})\n"
                "- hint: pyoco-client submit --param x=1"
            )
        if value_text == "":
            out[key] = ""
            continue
        try:
            out[key] = json.loads(value_text)
        except json.JSONDecodeError:
            out[key] = value_text
    return out


def _parse_params_file(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: failed to read --params-file: {path} ({exc})\n"
            "- hint: check file path and read permission"
        ) from exc

    json_exc: Exception | None = None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        json_exc = exc
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as yaml_exc:
            raise _CliInputError(
                f"{_ERR_ID}: {_ERR_MSG}\n"
                f"- reason: --params-file must be JSON/YAML object ({path})\n"
                f"- detail: json={json_exc}; yaml={yaml_exc}\n"
                "- hint: file example: {\"x\":1} or x: 1"
            ) from yaml_exc

    if not isinstance(value, dict):
        raise _CliInputError(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: --params-file must contain object at top level ({path})\n"
            "- hint: file example: {\"x\":1}"
        )
    return value


def _build_submit_params(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.params_file:
        payload.update(_parse_params_file(str(args.params_file)))
    if args.params is not None:
        payload.update(_parse_json_object(args.params, field="--params"))
    if args.param:
        payload.update(_parse_param_assignments([str(it) for it in args.param]))
    return payload


def _parse_tags(raw: Optional[str]) -> Optional[list[str]]:
    if raw is None:
        return None
    tags = [t.strip() for t in str(raw).split(",") if t.strip()]
    return tags or None


def _build_parser() -> argparse.ArgumentParser:
    p = _ClientArgumentParser(prog="pyoco-client")
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--api-key", default=None, help="Value for HTTP auth header")
    p.add_argument("--api-key-header", default="X-API-Key")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_ClientArgumentParser)

    s = sub.add_parser("submit", help="Submit a run")
    s.add_argument("--flow-name", default="main")
    s.add_argument("--params", default=None, help='JSON object, e.g. \'{"x":1}\'')
    s.add_argument("--params-file", default=None, help="JSON/YAML object file")
    s.add_argument(
        "--param",
        action="append",
        default=[],
        help="key=value pair (repeatable, overrides --params and --params-file)",
    )
    s.add_argument("--tag", default=None)
    s.add_argument("--tags", default=None, help="comma-separated tags")

    sy = sub.add_parser("submit-yaml", help="Submit a flow.yaml run")
    sy.add_argument("--workflow-file", required=True, help="path to flow.yaml")
    sy.add_argument("--flow-name", required=True)
    sy.add_argument("--tag", required=True)

    g = sub.add_parser("get", help="Get run snapshot")
    g.add_argument("run_id")
    g.add_argument("--records", action="store_true", help="include task_records")

    t = sub.add_parser("tasks", help="Get run tasks")
    t.add_argument("run_id")

    l = sub.add_parser("list", help="List runs (compat mode)")
    l.add_argument("--status", default=None)
    l.add_argument("--flow", default=None)
    l.add_argument("--tag", default=None)
    l.add_argument("--full", action="store_true")
    l.add_argument("--limit", type=int, default=None)
    l.add_argument("--output", choices=["json", "table"], default="json")

    lv = sub.add_parser("list-vnext", help="List runs (vnext delta mode)")
    lv.add_argument("--status", default=None)
    lv.add_argument("--flow", default=None)
    lv.add_argument("--tag", default=None)
    lv.add_argument("--full", action="store_true")
    lv.add_argument("--limit", type=int, default=None)
    lv.add_argument("--updated-after", type=float, default=None)
    lv.add_argument("--cursor", default=None)
    lv.add_argument("--workflow-yaml-sha256", default=None)
    lv.add_argument("--output", choices=["json", "table"], default="json")

    w = sub.add_parser("watch", help="Watch run via SSE")
    w.add_argument("run_id")
    w.add_argument("--records", action="store_true")
    w.add_argument("--since", type=float, default=None)
    w.add_argument("--timeout-sec", type=int, default=None)
    w.add_argument("--max-events", type=int, default=0, help="0 means unlimited")
    w.add_argument("--until-terminal", action="store_true")
    w.add_argument("--output", choices=["json", "status"], default="json")

    c = sub.add_parser("cancel", help="Cancel a run")
    c.add_argument("--run-id", required=True)
    c.add_argument("--wait", action="store_true", help="wait until terminal status")
    c.add_argument("--timeout-sec", type=int, default=30)

    sub.add_parser("workers", help="Get active workers")
    sub.add_parser("wheels", help="List wheel registry")
    wh = sub.add_parser("wheel-history", help="List wheel upload/delete history")
    wh.add_argument("--limit", type=int, default=100)
    wh.add_argument("--wheel-name", default=None, help="filter by wheel filename")
    wh.add_argument("--action", choices=["upload", "delete"], default=None, help="filter by action")
    wu = sub.add_parser("wheel-upload", help="Upload a wheel into registry")
    wu.add_argument("--wheel-file", required=True, help="path to *.whl")
    wu.add_argument("--tags", default=None, help="comma-separated tags")
    wu.add_argument("--replace", dest="replace", action="store_true", default=True)
    wu.add_argument("--no-replace", dest="replace", action="store_false")
    wd = sub.add_parser("wheel-delete", help="Delete a wheel from registry")
    wd.add_argument("--name", required=True, help="wheel filename")
    sub.add_parser("metrics", help="Get metrics text")
    return p


def _to_run_table_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items:
        row = [
            str(item.get("run_id", "-")),
            str(item.get("status", "-")),
            str(item.get("flow_name", "-")),
            str(item.get("tag", "-")),
            str(item.get("updated_at", "-")),
        ]
        rows.append(row)
    return rows


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        sys.stdout.write("(no items)\n")
        sys.stdout.flush()
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _line(cells: list[str]) -> str:
        return "  ".join(cells[idx].ljust(widths[idx]) for idx in range(len(headers)))

    sys.stdout.write(_line(headers) + "\n")
    for row in rows:
        sys.stdout.write(_line(row) + "\n")
    sys.stdout.flush()


def _print_watch_status(evt: dict[str, Any]) -> None:
    event = str(evt.get("event", "message"))
    data = evt.get("data") or {}
    snapshot = data.get("snapshot") or {}
    run_id = str(data.get("run_id") or snapshot.get("run_id") or "-")
    status = str(snapshot.get("status") or "-")
    ts = str(data.get("ts") or snapshot.get("updated_at") or "-")
    sys.stdout.write(f"{ts}\t{event}\t{status}\t{run_id}\n")
    sys.stdout.flush()


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    resp = exc.response
    req = exc.request
    detail = (resp.text or "").strip()
    base = f"HTTP {resp.status_code} {req.method} {req.url.path}"
    if detail:
        return f"{base}: {detail}"
    return base


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _CliInputError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    client: Optional[PyocoHttpClient] = None
    try:
        client = PyocoHttpClient(
            args.server,
            api_key=args.api_key,
            api_key_header=args.api_key_header,
        )
        if args.command == "submit":
            payload = _build_submit_params(args)
            out = client.submit_run(
                args.flow_name,
                params=payload,
                tag=args.tag,
                tags=_parse_tags(args.tags),
            )
            _print_json(out)
            return 0

        if args.command == "submit-yaml":
            workflow = Path(args.workflow_file).read_text(encoding="utf-8")
            out = client.submit_run_yaml(workflow, flow_name=args.flow_name, tag=args.tag)
            _print_json(out)
            return 0

        if args.command == "get":
            out = client.get_run_with_records(args.run_id) if args.records else client.get_run(args.run_id)
            _print_json(out)
            return 0

        if args.command == "tasks":
            _print_json(client.get_tasks(args.run_id))
            return 0

        if args.command == "list":
            out = client.list_runs(
                status=args.status,
                flow=args.flow,
                tag=args.tag,
                full=bool(args.full),
                limit=args.limit,
            )
            if args.output == "table":
                _print_table(
                    headers=["run_id", "status", "flow_name", "tag", "updated_at"],
                    rows=_to_run_table_rows(out),
                )
            else:
                _print_json(out)
            return 0

        if args.command == "list-vnext":
            out = client.list_runs_vnext(
                status=args.status,
                flow=args.flow,
                tag=args.tag,
                full=bool(args.full),
                limit=args.limit,
                updated_after=args.updated_after,
                cursor=args.cursor,
                workflow_yaml_sha256=args.workflow_yaml_sha256,
            )
            if args.output == "table":
                items = out.get("items") if isinstance(out, dict) else None
                _print_table(
                    headers=["run_id", "status", "flow_name", "tag", "updated_at"],
                    rows=_to_run_table_rows(items if isinstance(items, list) else []),
                )
                if isinstance(out, dict) and out.get("next_cursor"):
                    sys.stdout.write(f"next_cursor: {out['next_cursor']}\n")
                    sys.stdout.flush()
            else:
                _print_json(out)
            return 0

        if args.command == "watch":
            count = 0
            watch_iter = client.watch_run(
                args.run_id,
                include_records=bool(args.records),
                since=args.since,
                timeout_sec=args.timeout_sec,
            )
            try:
                for evt in watch_iter:
                    if args.output == "status":
                        _print_watch_status(evt)
                    else:
                        _print_json(evt)
                    count += 1
                    if int(args.max_events or 0) > 0 and count >= int(args.max_events):
                        break
                    if args.until_terminal:
                        status = ((evt.get("data") or {}).get("snapshot") or {}).get("status")
                        if status in _TERMINAL_STATUSES:
                            break
            finally:
                close = getattr(watch_iter, "close", None)
                if callable(close):
                    close()
            return 0

        if args.command == "cancel":
            out = client.cancel_run(
                args.run_id,
                wait=bool(args.wait),
                timeout_sec=args.timeout_sec,
            )
            _print_json(out)
            return 0

        if args.command == "workers":
            _print_json(client.get_workers())
            return 0

        if args.command == "wheels":
            _print_json(client.list_wheels())
            return 0

        if args.command == "wheel-history":
            _print_json(
                client.list_wheel_history(
                    limit=args.limit,
                    wheel_name=args.wheel_name,
                    action=args.action,
                )
            )
            return 0

        if args.command == "wheel-upload":
            wheel_path = Path(args.wheel_file)
            data = wheel_path.read_bytes()
            out = client.upload_wheel(
                filename=wheel_path.name,
                data=data,
                replace=bool(args.replace),
                tags=_parse_tags(args.tags),
            )
            _print_json(out)
            return 0

        if args.command == "wheel-delete":
            _print_json(client.delete_wheel(args.name))
            return 0

        if args.command == "metrics":
            sys.stdout.write(client.get_metrics())
            return 0

        raise SystemExit(2)
    except _CliInputError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except ValueError as exc:
        sys.stderr.write(
            f"{_ERR_ID}: {_ERR_MSG}\n"
            f"- reason: {exc}\n"
            "- hint: pyoco-client submit --flow-name main --param x=1 --tag default\n"
        )
        return 1
    except httpx.HTTPStatusError as exc:
        sys.stderr.write(
            "ERR-PYOCO-HTTP: request failed\n"
            f"- reason: {_format_http_status_error(exc)}\n"
            "- hint: check server status and request parameters\n"
        )
        return 1
    except httpx.HTTPError as exc:
        sys.stderr.write(
            "ERR-PYOCO-HTTP: connection error\n"
            f"- reason: {exc}\n"
            "- hint: check --server URL and gateway availability\n"
        )
        return 1
    except TimeoutError as exc:
        sys.stderr.write(
            "ERR-PYOCO-CANCEL: wait timeout\n"
            f"- reason: {exc}\n"
            "- hint: retry cancel or inspect run/worker status\n"
        )
        return 1
    except OSError as exc:
        sys.stderr.write(
            f"{_ERR_ID}: file I/O error\n"
            f"- reason: {exc}\n"
            "- hint: check file path and permission\n"
        )
        return 1
    except KeyboardInterrupt:
        return 130
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code == 0:
            raise
        return 1
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"ERR-PYOCO-UNEXPECTED: {exc}\n")
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
