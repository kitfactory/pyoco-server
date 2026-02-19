from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Optional


_DOTENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    raw = str(line).strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.startswith("export "):
        raw = raw[7:].strip()
    if "=" not in raw:
        return None
    key, value = raw.split("=", 1)
    key = key.strip()
    if not _DOTENV_KEY_RE.fullmatch(key):
        return None
    value = value.strip()
    if value and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        body = value[1:-1]
        if quote == '"':
            try:
                body = bytes(body, encoding="utf-8").decode("unicode_escape")
            except Exception:
                pass
        return key, body
    # Inline comments are treated as comments only when preceded by whitespace.
    # 空白の後ろにある # のみをコメント扱いにします。
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    return key, value


def _read_dotenv_values() -> dict[str, str]:
    raw_enabled = str(os.environ.get("PYOCO_LOAD_DOTENV", "1")).strip().lower()
    if raw_enabled in {"0", "false", "no", "off"}:
        return {}

    env_file = str(os.environ.get("PYOCO_ENV_FILE", ".env")).strip()
    if not env_file:
        return {}

    path = Path(env_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    out: dict[str, str] = {}
    for line in text.splitlines():
        parsed = _parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        out[key] = value
    return out


@dataclass(frozen=True)
class NatsBackendConfig:
    """
    Opinionated defaults for a single-queue deployment.
    """

    nats_url: str = "nats://127.0.0.1:4222"

    # Work queue (JetStream stream + subject)
    work_stream: str = "PYOCO_WORK"
    # Tags are expressed as NATS subjects: "<work_subject_prefix>.<tag>"
    work_subject_prefix: str = "pyoco.work"
    default_tag: str = "default"
    consumer_prefix: str = "pyoco_workers"

    # Latest run status (JetStream KV)
    runs_kv_bucket: str = "pyoco_runs"

    # Worker liveness (JetStream KV with TTL)
    workers_kv_bucket: str = "pyoco_workers"
    workers_kv_ttl_sec: float = 15.0

    # HTTP auth (opt-in)
    # - "none": allow all requests (MVP / trust boundary outside)
    # - "api_key": require X-API-Key for /runs* endpoints
    http_auth_mode: str = "none"
    http_api_key_header: str = "X-API-Key"
    auth_kv_bucket: str = "pyoco_auth"
    auth_pepper: Optional[str] = None

    # Heartbeat intervals (best-effort)
    run_heartbeat_interval_sec: float = 1.0
    worker_heartbeat_interval_sec: float = 5.0
    # Worker registry disconnect interpretation timeout.
    worker_disconnect_timeout_sec: float = 20.0
    # Cancel request grace period (best-effort). Worker may log timeout after this.
    cancel_grace_period_sec: float = 30.0

    # JetStream ACK progress interval for long-running runs.
    # Worker periodically sends "in progress" ACK to avoid redelivery while still processing.
    ack_progress_interval_sec: float = 10.0

    # JetStream consumer defaults (per-tag durable consumers).
    # These values are intentionally conservative and can be overridden per environment.
    consumer_ack_wait_sec: float = 30.0
    # Delivery cap is mainly a safety net for stuck/crashing workers.
    # Keep it high enough to tolerate transient outages.
    consumer_max_deliver: int = 20
    consumer_max_ack_pending: int = 200

    # DLQ (optional but recommended for diagnostics)
    dlq_stream: str = "PYOCO_DLQ"
    dlq_subject_prefix: str = "pyoco.dlq"
    dlq_max_age_sec: float = 7 * 24 * 60 * 60  # 7 days
    dlq_max_msgs: int = 100_000
    dlq_max_bytes: int = 512 * 1024 * 1024  # 512 MiB
    dlq_publish_execution_error: bool = True

    # KV snapshot size guard (JetStream has max payload limits; keep snapshots bounded).
    # If the serialized snapshot exceeds this size, the worker may drop `task_records`.
    max_run_snapshot_bytes: int = 256 * 1024  # 256 KiB

    # Wheel registry (JetStream Object Store + worker sync/install).
    wheel_object_store_bucket: str = "pyoco_wheels"
    wheel_sync_enabled: bool = False
    wheel_sync_dir: str = ".pyoco/wheels"
    wheel_sync_interval_sec: float = 10.0
    wheel_install_timeout_sec: float = 180.0
    wheel_max_bytes: int = 512 * 1024 * 1024  # 512 MiB
    wheel_history_kv_bucket: str = "pyoco_wheel_history"
    wheel_history_ttl_sec: float = 90 * 24 * 60 * 60  # 90 days

    # flow.yaml (YAML) submission policy (Phase 4)
    # flow.yaml は JetStream の1メッセージとして投入するため、サイズ上限を設ける。
    # Since flow.yaml is carried inside a single JetStream message, keep it bounded.
    workflow_yaml_max_bytes: int = 256 * 1024  # 256 KiB

    # Dashboard locale policy:
    # - "auto": derive from server locale.
    # - "ja" / "en": force locale for all dashboard users.
    dashboard_lang: str = "auto"

    @classmethod
    def from_env(cls) -> "NatsBackendConfig":
        """
        環境変数から設定を読み込みます（docs/spec.md 付録I）。
        Load config from env vars defined in docs/spec.md (Appendix I).

        env の解釈を1箇所に集約し、HTTP gateway / worker が同じ仕組みで設定できるようにします。
        Centralize env parsing so both HTTP gateway and workers use the same mechanism.
        """

        dotenv_values = _read_dotenv_values()

        def _env_raw(name: str, default: Optional[str] = None) -> Optional[str]:
            raw = os.environ.get(name)
            if raw is None or raw == "":
                raw = dotenv_values.get(name)
            if raw is None or raw == "":
                return default
            return raw

        def _env_float(name: str, default: float) -> float:
            raw = _env_raw(name)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def _env_bool(name: str, default: bool) -> bool:
            raw = _env_raw(name)
            if raw is None:
                return default
            v = raw.strip().lower()
            if v in {"1", "true", "yes", "on"}:
                return True
            if v in {"0", "false", "no", "off"}:
                return False
            return default

        def _env_int(name: str, default: int) -> int:
            raw = _env_raw(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        auth_pepper = _env_raw("PYOCO_AUTH_PEPPER")

        return cls(
            nats_url=_env_raw("PYOCO_NATS_URL", cls.nats_url) or cls.nats_url,
            runs_kv_bucket=_env_raw("PYOCO_RUNS_KV_BUCKET", cls.runs_kv_bucket) or cls.runs_kv_bucket,
            workers_kv_bucket=_env_raw("PYOCO_WORKERS_KV_BUCKET", cls.workers_kv_bucket)
            or cls.workers_kv_bucket,
            work_subject_prefix=_env_raw("PYOCO_WORK_SUBJECT_PREFIX", cls.work_subject_prefix)
            or cls.work_subject_prefix,
            default_tag=_env_raw("PYOCO_DEFAULT_TAG", cls.default_tag) or cls.default_tag,
            workers_kv_ttl_sec=_env_float("PYOCO_WORKERS_KV_TTL_SEC", cls.workers_kv_ttl_sec),
            http_auth_mode=_env_raw("PYOCO_HTTP_AUTH_MODE", cls.http_auth_mode) or cls.http_auth_mode,
            http_api_key_header=_env_raw("PYOCO_HTTP_API_KEY_HEADER", cls.http_api_key_header)
            or cls.http_api_key_header,
            auth_kv_bucket=_env_raw("PYOCO_AUTH_KV_BUCKET", cls.auth_kv_bucket) or cls.auth_kv_bucket,
            auth_pepper=(auth_pepper if auth_pepper is not None and str(auth_pepper).strip() != "" else None),
            run_heartbeat_interval_sec=_env_float(
                "PYOCO_RUN_HEARTBEAT_INTERVAL_SEC", cls.run_heartbeat_interval_sec
            ),
            worker_heartbeat_interval_sec=_env_float(
                "PYOCO_WORKER_HEARTBEAT_INTERVAL_SEC", cls.worker_heartbeat_interval_sec
            ),
            worker_disconnect_timeout_sec=_env_float(
                "PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC", cls.worker_disconnect_timeout_sec
            ),
            cancel_grace_period_sec=_env_float(
                "PYOCO_CANCEL_GRACE_PERIOD_SEC", cls.cancel_grace_period_sec
            ),
            ack_progress_interval_sec=_env_float(
                "PYOCO_ACK_PROGRESS_INTERVAL_SEC", cls.ack_progress_interval_sec
            ),
            consumer_ack_wait_sec=_env_float("PYOCO_CONSUMER_ACK_WAIT_SEC", cls.consumer_ack_wait_sec),
            consumer_max_deliver=_env_int("PYOCO_CONSUMER_MAX_DELIVER", cls.consumer_max_deliver),
            consumer_max_ack_pending=_env_int("PYOCO_CONSUMER_MAX_ACK_PENDING", cls.consumer_max_ack_pending),
            dlq_stream=_env_raw("PYOCO_DLQ_STREAM", cls.dlq_stream) or cls.dlq_stream,
            dlq_subject_prefix=_env_raw("PYOCO_DLQ_SUBJECT_PREFIX", cls.dlq_subject_prefix)
            or cls.dlq_subject_prefix,
            dlq_max_age_sec=_env_float("PYOCO_DLQ_MAX_AGE_SEC", cls.dlq_max_age_sec),
            dlq_max_msgs=_env_int("PYOCO_DLQ_MAX_MSGS", cls.dlq_max_msgs),
            dlq_max_bytes=_env_int("PYOCO_DLQ_MAX_BYTES", cls.dlq_max_bytes),
            dlq_publish_execution_error=_env_bool(
                "PYOCO_DLQ_PUBLISH_EXECUTION_ERROR", cls.dlq_publish_execution_error
            ),
            max_run_snapshot_bytes=_env_int("PYOCO_MAX_RUN_SNAPSHOT_BYTES", cls.max_run_snapshot_bytes),
            wheel_object_store_bucket=_env_raw(
                "PYOCO_WHEEL_OBJECT_STORE_BUCKET", cls.wheel_object_store_bucket
            )
            or cls.wheel_object_store_bucket,
            wheel_sync_enabled=_env_bool("PYOCO_WHEEL_SYNC_ENABLED", cls.wheel_sync_enabled),
            wheel_sync_dir=_env_raw("PYOCO_WHEEL_SYNC_DIR", cls.wheel_sync_dir) or cls.wheel_sync_dir,
            wheel_sync_interval_sec=_env_float(
                "PYOCO_WHEEL_SYNC_INTERVAL_SEC", cls.wheel_sync_interval_sec
            ),
            wheel_install_timeout_sec=_env_float(
                "PYOCO_WHEEL_INSTALL_TIMEOUT_SEC", cls.wheel_install_timeout_sec
            ),
            wheel_max_bytes=_env_int("PYOCO_WHEEL_MAX_BYTES", cls.wheel_max_bytes),
            wheel_history_kv_bucket=_env_raw(
                "PYOCO_WHEEL_HISTORY_KV_BUCKET", cls.wheel_history_kv_bucket
            )
            or cls.wheel_history_kv_bucket,
            wheel_history_ttl_sec=_env_float(
                "PYOCO_WHEEL_HISTORY_TTL_SEC", cls.wheel_history_ttl_sec
            ),
            workflow_yaml_max_bytes=_env_int(
                "PYOCO_WORKFLOW_YAML_MAX_BYTES", cls.workflow_yaml_max_bytes
            ),
            dashboard_lang=_env_raw("PYOCO_DASHBOARD_LANG", cls.dashboard_lang) or cls.dashboard_lang,
        )
