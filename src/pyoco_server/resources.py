from __future__ import annotations

from nats.js import api
from nats.js.errors import BucketNotFoundError, NotFoundError

from .config import NatsBackendConfig


async def ensure_resources(js, config: NatsBackendConfig) -> None:
    """
    Ensure JetStream resources exist:
    - a WORK_QUEUE retention stream for jobs
    - a KV bucket for latest run snapshots
    """

    # Stream (work queue)
    try:
        await js.stream_info(config.work_stream)
    except NotFoundError:
        await js.add_stream(
            api.StreamConfig(
                name=config.work_stream,
                subjects=[f"{config.work_subject_prefix}.>"],
                retention=api.RetentionPolicy.WORK_QUEUE,
            )
        )

    # Stream (DLQ; diagnostic)
    try:
        await js.stream_info(config.dlq_stream)
    except NotFoundError:
        await js.add_stream(
            api.StreamConfig(
                name=config.dlq_stream,
                subjects=[f"{config.dlq_subject_prefix}.>"],
                retention=api.RetentionPolicy.LIMITS,
                max_age=float(config.dlq_max_age_sec),
                max_msgs=int(config.dlq_max_msgs),
                max_bytes=int(config.dlq_max_bytes),
            )
        )

    # KV bucket (latest run snapshot)
    try:
        await js.key_value(config.runs_kv_bucket)
    except NotFoundError:
        await js.create_key_value(api.KeyValueConfig(bucket=config.runs_kv_bucket, history=1))

    # KV bucket (worker liveness)
    try:
        await js.key_value(config.workers_kv_bucket)
    except NotFoundError:
        await js.create_key_value(
            api.KeyValueConfig(
                bucket=config.workers_kv_bucket,
                history=1,
                ttl=float(config.workers_kv_ttl_sec),
            )
        )

    # KV bucket (auth; API keys)
    # Kept separate from runs/workers so it can be access-controlled independently.
    # 認証用KV（API key）。runs/workersと分離して権限分離しやすくする。
    try:
        await js.key_value(config.auth_kv_bucket)
    except NotFoundError:
        await js.create_key_value(api.KeyValueConfig(bucket=config.auth_kv_bucket, history=1))

    # Object Store bucket (wheel registry)
    try:
        await js.object_store(config.wheel_object_store_bucket)
    except (NotFoundError, BucketNotFoundError):
        await js.create_object_store(
            bucket=str(config.wheel_object_store_bucket),
            max_bytes=int(config.wheel_max_bytes),
        )

    # KV bucket (wheel distribution history / audit trail)
    try:
        await js.key_value(config.wheel_history_kv_bucket)
    except NotFoundError:
        await js.create_key_value(
            api.KeyValueConfig(
                bucket=config.wheel_history_kv_bucket,
                history=1,
                ttl=float(config.wheel_history_ttl_sec),
            )
        )
