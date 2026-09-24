# ADR 0002: Alert worker claims readings with a flag and SKIP LOCKED

Date: 2026-09-24
Status: Accepted

## Context
Alerts are evaluated off the ingest path by a background worker. The worker needs to
know which readings it has already evaluated.

The obvious design is a cursor: remember the highest `readings.id` processed. That is
subtly wrong in Postgres. Sequence values are handed out when a row is inserted, not when
its transaction commits, so a transaction holding id 9 can commit after one holding id 10.
A cursor that has moved past 10 would never see 9.

## Decision
- Each reading has an `alert_checked` boolean, plus a partial index on unchecked rows.
- The worker selects unchecked rows `ORDER BY ts LIMIT n FOR UPDATE SKIP LOCKED`,
  evaluates them, sets the flag and commits in one transaction. If it crashes
  mid-batch, the transaction rolls back and the rows are retried.
- An alert opens on the first breaching reading and resolves on the next in-range one.
  A partial unique index allows at most one open alert per (rule, device).

## Consequences
- Every reading is written twice (insert, then flag update). That costs extra WAL and
  table bloat on the busiest table. Measure it in the load test before optimising.
- Several workers can run safely, but readings from one device may then be evaluated
  out of order across workers. If two workers race to open the same alert, the unique
  index rejects one and its batch is retried. Run one worker until load says otherwise.
- Readings that arrive late (older `ts` than ones already evaluated) are still
  evaluated, but can open or resolve an alert out of time order. Accepted for now.
- Alternatives if the double write hurts: evaluate rules at ingest time, or use an
  outbox table or `LISTEN/NOTIFY`.
