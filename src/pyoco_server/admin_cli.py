from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Optional

import nats
from nats.js.errors import KeyNotFoundError

from .auth import ApiKeyRecord, generate_api_key, make_kv_key_for_api_key_id
from .config import NatsBackendConfig
from .resources import ensure_resources


async def _connect_js(cfg: NatsBackendConfig):
    nc = await nats.connect(cfg.nats_url, name="pyoco-admin-cli")
    js = nc.jetstream()
    await ensure_resources(js, cfg)
    kv = await js.key_value(cfg.auth_kv_bucket)
    return nc, js, kv


def _print_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


async def _api_key_create(cfg: NatsBackendConfig, *, tenant_id: str) -> int:
    nc, _, kv = await _connect_js(cfg)
    try:
        api_key, rec = generate_api_key(tenant_id=tenant_id, pepper=cfg.auth_pepper)
        await kv.put(make_kv_key_for_api_key_id(rec.key_id), rec.to_json_bytes())
        # Plaintext api_key is shown only here.
        # 平文のAPI keyはここでだけ出力する（保存しない）。
        _print_json(
            {
                "key_id": rec.key_id,
                "tenant_id": rec.tenant_id,
                "api_key": api_key,
                "created_at": rec.created_at,
            }
        )
        return 0
    finally:
        await nc.close()


async def _api_key_list(cfg: NatsBackendConfig) -> int:
    nc, _, kv = await _connect_js(cfg)
    try:
        keys = await kv.keys()
        out = []
        for k in list(keys or []):
            try:
                e = await kv.get(k)
            except KeyNotFoundError:
                continue
            try:
                rec = ApiKeyRecord.from_json_bytes(e.value)
            except Exception:
                continue
            out.append(
                {
                    "key_id": rec.key_id,
                    "tenant_id": rec.tenant_id,
                    "created_at": rec.created_at,
                    "revoked_at": rec.revoked_at,
                }
            )
        out.sort(key=lambda r: float(r.get("created_at") or 0.0), reverse=True)
        _print_json(out)
        return 0
    finally:
        await nc.close()


async def _api_key_revoke(cfg: NatsBackendConfig, *, key_id: str) -> int:
    nc, _, kv = await _connect_js(cfg)
    try:
        kv_key = make_kv_key_for_api_key_id(key_id)
        try:
            e = await kv.get(kv_key)
        except KeyNotFoundError:
            _print_json({"error": "not_found", "key_id": key_id})
            return 2
        rec = ApiKeyRecord.from_json_bytes(e.value)
        now = time.time()
        revoked = ApiKeyRecord(
            key_id=rec.key_id,
            tenant_id=rec.tenant_id,
            kdf=rec.kdf,
            iterations=rec.iterations,
            salt_b64=rec.salt_b64,
            hash_b64=rec.hash_b64,
            created_at=rec.created_at,
            revoked_at=now,
        )
        await kv.put(kv_key, revoked.to_json_bytes())
        _print_json({"key_id": key_id, "revoked_at": now})
        return 0
    finally:
        await nc.close()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pyoco-server-admin")
    p.add_argument("--nats-url", default=None, help="Override PYOCO_NATS_URL (optional)")
    sub = p.add_subparsers(dest="command", required=True)

    api_key = sub.add_parser("api-key", help="Manage HTTP API keys (stored in JetStream KV)")
    api_key_sub = api_key.add_subparsers(dest="api_key_command", required=True)

    c = api_key_sub.add_parser("create", help="Create a new API key")
    c.add_argument("--tenant", required=True, help="tenant_id (e.g. demo)")

    api_key_sub.add_parser("list", help="List API keys (no secrets)")

    r = api_key_sub.add_parser("revoke", help="Revoke an API key by key_id")
    r.add_argument("--key-id", required=True, help="key_id to revoke")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = NatsBackendConfig.from_env()
    if args.nats_url:
        cfg = NatsBackendConfig(**{**cfg.__dict__, "nats_url": args.nats_url})

    if args.command == "api-key":
        if args.api_key_command == "create":
            return asyncio.run(_api_key_create(cfg, tenant_id=args.tenant))
        if args.api_key_command == "list":
            return asyncio.run(_api_key_list(cfg))
        if args.api_key_command == "revoke":
            return asyncio.run(_api_key_revoke(cfg, key_id=args.key_id))

    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
