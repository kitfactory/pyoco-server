import argparse
import time

from pyoco_server import PyocoHttpClient


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--tag", default="hello")
    p.add_argument("--api-key", default=None, help="HTTP auth (opt-in): value for X-API-Key")
    args = p.parse_args()

    client = PyocoHttpClient(args.server, api_key=args.api_key)
    try:
        res = client.submit_run("main", params={"ts": time.time()}, tag=args.tag, tags=[args.tag])
        run_id = res["run_id"]
        print(f"submitted run_id={run_id}")

        while True:
            snap = client.get_run(run_id)
            status = snap.get("status")
            if status in {"COMPLETED", "FAILED", "CANCELLED"}:
                print(f"terminal status={status}")
                print("tasks:", snap.get("tasks"))
                return
            time.sleep(0.2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
