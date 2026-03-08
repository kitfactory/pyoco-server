from __future__ import annotations


def add_one(x: int = 0) -> int:
    # テスト用の最小タスク。Test-only minimal task.
    return int(x) + 1


def to_text(add_one: int) -> str:
    # テスト用の最小タスク。Test-only minimal task.
    return f"v={int(add_one)}"


def echo(x=None):
    # テスト用の受け渡しタスク。Test-only passthrough task.
    return x


def child_summary_text(run_child: dict) -> str:
    # child result summary を親で読む最小タスク。Test-only child summary reader.
    outputs = dict((run_child or {}).get("outputs") or {})
    text_value = outputs.get("to_text")
    return f"{(run_child or {}).get('status')}:{text_value}"
