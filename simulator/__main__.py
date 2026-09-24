"""Simulated device fleet. All data it sends is synthetic.

Examples:
  # 10 devices, one tick every 2 s for 60 s, 1% chance per tick of starting a fault
  python -m simulator --devices 10 --interval 2 --duration 60 --fault-rate 0.01

  # Backfill 24 h of 1-minute data as fast as the API accepts it
  python -m simulator --devices 50 --interval 60 --duration 86400 --backfill

Device API keys are cached in --devices-file so reruns reuse the same devices.
Fault ground truth is written to --events (CSV) for later evaluation.
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from simulator.model import DeviceModel, Sample

RETRYABLE = {429, 500, 502, 503, 504}


@dataclass
class Stats:
    sent: int = 0
    inserted: int = 0
    duplicates: int = 0
    retries: int = 0
    failed_batches: int = 0
    started: float = field(default_factory=time.monotonic)


def load_or_register(
    client: httpx.Client, path: Path, count: int, seed: int, admin_token: str
) -> dict[str, str]:
    """Return {device_name: api_key}, registering any devices not yet in the cache file."""
    cache: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
    for i in range(count):
        name = f"sim-s{seed}-{i:04d}"
        if name in cache:
            continue
        r = client.post("/devices", json={"name": name}, headers={"X-Admin-Token": admin_token})
        if r.status_code == 409:
            sys.exit(
                f"{name} exists on the server but its key isn't in {path}. Use another --seed."
            )
        r.raise_for_status()
        cache[name] = r.json()["api_key"]
    path.write_text(json.dumps(cache, indent=2))
    path.chmod(0o600)
    return {f"sim-s{seed}-{i:04d}": cache[f"sim-s{seed}-{i:04d}"] for i in range(count)}


async def send_batch(
    client: httpx.AsyncClient, api_key: str, samples: list[Sample], stats: Stats
) -> None:
    body = {
        "readings": [
            {"metric": s.metric, "value": s.value, "ts": s.ts.isoformat()} for s in samples
        ]
    }
    # One key per batch: a retry after a timeout can't double-count, even if the first try landed.
    headers = {"X-API-Key": api_key, "Idempotency-Key": str(uuid.uuid4())}
    for attempt in range(5):
        try:
            r = await client.post("/readings/batch", json=body, headers=headers)
        except httpx.TransportError:
            r = None
        if r is not None and r.status_code not in RETRYABLE:
            r.raise_for_status()
            result = r.json()
            stats.sent += result["received"]
            stats.inserted += result["inserted"]
            stats.duplicates += result["duplicates"]
            return
        stats.retries += 1
        await asyncio.sleep(min(0.2 * 2**attempt, 5))
    stats.failed_batches += 1


async def run(
    args: argparse.Namespace,
    keys: dict[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[Stats, list[DeviceModel]]:
    devices = [DeviceModel(name, i, args.seed, args.fault_rate) for i, name in enumerate(keys)]
    stats = Stats()
    ticks = int(args.duration // args.interval)
    step = timedelta(seconds=args.interval)
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - step * ticks if args.backfill else now
    pending: dict[str, list[Sample]] = {d.name: [] for d in devices}
    limits = httpx.Limits(max_connections=args.concurrency)
    sem = asyncio.Semaphore(args.concurrency)

    async def flush(client: httpx.AsyncClient, name: str) -> None:
        batch, pending[name] = pending[name], []
        if batch:
            async with sem:
                await send_batch(client, keys[name], batch, stats)

    async with httpx.AsyncClient(
        base_url=args.url, timeout=30, limits=limits, transport=transport
    ) as client:
        tasks: set[asyncio.Task[None]] = set()
        for tick in range(ticks):
            ts = start + step * tick if args.backfill else datetime.now(UTC)
            for d in devices:
                pending[d.name].extend(d.step(ts))
                if len(pending[d.name]) >= args.batch_size or not args.backfill:
                    t = asyncio.create_task(flush(client, d.name))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
            if not args.backfill:
                await asyncio.sleep(args.interval)
            elif len(tasks) > args.concurrency * 4:
                await asyncio.gather(*list(tasks))
        await asyncio.gather(*list(tasks))
        await asyncio.gather(*(flush(client, name) for name in pending))

    end = start + step * ticks if args.backfill else datetime.now(UTC)
    for d in devices:
        d.close(end)
    return stats, devices


def write_events(path: Path, devices: list[DeviceModel]) -> int:
    rows = [e for d in devices for e in d.events]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["device", "fault", "metric", "start", "end", "synthetic"])
        for e in rows:
            w.writerow(
                [e.device, e.fault, e.metric or "*", e.start.isoformat(), e.end.isoformat(), 1]
            )
    return len(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m simulator",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--devices", type=int, default=10)
    p.add_argument("--interval", type=float, default=5.0, help="seconds between ticks")
    p.add_argument("--duration", type=float, default=60.0, help="simulated seconds")
    p.add_argument("--fault-rate", type=float, default=0.01, help="chance per tick of a new fault")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--backfill", action="store_true", help="historical timestamps, send ASAP")
    p.add_argument("--batch-size", type=int, default=300, help="readings per request (backfill)")
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--devices-file", type=Path, default=Path(".sim_devices.json"))
    p.add_argument("--events", type=Path, default=Path("fault_events.csv"))
    p.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN", "dev-admin-token"))
    args = p.parse_args(argv)
    if not 1 <= args.batch_size <= 1000:
        p.error("--batch-size must be between 1 and 1000 (the API's batch limit)")
    return args


def main() -> None:
    args = parse_args()

    with httpx.Client(base_url=args.url, timeout=10) as client:
        keys = load_or_register(
            client, args.devices_file, args.devices, args.seed, args.admin_token
        )

    stats, devices = asyncio.run(run(args, keys))
    elapsed = time.monotonic() - stats.started
    n_events = write_events(args.events, devices)
    print(
        f"sent={stats.sent} inserted={stats.inserted} duplicates={stats.duplicates} "
        f"retries={stats.retries} failed_batches={stats.failed_batches} "
        f"elapsed={elapsed:.1f}s rate={stats.sent / max(elapsed, 1e-9):.0f} readings/s"
    )
    print(f"{n_events} synthetic fault events written to {args.events}")
    if stats.failed_batches:
        sys.exit(1)


if __name__ == "__main__":
    main()
