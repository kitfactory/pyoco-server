from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from .config import NatsBackendConfig


async def publish_dlq(
    *,
    js,
    config: NatsBackendConfig,
    tag: str,
    reason: str,
    payload: Dict[str, Any],
    error: Optional[str] = None,
) -> None:
    """
    Best-effort DLQ publish for diagnostics. The caller decides when to DLQ.
    """

    body = {
        "reason": reason,
        "error": error,
        "timestamp": time.time(),
        **payload,
    }
    subject = f"{config.dlq_subject_prefix}.{tag}"
    await js.publish(
        subject=subject,
        payload=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        stream=config.dlq_stream,
    )

