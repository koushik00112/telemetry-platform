import asyncio
import csv
import json
from datetime import UTC, datetime

import httpx
import pytest

from simulator.__main__ import Stats, load_or_register, parse_args, run, send_batch, write_events
from simulator.model import Sample


def test_registers_devices_once_and_caches_keys(client, tmp_path):
    cache = tmp_path / "devices.json"
    keys = load_or_register(client, cache, count=3, seed=9, admin_token="dev-admin-token")
    assert list(keys) == ["sim-s9-0000", "sim-s9-0001", "sim-s9-0002"]
    assert oct(cache.stat().st_mode)[-3:] == "600"  # keys are secrets

    # A rerun with more devices reuses the cached three and registers one more.
    again = load_or_register(client, cache, count=4, seed=9, admin_token="dev-admin-token")
    assert {k: again[k] for k in keys} == keys
    assert len(json.loads(cache.read_text())) == 4


def test_retry_reuses_the_same_idempotency_key():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Idempotency-Key"])
        if len(seen) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"received": 1, "inserted": 1, "duplicates": 0})

    async def go():
        stats = Stats()
        async with httpx.AsyncClient(
            base_url="http://t", transport=httpx.MockTransport(handler)
        ) as c:
            await send_batch(c, "tp_k", [Sample("t", 1.0, datetime.now(UTC), None)], stats)
        return stats

    stats = asyncio.run(go())
    assert len(seen) == 2 and seen[0] == seen[1]
    assert (stats.retries, stats.inserted, stats.failed_batches) == (1, 1, 0)


def test_gives_up_after_repeated_failures(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    async def go():
        stats = Stats()
        transport = httpx.MockTransport(lambda r: httpx.Response(503))
        async with httpx.AsyncClient(base_url="http://t", transport=transport) as c:
            await send_batch(c, "k", [], stats)
        return stats

    assert asyncio.run(go()).failed_batches == 1


async def _no_sleep(_seconds):
    return None


def test_backfill_end_to_end_against_the_api(client, tmp_path, session_factory):
    from app.main import app

    args = parse_args(
        [
            "--url",
            "http://testserver",
            "--devices",
            "2",
            "--interval",
            "60",
            "--duration",
            "3600",
            "--backfill",
            "--fault-rate",
            "0.05",
            "--seed",
            "3",
            "--batch-size",
            "50",
            # The in-memory SQLite test DB is one shared connection: no concurrent requests.
            "--concurrency",
            "1",
            "--devices-file",
            str(tmp_path / "d.json"),
            "--events",
            str(tmp_path / "e.csv"),
        ]
    )
    keys = load_or_register(client, args.devices_file, args.devices, args.seed, args.admin_token)
    stats, devices = asyncio.run(run(args, keys, transport=httpx.ASGITransport(app=app)))

    assert len(devices) == 2
    assert stats.failed_batches == 0
    assert stats.sent == stats.inserted > 0
    n = write_events(args.events, devices)
    rows = list(csv.DictReader(args.events.open()))
    assert len(rows) == n
    assert all(r["synthetic"] == "1" for r in rows)


def test_rejects_batch_size_above_api_limit():
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "1001"])
