"""API tests on in-memory SQLite. Fast, but not Postgres: see tests/integration for that."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.unit.conftest import ADMIN

NOW = datetime.now(UTC).replace(microsecond=0)


def register(client: TestClient, name: str = "dev-1") -> dict[str, str]:
    r = client.post("/devices", json={"name": name}, headers=ADMIN)
    assert r.status_code == 201
    return r.json()


def reading(offset_min: int = 0, value: float = 21.5, metric: str = "temperature_c") -> dict:
    return {
        "metric": metric,
        "value": value,
        "ts": (NOW - timedelta(minutes=offset_min)).isoformat(),
    }


def window() -> dict[str, str]:
    return {
        "start": (NOW - timedelta(hours=1)).isoformat(),
        "end": (NOW + timedelta(minutes=1)).isoformat(),
    }


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_register_requires_admin_token(client):
    assert client.post("/devices", json={"name": "x"}).status_code == 401
    bad = client.post("/devices", json={"name": "x"}, headers={"X-Admin-Token": "nope"})
    assert bad.status_code == 401


def test_register_returns_key_once_and_rejects_duplicate_names(client):
    device = register(client)
    assert device["api_key"].startswith("tp_")
    assert client.post("/devices", json={"name": "dev-1"}, headers=ADMIN).status_code == 409


def test_ingest_requires_valid_key(client):
    assert client.post("/readings", json=reading()).status_code == 401
    r = client.post("/readings", json=reading(), headers={"X-API-Key": "tp_wrong"})
    assert r.status_code == 401


def test_ingest_then_query_round_trip(client):
    device = register(client)
    headers = {"X-API-Key": device["api_key"]}
    for i in (3, 2, 1):
        assert (
            client.post("/readings", json=reading(i, value=20 + i), headers=headers).status_code
            == 201
        )

    r = client.get(f"/devices/{device['id']}/readings", params=window(), headers=headers)
    assert r.status_code == 200
    assert [x["value"] for x in r.json()] == [23, 22, 21]  # ordered by ts ascending


def test_query_filters_by_metric_and_time(client):
    device = register(client)
    headers = {"X-API-Key": device["api_key"]}
    client.post("/readings", json=reading(5, metric="temperature_c"), headers=headers)
    client.post("/readings", json=reading(5, metric="humidity_pct"), headers=headers)
    client.post("/readings", json=reading(120), headers=headers)  # outside the 1h window

    r = client.get(
        f"/devices/{device['id']}/readings",
        params={**window(), "metric": "humidity_pct"},
        headers=headers,
    )
    assert [x["metric"] for x in r.json()] == ["humidity_pct"]


def test_device_cannot_read_another_devices_data(client):
    a, b = register(client, "a"), register(client, "b")
    r = client.get(
        f"/devices/{b['id']}/readings", params=window(), headers={"X-API-Key": a["api_key"]}
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    "bad",
    [
        {"metric": "Temperature", "value": 1, "ts": NOW.isoformat()},  # uppercase metric
        {"metric": "t", "value": "nan", "ts": NOW.isoformat()},  # non-finite
        {"metric": "t", "value": 1, "ts": "2026-09-28T12:00:00"},  # no timezone
        {"metric": "t", "value": 1, "ts": (NOW + timedelta(hours=1)).isoformat()},  # future
        {"metric": "t", "value": 1},  # missing ts
    ],
)
def test_ingest_rejects_invalid_readings(client, bad):
    device = register(client)
    assert (
        client.post("/readings", json=bad, headers={"X-API-Key": device["api_key"]}).status_code
        == 422
    )


def test_query_rejects_inverted_or_naive_window(client):
    device = register(client)
    headers = {"X-API-Key": device["api_key"]}
    url = f"/devices/{device['id']}/readings"
    w = window()
    assert (
        client.get(url, params={"start": w["end"], "end": w["start"]}, headers=headers).status_code
        == 422
    )
    naive = {"start": "2026-09-28T00:00:00", "end": "2026-09-29T00:00:00"}
    assert client.get(url, params=naive, headers=headers).status_code == 422
