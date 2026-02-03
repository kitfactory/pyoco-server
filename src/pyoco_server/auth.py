from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Optional, Tuple


API_KEY_PREFIX = "pyoco_"
API_KEY_SEPARATOR = "."

DEFAULT_PBKDF2_ITERATIONS = 200_000
DEFAULT_SALT_BYTES = 16
DEFAULT_SECRET_BYTES = 32

_RE_TENANT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RE_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_RE_SECRET = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


class ApiKeyError(ValueError):
    """
    API key validation error.
    API key の検証エラー。
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode_nopad(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


@dataclass(frozen=True)
class ApiKeyRecord:
    """
    Stored API key record (hash + metadata).
    保存されるAPI keyレコード（ハッシュ + メタデータ）。
    """

    key_id: str
    tenant_id: str
    kdf: str
    iterations: int
    salt_b64: str
    hash_b64: str
    created_at: float
    revoked_at: Optional[float] = None

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def to_json_bytes(self) -> bytes:
        return json.dumps(
            {
                "key_id": self.key_id,
                "tenant_id": self.tenant_id,
                "kdf": self.kdf,
                "iterations": int(self.iterations),
                "salt_b64": self.salt_b64,
                "hash_b64": self.hash_b64,
                "created_at": float(self.created_at),
                "revoked_at": (float(self.revoked_at) if self.revoked_at is not None else None),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "ApiKeyRecord":
        data = json.loads(raw.decode("utf-8"))
        return cls(
            key_id=str(data["key_id"]),
            tenant_id=str(data["tenant_id"]),
            kdf=str(data.get("kdf") or "pbkdf2_hmac_sha256"),
            iterations=int(data.get("iterations") or DEFAULT_PBKDF2_ITERATIONS),
            salt_b64=str(data["salt_b64"]),
            hash_b64=str(data["hash_b64"]),
            created_at=float(data.get("created_at") or 0.0),
            revoked_at=(float(data["revoked_at"]) if data.get("revoked_at") is not None else None),
        )


def make_kv_key_for_api_key_id(key_id: str) -> str:
    # NATS KV keys are subject-like. Keep it token-safe.
    # NATS KV の key は subject 風なので、安全なトークンに限定する。
    return f"api_keys.{key_id}"


def parse_api_key(api_key: str) -> Tuple[str, str]:
    """
    Parse `pyoco_<key_id>.<secret>` into (key_id, secret).
    `pyoco_<key_id>.<secret>` を (key_id, secret) に分解する。
    """

    if api_key is None or api_key == "":
        raise ApiKeyError("missing", "api key is required")
    if not api_key.startswith(API_KEY_PREFIX):
        raise ApiKeyError("invalid_format", "invalid api key format")
    if API_KEY_SEPARATOR not in api_key:
        raise ApiKeyError("invalid_format", "invalid api key format")
    prefix, secret = api_key.split(API_KEY_SEPARATOR, 1)
    key_id = prefix[len(API_KEY_PREFIX) :]
    if not _RE_KEY_ID.match(key_id) or not _RE_SECRET.match(secret):
        raise ApiKeyError("invalid_format", "invalid api key format")
    return key_id, secret


def _derive_hash(
    secret: str,
    *,
    salt: bytes,
    iterations: int,
    pepper: Optional[str],
) -> bytes:
    password = (secret + (pepper or "")).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", password, salt, int(iterations), dklen=32)


def generate_api_key(
    *,
    tenant_id: str,
    now: Optional[float] = None,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
    pepper: Optional[str] = None,
) -> Tuple[str, ApiKeyRecord]:
    """
    Generate an API key and the corresponding record to store.
    API key と保存用レコードを生成する（平文キーは保存しない）。
    """

    if not _RE_TENANT_ID.match(tenant_id or ""):
        raise ValueError("invalid tenant_id (expected [A-Za-z0-9_-]{1,64})")
    now_f = float(time.time() if now is None else now)

    # key_id: short token used to look up the record in KV.
    # key_id：KV でレコードを引くための短いトークン。
    #
    # Must be CLI-friendly too. Avoid leading '-' which can be mis-parsed by argparse.
    # CLIでも扱いやすいことが重要。先頭が '-' だと argparse に誤解され得るので避ける。
    key_id = secrets.token_hex(12)  # 24 chars, [0-9a-f], never starts with '-'
    if not _RE_KEY_ID.match(key_id):
        key_id = secrets.token_hex(16)

    secret = _b64url_nopad(secrets.token_bytes(DEFAULT_SECRET_BYTES))
    if not _RE_SECRET.match(secret):
        # Defensive fallback; base64url should satisfy.
        # 念のためのフォールバック（通常はbase64urlで満たす）。
        secret = secrets.token_urlsafe(32).replace(".", "_")

    salt = secrets.token_bytes(DEFAULT_SALT_BYTES)
    derived = _derive_hash(secret, salt=salt, iterations=iterations, pepper=pepper)

    record = ApiKeyRecord(
        key_id=key_id,
        tenant_id=tenant_id,
        kdf="pbkdf2_hmac_sha256",
        iterations=int(iterations),
        salt_b64=_b64url_nopad(salt),
        hash_b64=_b64url_nopad(derived),
        created_at=now_f,
        revoked_at=None,
    )
    return f"{API_KEY_PREFIX}{key_id}{API_KEY_SEPARATOR}{secret}", record


def verify_api_key(
    api_key: str,
    *,
    record: ApiKeyRecord,
    pepper: Optional[str],
) -> bool:
    """
    Verify a presented api key against a stored record.
    提示されたAPI keyを保存レコードに対して検証する。
    """

    if record.is_revoked():
        return False
    key_id, secret = parse_api_key(api_key)
    if key_id != record.key_id:
        return False
    salt = _b64url_decode_nopad(record.salt_b64)
    expected = _b64url_decode_nopad(record.hash_b64)
    actual = _derive_hash(secret, salt=salt, iterations=record.iterations, pepper=pepper)
    return hmac.compare_digest(actual, expected)
