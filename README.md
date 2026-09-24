# Telemetry Platform

Devices send sensor readings to an HTTP API. The API authenticates each device, validates
and stores its readings, and serves them back by time range. Alerts, batch ingestion, a
load-tested simulator, cloud deploy and dashboards follow in later milestones (see
[Roadmap](#roadmap)).

> **Data:** all device data in this repo is **synthetic** (simulated devices). No real
> hardware is involved.

## Quick start

Requires Docker.

```bash
docker compose up --build        # Postgres + migrations + API on :8000
python scripts/smoke.py          # registers a device, posts 20 readings, queries them back
```

API docs: http://localhost:8000/docs

## API (v0.1)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | none | Liveness plus DB check (503 if the DB is down) |
| POST | `/devices` | `X-Admin-Token` | Register a device; returns its API key **once** |
| POST | `/readings` | `X-API-Key` | Ingest one reading `{metric, value, ts}` |
| GET | `/devices/{id}/readings?start&end[&metric][&limit]` | `X-API-Key` | Readings in `[start, end)`, oldest first |

Validation: metric names are `snake_case`, values must be finite, and timestamps must carry a
timezone and be no more than 5 minutes in the future. API keys are stored only as SHA-256
hashes.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/mypy app
.venv/bin/pytest                               # unit tests (SQLite)
docker compose up -d db
DATABASE_URL=postgresql+psycopg://telemetry:telemetry@localhost:5432/telemetry .venv/bin/pytest -m integration
```

## Results

Every number below is measured, dated, and labelled with the data it came from. Blank means
not measured yet.

| Metric | Value | Date | Data |
|---|---|---|---|
| Max sustained ingest rate (p95 < budget) | | | synthetic |
| Test count / coverage | | | |
| CI duration | | | |
| Deploy time | | | |
| Recovery time after forced DB restart | | | |
| Monthly cloud cost | | | |

## Roadmap

- [ ] **Week 1:** vertical slice: ingest, auth, Postgres plus migrations, query, CI
- [ ] **Week 2:** batch endpoint, idempotency keys, alert worker, fleet simulator, baseline load test
- [ ] **Week 3:** Terraform, deploy on merge with approval, budget alarm
- [ ] **Week 4:** structured logs, metrics, Grafana as code, security scans, threat model, demo

Design decisions: [docs/adr](docs/adr).
