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
