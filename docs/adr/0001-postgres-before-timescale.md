# ADR 0001: Plain Postgres for readings (for now)

Date: 2026-09-24
Status: Accepted

## Context
Readings are append-heavy time series queried by device, metric and time range.
TimescaleDB or InfluxDB would suit that shape, but add operational surface before we
know the load.

## Decision
Store readings in a plain Postgres table with a composite index on
`(device_id, metric, ts)`. Timestamps are `timestamptz`, and the API rejects values without
a timezone.

## Consequences
- One database to run, migrate and back up.
- Revisit after the week 2 load test. If the measured ingest rate or range-query
  latency misses budget, evaluate partitioning by time or TimescaleDB, with numbers.
