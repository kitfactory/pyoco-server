import os
from pathlib import Path

from pyoco_server import NatsBackendConfig


def test_from_env_defaults_when_unset(monkeypatch):
    # Ensure the test does not inherit env from the running session.
    for k in list(os.environ.keys()):
        if k.startswith("PYOCO_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "0")

    assert NatsBackendConfig.from_env() == NatsBackendConfig()


def test_from_env_parses_values_and_falls_back_on_invalid(monkeypatch):
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "0")
    # Valid values
    monkeypatch.setenv("PYOCO_NATS_URL", "nats://example:4222")
    monkeypatch.setenv("PYOCO_RUNS_KV_BUCKET", "runs_test")
    monkeypatch.setenv("PYOCO_WORKERS_KV_BUCKET", "workers_test")
    monkeypatch.setenv("PYOCO_WORKERS_KV_TTL_SEC", "12.5")
    monkeypatch.setenv("PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC", "34.5")
    monkeypatch.setenv("PYOCO_CANCEL_GRACE_PERIOD_SEC", "45.0")
    monkeypatch.setenv("PYOCO_CONSUMER_MAX_DELIVER", "7")
    monkeypatch.setenv("PYOCO_DLQ_PUBLISH_EXECUTION_ERROR", "0")
    monkeypatch.setenv("PYOCO_HTTP_AUTH_MODE", "api_key")
    monkeypatch.setenv("PYOCO_HTTP_API_KEY_HEADER", "X-API-Key")
    monkeypatch.setenv("PYOCO_AUTH_KV_BUCKET", "auth_test")
    monkeypatch.setenv("PYOCO_AUTH_PEPPER", "pepper")
    monkeypatch.setenv("PYOCO_WORKFLOW_YAML_MAX_BYTES", "12345")
    monkeypatch.setenv("PYOCO_DASHBOARD_LANG", "ja")
    monkeypatch.setenv("PYOCO_WHEEL_OBJECT_STORE_BUCKET", "wheels_test")
    monkeypatch.setenv("PYOCO_WHEEL_SYNC_ENABLED", "1")
    monkeypatch.setenv("PYOCO_WHEEL_SYNC_DIR", "/tmp/wheels")
    monkeypatch.setenv("PYOCO_WHEEL_SYNC_INTERVAL_SEC", "9.5")
    monkeypatch.setenv("PYOCO_WHEEL_INSTALL_TIMEOUT_SEC", "77.0")
    monkeypatch.setenv("PYOCO_WHEEL_MAX_BYTES", "999")
    monkeypatch.setenv("PYOCO_WHEEL_HISTORY_KV_BUCKET", "wheel_history_test")
    monkeypatch.setenv("PYOCO_WHEEL_HISTORY_TTL_SEC", "3600")

    cfg = NatsBackendConfig.from_env()
    assert cfg.nats_url == "nats://example:4222"
    assert cfg.runs_kv_bucket == "runs_test"
    assert cfg.workers_kv_bucket == "workers_test"
    assert cfg.workers_kv_ttl_sec == 12.5
    assert cfg.worker_disconnect_timeout_sec == 34.5
    assert cfg.cancel_grace_period_sec == 45.0
    assert cfg.consumer_max_deliver == 7
    assert cfg.dlq_publish_execution_error is False
    assert cfg.http_auth_mode == "api_key"
    assert cfg.http_api_key_header == "X-API-Key"
    assert cfg.auth_kv_bucket == "auth_test"
    assert cfg.auth_pepper == "pepper"
    assert cfg.workflow_yaml_max_bytes == 12345
    assert cfg.dashboard_lang == "ja"
    assert cfg.wheel_object_store_bucket == "wheels_test"
    assert cfg.wheel_sync_enabled is True
    assert cfg.wheel_sync_dir == "/tmp/wheels"
    assert cfg.wheel_sync_interval_sec == 9.5
    assert cfg.wheel_install_timeout_sec == 77.0
    assert cfg.wheel_max_bytes == 999
    assert cfg.wheel_history_kv_bucket == "wheel_history_test"
    assert cfg.wheel_history_ttl_sec == 3600.0

    # Invalid values -> defaults
    monkeypatch.setenv("PYOCO_WORKERS_KV_TTL_SEC", "not-a-float")
    monkeypatch.setenv("PYOCO_WORKER_DISCONNECT_TIMEOUT_SEC", "nope")
    monkeypatch.setenv("PYOCO_CANCEL_GRACE_PERIOD_SEC", "bad-float")
    monkeypatch.setenv("PYOCO_DLQ_PUBLISH_EXECUTION_ERROR", "maybe")
    monkeypatch.setenv("PYOCO_CONSUMER_MAX_DELIVER", "not-an-int")
    monkeypatch.setenv("PYOCO_WORKFLOW_YAML_MAX_BYTES", "not-an-int")
    monkeypatch.setenv("PYOCO_WHEEL_SYNC_INTERVAL_SEC", "bad-float")
    monkeypatch.setenv("PYOCO_WHEEL_INSTALL_TIMEOUT_SEC", "bad-float")
    monkeypatch.setenv("PYOCO_WHEEL_MAX_BYTES", "bad-int")
    monkeypatch.setenv("PYOCO_WHEEL_HISTORY_TTL_SEC", "bad-float")
    cfg2 = NatsBackendConfig.from_env()
    assert cfg2.workers_kv_ttl_sec == NatsBackendConfig.workers_kv_ttl_sec
    assert cfg2.worker_disconnect_timeout_sec == NatsBackendConfig.worker_disconnect_timeout_sec
    assert cfg2.cancel_grace_period_sec == NatsBackendConfig.cancel_grace_period_sec
    assert cfg2.dlq_publish_execution_error == NatsBackendConfig.dlq_publish_execution_error
    assert cfg2.consumer_max_deliver == NatsBackendConfig.consumer_max_deliver
    assert cfg2.workflow_yaml_max_bytes == NatsBackendConfig.workflow_yaml_max_bytes
    assert cfg2.wheel_sync_interval_sec == NatsBackendConfig.wheel_sync_interval_sec
    assert cfg2.wheel_install_timeout_sec == NatsBackendConfig.wheel_install_timeout_sec
    assert cfg2.wheel_max_bytes == NatsBackendConfig.wheel_max_bytes
    assert cfg2.wheel_history_ttl_sec == NatsBackendConfig.wheel_history_ttl_sec


