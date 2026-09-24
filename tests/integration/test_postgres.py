"""Runs against a real Postgres with real migrations. Skipped unless DATABASE_URL is set.

Locally:  docker compose up -d db
          DATABASE_URL=postgresql+psycopg://telemetry:telemetry@localhost:5432/telemetry pytest -m integration
"""

import os
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="DATABASE_URL not set"),
]


@pytest.fixture(scope="module")
def client():
    command.upgrade(Config("alembic.ini"), "head")
    from app.main import app

    return TestClient(app)


def test_migrations_and_timezone_round_trip(client):
    r = client.post(
        "/devices",
        json={"name": f"it-{uuid.uuid4().hex[:8]}"},
        headers={"X-Admin-Token": "dev-admin-token"},
    )
    assert r.status_code == 201
    device = r.json()
    headers = {"X-API-Key": device["api_key"]}

    # Submit in UTC+05:30; Postgres must store and return the same instant, normalised to UTC.
    ist = timezone(timedelta(hours=5, minutes=30))
    ts = datetime.now(ist).replace(microsecond=0) - timedelta(minutes=1)
    assert (
        client.post(
            "/readings",
            json={"metric": "temperature_c", "value": 22.25, "ts": ts.isoformat()},
            headers=headers,
        ).status_code
        == 201
    )

    r = client.get(
        f"/devices/{device['id']}/readings",
        params={
            "start": (ts - timedelta(minutes=1)).isoformat(),
            "end": (ts + timedelta(minutes=1)).isoformat(),
        },
        headers=headers,
    )
    assert r.status_code == 200
    [row] = r.json()
    assert row["value"] == 22.25
    assert datetime.fromisoformat(row["ts"]) == ts.astimezone(UTC)


def _device(client):
    r = client.post(
        "/devices",
        json={"name": f"it-{uuid.uuid4().hex[:8]}"},
        headers={"X-Admin-Token": "dev-admin-token"},
    )
    return r.json()


def _batch(n, value=21.0):
    now = datetime.now(UTC).replace(microsecond=0)
    return {
        "readings": [
            {
                "metric": "temperature_c",
                "value": value,
                "ts": (now - timedelta(seconds=i)).isoformat(),
            }
            for i in range(n)
        ]
    }


def test_on_conflict_dedupe_and_idempotency_on_postgres(client):
    h = {"X-API-Key": _device(client)["api_key"]}
    body = _batch(10)
    assert client.post("/readings/batch", json=body, headers=h).json()["inserted"] == 10
    assert client.post("/readings/batch", json=body, headers=h).json()["duplicates"] == 10

    keyed = {**h, "Idempotency-Key": uuid.uuid4().hex}
    first = client.post("/readings/batch", json=_batch(3, value=5.0), headers=keyed)
    retry = client.post("/readings/batch", json=_batch(3, value=5.0), headers=keyed)
    assert retry.headers.get("Idempotent-Replayed") == "true"
    assert retry.json() == first.json()


def test_worker_opens_alert_on_postgres(client):
    from app.db import get_engine
    from app.services.alerts import process_batch

    admin = {"X-Admin-Token": "dev-admin-token"}
    metric = f"it_{uuid.uuid4().hex[:8]}"
    client.post(
        "/alert-rules", json={"metric": metric, "operator": "gt", "threshold": 10}, headers=admin
    )
    device = _device(client)
    now = datetime.now(UTC).replace(microsecond=0)
    readings = [
        {"metric": metric, "value": v, "ts": (now - timedelta(seconds=10 - i)).isoformat()}
        for i, v in enumerate([5, 50, 60, 5])
    ]
    client.post(
        "/readings/batch", json={"readings": readings}, headers={"X-API-Key": device["api_key"]}
    )

    with Session(get_engine()) as s:
        while process_batch(s):
            pass

    alerts = client.get("/alerts", params={"device_id": device["id"]}, headers=admin).json()
    assert [(a["status"], a["trigger_value"]) for a in alerts] == [("resolved", 50.0)]


def test_skip_locked_lets_two_workers_split_the_backlog(client):
    from sqlalchemy import select

    from app.db import get_engine
    from app.models import Reading
    from app.services.alerts import process_batch

    engine = get_engine()
    with Session(engine) as s:  # drain anything left by other tests
        while process_batch(s):
            pass
    client.post(
        "/readings/batch", json=_batch(10), headers={"X-API-Key": _device(client)["api_key"]}
    )

    with Session(engine) as holder, Session(engine) as worker:
        # "holder" plays a worker that has claimed the backlog but not committed yet.
        claimed = holder.scalars(
            select(Reading)
            .where(Reading.alert_checked.is_(False))
            .with_for_update(skip_locked=True)
        ).all()
        assert len(claimed) == 10
        assert process_batch(worker) == 0  # skips locked rows instead of blocking
        holder.rollback()
        assert process_batch(worker) == 10
