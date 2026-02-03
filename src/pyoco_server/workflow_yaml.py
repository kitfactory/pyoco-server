from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

import yaml
from pyoco.schemas.config import FlowConfig, PyocoConfig, RuntimeConfig, TaskConfig


@dataclass(frozen=True)
class ParsedWorkflowYaml:
    """
    flow.yaml の最小パース結果（HTTP Gateway / worker 共通）。
    Minimal parsed representation of a flow.yaml for both HTTP gateway and workers.
    """

    config: PyocoConfig
    sha256: str
    size_bytes: int


class WorkflowYamlValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_ALLOWED_TOP_LEVEL_KEYS = {"version", "flow", "tasks", "runtime"}
_ALLOWED_FLOW_KEYS = {"graph", "defaults"}
_ALLOWED_TASK_KEYS = {"callable", "inputs", "outputs"}
_ALLOWED_RUNTIME_KEYS = {"expose_env"}


def parse_workflow_yaml_bytes(raw: bytes, *, require_flow: bool = True) -> ParsedWorkflowYaml:
    if not isinstance(raw, (bytes, bytearray)):
        raise WorkflowYamlValidationError("invalid_bytes")

    size = len(raw)
    sha256 = hashlib.sha256(raw).hexdigest()

    try:
        text = raw.decode("utf-8")
    except Exception as exc:
        raise WorkflowYamlValidationError("invalid_utf8") from exc

    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise WorkflowYamlValidationError("invalid_yaml") from exc

    if not isinstance(data, dict):
        raise WorkflowYamlValidationError("invalid_yaml_root")

    # Backward-compat/safety: flows/discovery は明示的に禁止（pyoco 0.6.0+）。
    if "flows" in data:
        raise WorkflowYamlValidationError("unsupported_key_flows")
    if "discovery" in data:
        raise WorkflowYamlValidationError("unsupported_key_discovery")

    # Strict key set: 「不明キー何でもOK」を許さない。
    unknown_top = set(data.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown_top:
        raise WorkflowYamlValidationError(f"unknown_top_level_keys: {sorted(unknown_top)}")

    flow_data = data.get("flow")
    if flow_data is None:
        if require_flow:
            raise WorkflowYamlValidationError("missing_flow")
        flow = None
    else:
        if not isinstance(flow_data, dict):
            raise WorkflowYamlValidationError("invalid_flow")
        unknown_flow = set(flow_data.keys()) - _ALLOWED_FLOW_KEYS
        if unknown_flow:
            raise WorkflowYamlValidationError(f"unknown_flow_keys: {sorted(unknown_flow)}")
        graph = flow_data.get("graph")
        if not isinstance(graph, str) or not graph.strip():
            raise WorkflowYamlValidationError("missing_flow_graph")
        defaults = flow_data.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise WorkflowYamlValidationError("invalid_flow_defaults")
        flow = FlowConfig(graph=graph, defaults=defaults)

    tasks_data = data.get("tasks") or {}
    if not isinstance(tasks_data, dict):
        raise WorkflowYamlValidationError("invalid_tasks")
    tasks: Dict[str, TaskConfig] = {}
    for name, conf in tasks_data.items():
        if not isinstance(name, str) or not name.strip():
            raise WorkflowYamlValidationError("invalid_task_name")
        if not isinstance(conf, dict):
            raise WorkflowYamlValidationError(f"invalid_task_config: {name}")
        unknown_task = set(conf.keys()) - _ALLOWED_TASK_KEYS
        if unknown_task:
            raise WorkflowYamlValidationError(f"unknown_task_keys: {name}: {sorted(unknown_task)}")
        callable_path = conf.get("callable")
        if callable_path is not None and (not isinstance(callable_path, str) or ":" not in callable_path):
            raise WorkflowYamlValidationError(f"invalid_task_callable: {name}")
        inputs = conf.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise WorkflowYamlValidationError(f"invalid_task_inputs: {name}")
        outputs = conf.get("outputs") or []
        if not isinstance(outputs, list) or any(not isinstance(x, str) for x in outputs):
            raise WorkflowYamlValidationError(f"invalid_task_outputs: {name}")
        tasks[name] = TaskConfig(callable=callable_path, inputs=inputs, outputs=outputs)

    runtime_data = data.get("runtime") or {}
    if not isinstance(runtime_data, dict):
        raise WorkflowYamlValidationError("invalid_runtime")
    unknown_runtime = set(runtime_data.keys()) - _ALLOWED_RUNTIME_KEYS
    if unknown_runtime:
        raise WorkflowYamlValidationError(f"unknown_runtime_keys: {sorted(unknown_runtime)}")
    expose_env = runtime_data.get("expose_env") or []
    if not isinstance(expose_env, list) or any(not isinstance(x, str) for x in expose_env):
        raise WorkflowYamlValidationError("invalid_runtime_expose_env")
    runtime = RuntimeConfig(expose_env=expose_env)

    version = data.get("version", 1)
    try:
        version_i = int(version)
    except Exception as exc:
        raise WorkflowYamlValidationError("invalid_version") from exc

    cfg = PyocoConfig(version=version_i, flow=flow, tasks=tasks, runtime=runtime)
    return ParsedWorkflowYaml(config=cfg, sha256=sha256, size_bytes=size)


def extract_flow_defaults(parsed: ParsedWorkflowYaml) -> Dict[str, Any]:
    flow: Optional[FlowConfig] = parsed.config.flow
    if flow is None:
        return {}
    return dict(flow.defaults or {})
