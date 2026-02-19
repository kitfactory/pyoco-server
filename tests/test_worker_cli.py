from __future__ import annotations

from pathlib import Path

import pytest

from pyoco_server import worker_cli
from pyoco_server.worker_cli import _load_flow_resolver, _yaml_only_resolver


def _write_resolver_module(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "import pyoco",
                "",
                "def resolve_flow(name: str):",
                "    return pyoco.Flow(name=name)",
                "",
                "not_callable = 1",
            ]
        ),
        encoding="utf-8",
    )


def test_load_flow_resolver_from_file(tmp_path: Path) -> None:
    mod_path = tmp_path / "myresolver.py"
    _write_resolver_module(mod_path)

    resolver = _load_flow_resolver(f"{mod_path}:resolve_flow")
    flow = resolver("main")
    assert flow.name == "main"


def test_load_flow_resolver_from_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod_path = tmp_path / "myresolver.py"
    _write_resolver_module(mod_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    resolver = _load_flow_resolver("myresolver:resolve_flow")
    flow = resolver("train")
    assert flow.name == "train"


def test_load_flow_resolver_validation(tmp_path: Path) -> None:
    mod_path = tmp_path / "myresolver.py"
    _write_resolver_module(mod_path)

    with pytest.raises(ValueError):
        _load_flow_resolver("invalid")
    with pytest.raises(ValueError):
        _load_flow_resolver(f"{mod_path}:not_callable")


def test_yaml_only_resolver_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        _yaml_only_resolver("missing")


def test_worker_cli_invalid_resolver_message(capsys: pytest.CaptureFixture[str]) -> None:
    rc = worker_cli.main(["--flow-resolver", "invalid"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERR-PYOCO-0018" in err
    assert "--flow-resolver must be module:function or file.py:function" in err


def test_worker_cli_parser_error_returns_one(capsys: pytest.CaptureFixture[str]) -> None:
    rc = worker_cli.main(["--unknown-option"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ERR-PYOCO-0018" in err
