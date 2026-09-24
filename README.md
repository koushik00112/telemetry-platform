# Telemetry Platform

Devices send sensor readings to an HTTP API. The API authenticates each device, validates
and stores its readings (skipping duplicates), and serves them back by time range. A
background worker raises and resolves threshold alerts. A seeded simulator generates a
device fleet with injected faults. Cloud deploy and dashboards follow in later milestones
(see [Roadmap](#roadmap)).

> **Data:** all device data in this repo is **synthetic** (simulated devices). No real
> hardware is involved.

## Quick start

Requires Docker.

```bash
docker compose up --build        # Postgres, migrations, API on :8000, alert worker
python scripts/smoke.py          # registers a device, posts 20 readings, queries them back

# Add a rule, then backfill 6 h of data from 20 simulated devices with injected faults
curl -X POST localhost:8000/alert-rules -H 'X-Admin-Token: dev-admin-token' \
     -H 'Content-Type: application/json' -d '{"metric":"temperature_c","operator":"gt","threshold":32}'
python -m simulator --devices 20 --interval 60 --duration 21600 --backfill --fault-rate 0.02
curl 'localhost:8000/alerts?status=resolved' -H 'X-Admin-Token: dev-admin-token'
```

The simulator writes the ground truth for every injected fault (spike, stuck, drift,
dropout) to `fault_events.csv`. The same `--seed` reproduces the same fault sequence.

API docs: http://localhost:8000/docs

## API (v0.2)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | none | Liveness plus DB check (503 if the DB is down) |
| POST | `/devices` | `X-Admin-Token` | Register a device; returns its API key **once** |
| POST | `/readings` | `X-API-Key` | Ingest one reading `{metric, value, ts}`. 201 if new, 200 if duplicate |
| POST | `/readings/batch` | `X-API-Key` | Ingest up to 1000 readings; optional `Idempotency-Key` header |
| GET | `/devices/{id}/readings?start&end[&metric][&limit]` | `X-API-Key` | Readings in `[start, end)`, oldest first |
| POST/GET | `/alert-rules` | `X-Admin-Token` | Create or list rules `{metric, operator: gt\|lt, threshold}` |
| GET | `/alerts?status&device_id` | `X-Admin-Token` | List alerts, newest first |

Validation: metric names are `snake_case`, values must be finite, and timestamps must carry a
timezone and be no more than 5 minutes in the future. API keys are stored only as SHA-256
hashes.

**Duplicates:** (device, metric, ts) is unique. A resent reading is skipped, not
rejected, and the first write wins. **Idempotency:** a batch retried with the same
`Idempotency-Key` gets the original response (header `Idempotent-Replayed: true`).
Reusing the key with a different body returns 422.

**Alerts:** see [ADR 0002](docs/adr/0002-alert-worker-claims-rows-with-a-flag.md) for how
the worker claims readings safely and its known limits.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/mypy app simulator
.venv/bin/pytest                               # unit tests (SQLite)
docker compose up -d db
DATABASE_URL=postgresql+psycopg://telemetry:telemetry@localhost:5432/telemetry .venv/bin/pytest -m integration
```

## Results

Every number below is measured, dated, and labelled with the data it came from. Blank means
not measured yet.

| Metric | Value | Date | Data |
|---|---|---|---|
| Max sustained ingest rate (p95 < 250 ms) | | | synthetic. Method: [docs/loadtest.md](docs/loadtest.md) |
| Test count / coverage | | | |
| CI duration | | | |
| Deploy time | | | |
| Recovery time after forced DB restart | | | |
| Monthly cloud cost | | | |

## Roadmap

- [ ] **Week 1:** vertical slice: ingest, auth, Postgres plus migrations, query, CI (code done; CI not yet run)
- [ ] **Week 2:** batch endpoint, idempotency keys, alert worker, fleet simulator, baseline load test (code done; load test not yet run)
- [ ] **Week 3:** Terraform, deploy on merge with approval, budget alarm
- [ ] **Week 4:** structured logs, metrics, Grafana as code, security scans, threat model, demo

Design decisions: [docs/adr](docs/adr).
