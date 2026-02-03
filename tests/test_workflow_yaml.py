import hashlib

import pytest

from pyoco_server.workflow_yaml import (
    WorkflowYamlValidationError,
    extract_flow_defaults,
    parse_workflow_yaml_bytes,
)


def test_parse_workflow_yaml_bytes_ok_and_extract_defaults():
    raw = b"""\
version: 1
flow:
  graph: |
    add_one >> to_text
  defaults:
    x: 1
tasks:
  add_one:
    callable: pyoco_server._workflow_test_tasks:add_one
  to_text:
    callable: pyoco_server._workflow_test_tasks:to_text
"""

    parsed = parse_workflow_yaml_bytes(raw, require_flow=True)
    assert parsed.size_bytes == len(raw)
    assert parsed.sha256 == hashlib.sha256(raw).hexdigest()
    assert parsed.config.flow is not None
    assert "add_one" in parsed.config.tasks
    assert extract_flow_defaults(parsed) == {"x": 1}


@pytest.mark.parametrize("bad", [b"- just: list\n", b"null\n"])
def test_parse_workflow_yaml_bytes_rejects_non_mapping_root(bad):
    with pytest.raises(WorkflowYamlValidationError) as exc:
        parse_workflow_yaml_bytes(bad, require_flow=True)
    assert exc.value.reason == "invalid_yaml_root"


def test_parse_workflow_yaml_bytes_rejects_unknown_keys():
    raw = b"""\
version: 1
flow:
  graph: "x"
unknown: 1
"""

    with pytest.raises(WorkflowYamlValidationError) as exc:
        parse_workflow_yaml_bytes(raw, require_flow=True)
    assert exc.value.reason.startswith("unknown_top_level_keys")


@pytest.mark.parametrize("key", ["flows", "discovery"])
def test_parse_workflow_yaml_bytes_rejects_forbidden_keys(key: str):
    raw = f"""\
version: 1
flow:
  graph: "x"
{key}: {{}}
""".encode("utf-8")

    with pytest.raises(WorkflowYamlValidationError) as exc:
        parse_workflow_yaml_bytes(raw, require_flow=True)
    assert exc.value.reason in {"unsupported_key_flows", "unsupported_key_discovery"}

