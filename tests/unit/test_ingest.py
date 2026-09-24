from datetime import UTC, datetime, timedelta

from tests.unit.conftest import ADMIN

NOW = datetime.now(UTC).replace(microsecond=0)


def device_headers(client, name="dev-1"):
    r = client.post("/devices", json={"name": name}, headers=ADMIN)
    return {"X-API-Key": r.json()["api_key"]}


def batch(n, offset=0, value=21.0):
    return {
        "readings": [
            {
                "metric": "temperature_c",
                "value": value,
                "ts": (NOW - timedelta(seconds=offset + i)).isoformat(),
            }
            for i in range(n)
        ]
    }


def test_single_duplicate_returns_200_with_the_stored_reading(client):
    h = device_headers(client)
    first = {"metric": "temperature_c", "value": 20.0, "ts": NOW.isoformat()}
    assert client.post("/readings", json=first, headers=h).status_code == 201

    resend = {**first, "value": 99.0}  # same device/metric/ts, different value
    r = client.post("/readings", json=resend, headers=h)
    assert r.status_code == 200
    assert r.json()["value"] == 20.0  # first write wins


def test_batch_counts_duplicates_including_within_one_batch(client):
    h = device_headers(client)
    assert client.post("/readings/batch", json=batch(5), headers=h).json() == {
        "received": 5,
        "inserted": 5,
        "duplicates": 0,
    }
    # Overlaps 3 of the stored readings, and repeats one new reading twice.
    body = batch(5, offset=2)
    body["readings"].append(body["readings"][-1])
    assert client.post("/readings/batch", json=body, headers=h).json() == {
        "received": 6,
        "inserted": 2,
        "duplicates": 4,
    }


def test_same_timestamp_on_different_devices_is_not_a_duplicate(client):
    a, b = device_headers(client, "a"), device_headers(client, "b")
    assert client.post("/readings/batch", json=batch(3), headers=a).json()["inserted"] == 3
    assert client.post("/readings/batch", json=batch(3), headers=b).json()["inserted"] == 3


def test_batch_size_limits(client):
    h = device_headers(client)
    assert client.post("/readings/batch", json=batch(1000), headers=h).status_code == 200
    assert client.post("/readings/batch", json=batch(1001), headers=h).status_code == 422
    assert client.post("/readings/batch", json={"readings": []}, headers=h).status_code == 422


def test_one_invalid_reading_rejects_the_whole_batch(client):
    h = device_headers(client)
    body = batch(3)
    body["readings"][1]["value"] = "inf"
    assert client.post("/readings/batch", json=body, headers=h).status_code == 422
    assert client.post("/readings/batch", json=batch(3), headers=h).json()["inserted"] == 3


def test_idempotent_retry_replays_the_original_result(client):
    h = {**device_headers(client), "Idempotency-Key": "batch-001"}
    first = client.post("/readings/batch", json=batch(4), headers=h)
    assert first.json()["inserted"] == 4
    assert "Idempotent-Replayed" not in first.headers

    retry = client.post("/readings/batch", json=batch(4), headers=h)
    assert retry.status_code == 200
    assert retry.headers["Idempotent-Replayed"] == "true"
    # Without the key, the retry would report inserted=0, duplicates=4.
    assert retry.json() == first.json()


def test_idempotency_key_reused_with_different_body_is_rejected(client):
    h = {**device_headers(client), "Idempotency-Key": "batch-001"}
    client.post("/readings/batch", json=batch(4), headers=h)
    r = client.post("/readings/batch", json=batch(4, value=30.0), headers=h)
    assert r.status_code == 422


def test_idempotency_keys_are_scoped_per_device(client):
    a = {**device_headers(client, "a"), "Idempotency-Key": "same-key"}
    b = {**device_headers(client, "b"), "Idempotency-Key": "same-key"}
    client.post("/readings/batch", json=batch(2), headers=a)
    r = client.post("/readings/batch", json=batch(3), headers=b)
    assert r.json()["inserted"] == 3
    assert "Idempotent-Replayed" not in r.headers
