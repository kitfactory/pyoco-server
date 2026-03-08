from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class BundleTaskConfig:
    """
    bundle 内 task 定義。通常 task と spawn task を同じ器で扱います。
    Unified task config for normal and spawn tasks in workflow bundles.
    """

    callable: Optional[str] = None
    spawn: Optional[str] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)

    @property
    def is_spawn(self) -> bool:
        return bool(self.spawn)


@dataclass(frozen=True)
class BundleWorkflowConfig:
    name: str
    flow: FlowConfig
    tasks: Dict[str, BundleTaskConfig]
    runtime: RuntimeConfig
    reachable_task_names: tuple[str, ...]
    reachable_spawn_task_names: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowBundleSubmit:
    entry_workflow: str
    inputs: Dict[str, Any]


@dataclass(frozen=True)
class ParsedWorkflowBundle:
    version: int
    workflows: Dict[str, BundleWorkflowConfig]
    submit: WorkflowBundleSubmit
    sha256: str
    size_bytes: int
    approval_required: bool


class WorkflowYamlValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_ALLOWED_TOP_LEVEL_KEYS = {"version", "flow", "tasks", "runtime"}
_ALLOWED_FLOW_KEYS = {"graph", "defaults"}
_ALLOWED_TASK_KEYS = {"callable", "inputs", "outputs"}
_ALLOWED_BUNDLE_TASK_KEYS = {"callable", "inputs", "outputs", "spawn"}
_ALLOWED_RUNTIME_KEYS = {"expose_env"}
_ALLOWED_BUNDLE_TOP_LEVEL_KEYS = {"version", "workflows", "submit"}
_ALLOWED_BUNDLE_WORKFLOW_KEYS = {"tasks", "flow", "runtime"}
_ALLOWED_BUNDLE_SUBMIT_KEYS = {"entry_workflow", "inputs"}


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


def parse_workflow_bundle_bytes(raw: bytes) -> ParsedWorkflowBundle:
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

    unknown_top = set(data.keys()) - _ALLOWED_BUNDLE_TOP_LEVEL_KEYS
    if unknown_top:
        raise WorkflowYamlValidationError(f"unknown_bundle_top_level_keys: {sorted(unknown_top)}")

    workflows_data = data.get("workflows")
    if not isinstance(workflows_data, dict) or not workflows_data:
        raise WorkflowYamlValidationError("invalid_bundle_workflows")

    workflows: Dict[str, BundleWorkflowConfig] = {}
    for workflow_name, workflow_conf in workflows_data.items():
        if not isinstance(workflow_name, str) or not workflow_name.strip():
            raise WorkflowYamlValidationError("invalid_workflow_name")
        if workflow_name in workflows:
            raise WorkflowYamlValidationError(f"duplicate_workflow_name: {workflow_name}")
        workflows[workflow_name] = _parse_bundle_workflow_config(workflow_name, workflow_conf)

    submit_data = data.get("submit")
    if not isinstance(submit_data, dict):
        raise WorkflowYamlValidationError("invalid_bundle_submit")
    unknown_submit = set(submit_data.keys()) - _ALLOWED_BUNDLE_SUBMIT_KEYS
    if unknown_submit:
        raise WorkflowYamlValidationError(f"unknown_bundle_submit_keys: {sorted(unknown_submit)}")

    entry_workflow = submit_data.get("entry_workflow")
    if not isinstance(entry_workflow, str) or not entry_workflow.strip():
        raise WorkflowYamlValidationError("invalid_entry_workflow")
    if entry_workflow not in workflows:
        raise WorkflowYamlValidationError(f"missing_entry_workflow: {entry_workflow}")

    submit_inputs = submit_data.get("inputs") or {}
    if not isinstance(submit_inputs, dict):
        raise WorkflowYamlValidationError("invalid_bundle_submit_inputs")
    submit = WorkflowBundleSubmit(entry_workflow=entry_workflow, inputs=dict(submit_inputs))

    for workflow_name, workflow in workflows.items():
        for task_name, task_conf in workflow.tasks.items():
            if task_conf.spawn and task_conf.spawn not in workflows:
                raise WorkflowYamlValidationError(
                    f"unknown_spawn_target: {workflow_name}.{task_name}: {task_conf.spawn}"
                )

    version = data.get("version", 1)
    try:
        version_i = int(version)
    except Exception as exc:
        raise WorkflowYamlValidationError("invalid_version") from exc

    approval_required = bool(workflows[entry_workflow].reachable_spawn_task_names)
    return ParsedWorkflowBundle(
        version=version_i,
        workflows=workflows,
        submit=submit,
        sha256=sha256,
        size_bytes=size,
        approval_required=approval_required,
    )


def extract_flow_defaults(parsed: ParsedWorkflowYaml) -> Dict[str, Any]:
    flow: Optional[FlowConfig] = parsed.config.flow
    if flow is None:
        return {}
    return dict(flow.defaults or {})


