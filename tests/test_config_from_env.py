import os

from pyoco_server import NatsBackendConfig


def test_from_env_defaults_when_unset(monkeypatch):
    # Ensure the test does not inherit env from the running session.
    for k in list(os.environ.keys()):
        if k.startswith("PYOCO_"):
            monkeypatch.delenv(k, raising=False)

    assert NatsBackendConfig.from_env() == NatsBackendConfig()


def test_from_env_parses_values_and_falls_back_on_invalid(monkeypatch):
    # Valid values
    monkeypatch.setenv("PYOCO_NATS_URL", "nats://example:4222")
    monkeypatch.setenv("PYOCO_RUNS_KV_BUCKET", "runs_test")
    monkeypatch.setenv("PYOCO_WORKERS_KV_BUCKET", "workers_test")
    monkeypatch.setenv("PYOCO_WORKERS_KV_TTL_SEC", "12.5")
    monkeypatch.setenv("PYOCO_CONSUMER_MAX_DELIVER", "7")
    monkeypatch.setenv("PYOCO_DLQ_PUBLISH_EXECUTION_ERROR", "0")
    monkeypatch.setenv("PYOCO_HTTP_AUTH_MODE", "api_key")
    monkeypatch.setenv("PYOCO_HTTP_API_KEY_HEADER", "X-API-Key")
    monkeypatch.setenv("PYOCO_AUTH_KV_BUCKET", "auth_test")
    monkeypatch.setenv("PYOCO_AUTH_PEPPER", "pepper")
    monkeypatch.setenv("PYOCO_WORKFLOW_YAML_MAX_BYTES", "12345")

    cfg = NatsBackendConfig.from_env()
    assert cfg.nats_url == "nats://example:4222"
    assert cfg.runs_kv_bucket == "runs_test"
    assert cfg.workers_kv_bucket == "workers_test"
    assert cfg.workers_kv_ttl_sec == 12.5
    assert cfg.consumer_max_deliver == 7
    assert cfg.dlq_publish_execution_error is False
    assert cfg.http_auth_mode == "api_key"
    assert cfg.http_api_key_header == "X-API-Key"
    assert cfg.auth_kv_bucket == "auth_test"
    assert cfg.auth_pepper == "pepper"
    assert cfg.workflow_yaml_max_bytes == 12345

    # Invalid values -> defaults
    monkeypatch.setenv("PYOCO_WORKERS_KV_TTL_SEC", "not-a-float")
    monkeypatch.setenv("PYOCO_DLQ_PUBLISH_EXECUTION_ERROR", "maybe")
    monkeypatch.setenv("PYOCO_CONSUMER_MAX_DELIVER", "not-an-int")
    monkeypatch.setenv("PYOCO_WORKFLOW_YAML_MAX_BYTES", "not-an-int")
    cfg2 = NatsBackendConfig.from_env()
    assert cfg2.workers_kv_ttl_sec == NatsBackendConfig.workers_kv_ttl_sec
    assert cfg2.dlq_publish_execution_error == NatsBackendConfig.dlq_publish_execution_error
    assert cfg2.consumer_max_deliver == NatsBackendConfig.consumer_max_deliver
    assert cfg2.workflow_yaml_max_bytes == NatsBackendConfig.workflow_yaml_max_bytes


def test_from_env_auth_pepper_empty_becomes_none(monkeypatch):
    monkeypatch.setenv("PYOCO_AUTH_PEPPER", "")
    assert NatsBackendConfig.from_env().auth_pepper is None
