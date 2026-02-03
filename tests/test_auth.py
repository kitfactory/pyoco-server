import pytest

from pyoco_server.auth import ApiKeyError, ApiKeyRecord, generate_api_key, parse_api_key, verify_api_key


def test_generate_and_verify_roundtrip():
    api_key, rec = generate_api_key(tenant_id="demo", now=123.0, pepper="pep")
    key_id, secret = parse_api_key(api_key)
    assert key_id == rec.key_id
    assert secret
    assert rec.tenant_id == "demo"
    assert verify_api_key(api_key, record=rec, pepper="pep") is True
    assert verify_api_key(api_key, record=rec, pepper="wrong") is False


def test_verify_fails_when_revoked():
    api_key, rec = generate_api_key(tenant_id="demo")
    revoked = ApiKeyRecord(
        **{**rec.__dict__, "revoked_at": 999.0},
    )
    assert verify_api_key(api_key, record=revoked, pepper=None) is False


def test_parse_rejects_invalid_format():
    with pytest.raises(ApiKeyError) as e1:
        parse_api_key("")
    assert e1.value.code == "missing"

    with pytest.raises(ApiKeyError) as e2:
        parse_api_key("nope")
    assert e2.value.code == "invalid_format"

    with pytest.raises(ApiKeyError) as e3:
        parse_api_key("pyoco_abc.def")  # key_id too short
    assert e3.value.code == "invalid_format"


def test_generate_rejects_invalid_tenant_id():
    with pytest.raises(ValueError):
        generate_api_key(tenant_id="bad tenant")

