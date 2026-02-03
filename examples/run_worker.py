import argparse
import asyncio

from pyoco_server import NatsBackendConfig, PyocoNatsWorker, configure_logging

from hello_flow import resolve_flow


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nats-url", default="nats://127.0.0.1:4222")
    p.add_argument("--tags", default="hello", help="comma-separated tags (OR)")
    p.add_argument("--worker-id", default="w1")
    args = p.parse_args()

    configure_logging(service="pyoco-server:worker")
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    cfg = NatsBackendConfig(nats_url=args.nats_url)
    worker = await PyocoNatsWorker.connect(
        config=cfg,
        flow_resolver=resolve_flow,
        worker_id=args.worker_id,
        tags=tags,
    )
    try:
        while True:
            await worker.run_once(timeout=1.0)
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
