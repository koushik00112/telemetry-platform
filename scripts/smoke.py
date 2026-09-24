"""End-to-end smoke test against a running API.

Registers a device, posts synthetic readings, then queries them back.
Usage: python scripts/smoke.py [--url http://localhost:8000] [--count 20]
"""

import argparse
import math
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx


def wait_until_up(client: httpx.Client, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            sys.exit(f"API at {client.base_url} not healthy after {timeout:.0f}s")
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN", "dev-admin-token"))
    args = parser.parse_args()

    with httpx.Client(base_url=args.url, timeout=10) as client:
        wait_until_up(client)
        r = client.post(
            "/devices",
            json={"name": f"smoke-{uuid.uuid4().hex[:8]}"},
            headers={"X-Admin-Token": args.admin_token},
        )
        r.raise_for_status()
        device = r.json()
        headers = {"X-API-Key": device["api_key"]}
        print(f"registered device {device['name']} ({device['id']})")

        start = datetime.now(UTC) - timedelta(minutes=args.count)
        for i in range(args.count):
            # Synthetic temperature: a slow sine wave around 21 °C.
            reading = {
                "metric": "temperature_c",
                "value": round(21 + 2 * math.sin(i / 5), 3),
                "ts": (start + timedelta(minutes=i)).isoformat(),
            }
            client.post("/readings", json=reading, headers=headers).raise_for_status()
        print(f"posted {args.count} readings")

        r = client.get(
            f"/devices/{device['id']}/readings",
            params={"start": start.isoformat(), "end": datetime.now(UTC).isoformat()},
            headers=headers,
        )
        r.raise_for_status()
        got = len(r.json())
        print(f"queried back {got} readings")
        return 0 if got == args.count else 1


if __name__ == "__main__":
    sys.exit(main())