def test_from_env_auth_pepper_empty_becomes_none(monkeypatch):
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "0")
    monkeypatch.setenv("PYOCO_AUTH_PEPPER", "")
    assert NatsBackendConfig.from_env().auth_pepper is None


def test_from_env_reads_dotenv_when_enabled(monkeypatch, tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "PYOCO_NATS_URL=nats://dotenv:4222",
                "PYOCO_WORKERS_KV_TTL_SEC=11.5",
                "PYOCO_DASHBOARD_LANG=ja",
                "PYOCO_AUTH_PEPPER=dotenv-pepper",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for k in list(os.environ.keys()):
        if k.startswith("PYOCO_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "1")

    cfg = NatsBackendConfig.from_env()
    assert cfg.nats_url == "nats://dotenv:4222"
    assert cfg.workers_kv_ttl_sec == 11.5
    assert cfg.dashboard_lang == "ja"
    assert cfg.auth_pepper == "dotenv-pepper"


def test_from_env_prefers_process_env_over_dotenv(monkeypatch, tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("PYOCO_NATS_URL=nats://dotenv:4222\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "1")
    monkeypatch.setenv("PYOCO_NATS_URL", "nats://env:4222")

    cfg = NatsBackendConfig.from_env()
    assert cfg.nats_url == "nats://env:4222"


def test_from_env_can_disable_dotenv(monkeypatch, tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("PYOCO_NATS_URL=nats://dotenv:4222\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "0")
    monkeypatch.delenv("PYOCO_NATS_URL", raising=False)

    cfg = NatsBackendConfig.from_env()
    assert cfg.nats_url == NatsBackendConfig.nats_url


def test_from_env_can_use_custom_env_file(monkeypatch, tmp_path: Path):
    dotenv = tmp_path / "custom.env"
    dotenv.write_text("PYOCO_DASHBOARD_LANG=en\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYOCO_LOAD_DOTENV", "1")
    monkeypatch.setenv("PYOCO_ENV_FILE", str(dotenv))
    monkeypatch.delenv("PYOCO_DASHBOARD_LANG", raising=False)

    cfg = NatsBackendConfig.from_env()
    assert cfg.dashboard_lang == "en"