def _parse_bundle_workflow_config(name: str, raw: Any) -> BundleWorkflowConfig:
    if not isinstance(raw, dict):
        raise WorkflowYamlValidationError(f"invalid_bundle_workflow: {name}")

    unknown_workflow = set(raw.keys()) - _ALLOWED_BUNDLE_WORKFLOW_KEYS
    if unknown_workflow:
        raise WorkflowYamlValidationError(f"unknown_bundle_workflow_keys: {name}: {sorted(unknown_workflow)}")

    flow_data = raw.get("flow")
    if not isinstance(flow_data, dict):
        raise WorkflowYamlValidationError(f"invalid_bundle_flow: {name}")
    unknown_flow = set(flow_data.keys()) - _ALLOWED_FLOW_KEYS
    if unknown_flow:
        raise WorkflowYamlValidationError(f"unknown_flow_keys: {name}: {sorted(unknown_flow)}")
    graph = flow_data.get("graph")
    if not isinstance(graph, str) or not graph.strip():
        raise WorkflowYamlValidationError(f"missing_flow_graph: {name}")
    defaults = flow_data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise WorkflowYamlValidationError(f"invalid_flow_defaults: {name}")
    flow = FlowConfig(graph=graph, defaults=dict(defaults))

    tasks_data = raw.get("tasks") or {}
    if not isinstance(tasks_data, dict):
        raise WorkflowYamlValidationError(f"invalid_tasks: {name}")
    tasks: Dict[str, BundleTaskConfig] = {}
    for task_name, task_raw in tasks_data.items():
        tasks[task_name] = _parse_bundle_task_config(workflow_name=name, task_name=task_name, raw=task_raw)

    runtime_data = raw.get("runtime") or {}
    if not isinstance(runtime_data, dict):
        raise WorkflowYamlValidationError(f"invalid_runtime: {name}")
    unknown_runtime = set(runtime_data.keys()) - _ALLOWED_RUNTIME_KEYS
    if unknown_runtime:
        raise WorkflowYamlValidationError(f"unknown_runtime_keys: {name}: {sorted(unknown_runtime)}")
    expose_env = runtime_data.get("expose_env") or []
    if not isinstance(expose_env, list) or any(not isinstance(x, str) for x in expose_env):
        raise WorkflowYamlValidationError(f"invalid_runtime_expose_env: {name}")
    runtime = RuntimeConfig(expose_env=expose_env)

    reachable_task_names = tuple(sorted(_collect_graph_task_names(graph, tasks.keys())))
    reachable_spawn_task_names = tuple(
        sorted(task_name for task_name in reachable_task_names if tasks[task_name].is_spawn)
    )
    return BundleWorkflowConfig(
        name=name,
        flow=flow,
        tasks=tasks,
        runtime=runtime,
        reachable_task_names=reachable_task_names,
        reachable_spawn_task_names=reachable_spawn_task_names,
    )


def _parse_bundle_task_config(*, workflow_name: str, task_name: Any, raw: Any) -> BundleTaskConfig:
    if not isinstance(task_name, str) or not task_name.strip():
        raise WorkflowYamlValidationError(f"invalid_task_name: {workflow_name}")
    if not isinstance(raw, dict):
        raise WorkflowYamlValidationError(f"invalid_task_config: {workflow_name}.{task_name}")

    unknown_task = set(raw.keys()) - _ALLOWED_BUNDLE_TASK_KEYS
    if unknown_task:
        raise WorkflowYamlValidationError(
            f"unknown_task_keys: {workflow_name}.{task_name}: {sorted(unknown_task)}"
        )

    callable_path = raw.get("callable")
    spawn_target = raw.get("spawn")
    if bool(callable_path) == bool(spawn_target):
        raise WorkflowYamlValidationError(f"invalid_task_kind: {workflow_name}.{task_name}")

    if callable_path is not None and (not isinstance(callable_path, str) or ":" not in callable_path):
        raise WorkflowYamlValidationError(f"invalid_task_callable: {workflow_name}.{task_name}")
    if spawn_target is not None and (not isinstance(spawn_target, str) or not spawn_target.strip()):
        raise WorkflowYamlValidationError(f"invalid_task_spawn: {workflow_name}.{task_name}")

    inputs = raw.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise WorkflowYamlValidationError(f"invalid_task_inputs: {workflow_name}.{task_name}")
    outputs = raw.get("outputs") or []
    if not isinstance(outputs, list) or any(not isinstance(x, str) for x in outputs):
        raise WorkflowYamlValidationError(f"invalid_task_outputs: {workflow_name}.{task_name}")
    return BundleTaskConfig(
        callable=callable_path,
        spawn=spawn_target,
        inputs=dict(inputs),
        outputs=list(outputs),
    )


def _collect_graph_task_names(graph: str, task_names: Any) -> set[str]:
    try:
        root = ast.parse(graph)
    except SyntaxError as exc:
        raise WorkflowYamlValidationError("invalid_flow_graph_syntax") from exc
    valid_names = set(str(name) for name in task_names)
    used: set[str] = set()
    for node in ast.walk(root):
        if isinstance(node, ast.Name) and node.id in valid_names:
            used.add(node.id)
    return used
