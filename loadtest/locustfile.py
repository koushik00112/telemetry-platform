"""Batch-ingest load test. Each Locust user is one simulated device.

  pip install -e ".[load]"
  locust -f loadtest/locustfile.py --host http://localhost:8000 \
      --headless -u 50 -r 10 -t 3m --csv loadtest/results/run

Env: ADMIN_TOKEN (default dev-admin-token), BATCH_SIZE (default 100).
Timestamps step back from "now" so every reading is unique and none are in the future.
"""

import itertools
import os
import random
import uuid
from datetime import UTC, datetime, timedelta

from locust import HttpUser, between, task

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))


class Device(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        r = self.client.post(
            "/devices",
            json={"name": f"load-{uuid.uuid4().hex[:12]}"},
            headers={"X-Admin-Token": ADMIN_TOKEN},
            name="/devices (setup)",
        )
        r.raise_for_status()
        self.headers = {"X-API-Key": r.json()["api_key"]}
        self.origin = datetime.now(UTC)
        self.counter = itertools.count()

    @task
    def post_batch(self) -> None:
        readings = []
        for _ in range(BATCH_SIZE):
            ts = self.origin - timedelta(milliseconds=next(self.counter))
            readings.append(
                {"metric": "temperature_c", "value": random.gauss(22, 0.5), "ts": ts.isoformat()}  # noqa: S311
            )
        self.client.post("/readings/batch", json={"readings": readings}, headers=self.headers)
