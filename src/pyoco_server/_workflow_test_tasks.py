from __future__ import annotations


def add_one(x: int = 0) -> int:
    # テスト用の最小タスク。Test-only minimal task.
    return int(x) + 1


def to_text(add_one: int) -> str:
    # テスト用の最小タスク。Test-only minimal task.
    return f"v={int(add_one)}"
