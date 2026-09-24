# Load testing

## Goal
Find the **maximum sustained ingest rate** (readings/s) at which **p95 latency of
`POST /readings/batch` stays under the budget**, with the error rate under 0.1%.

- Latency budget (p95): **250 ms**. This is my choice for a batch endpoint, not an
  industry standard. Change it here before the first run, not after seeing results.
- "Sustained" means a 3-minute steady state after ramp-up.

## Setup to record with every run
Machine (CPU, RAM), OS, Docker resource limits, Postgres version, API worker count,
batch size, Locust users and spawn rate, git commit. Results without this context
aren't comparable.

## How to run
```bash
docker compose up -d --build
pip install -e ".[load]"
mkdir -p loadtest/results
# Step the user count up across runs (e.g. 10, 25, 50, 100) until p95 breaks the budget.
locust -f loadtest/locustfile.py --host http://localhost:8000 \
    --headless -u 50 -r 10 -t 3m --csv loadtest/results/u50
```
Readings/s = requests/s × `BATCH_SIZE`. Take the p95 from the `_stats.csv` row for
`/readings/batch`, not the aggregate row, which includes setup calls.

## Results

Data: **synthetic** (Locust-generated readings). Environment: local Docker unless stated.

| Date | Commit | Users | Batch | Req/s | Readings/s | p50 ms | p95 ms | Errors | Within budget? |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

**Max sustained ingest rate:** not measured yet.

## Notes
- The load generator runs on the same machine as the API, so the two compete for CPU.
  Say so when quoting numbers.
- Watch whether the alert worker keeps up. Check the backlog of unchecked readings
  (`SELECT count(*) FROM readings WHERE NOT alert_checked`) during and after each run.
