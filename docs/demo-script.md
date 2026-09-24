# 3-minute demo script

Record the screen with voice-over; one take is fine. Everything shown must be real output.
Say out loud that the device data is **synthetic**.

| Time | Show | Say (roughly) |
|---|---|---|
| 0:00–0:20 | README top and architecture diagram | "Devices send sensor readings to an API. It stores them, raises alerts, and runs on AWS, built with Terraform. The data here is from a simulator, not real hardware." |
| 0:20–0:50 | Terminal: `python -m simulator --url $URL --devices 20 --interval 60 --duration 21600 --backfill --fault-rate 0.02` | "Twenty simulated devices backfill six hours of data with injected faults: spikes, stuck sensors, drift and dropouts. The same seed gives the same faults, and the ground truth goes to a CSV." |
| 0:50–1:15 | `curl $URL/alerts?status=resolved` (admin token) | "A background worker evaluates rules. Alerts open on the first bad reading and close on the next good one." Mention SKIP LOCKED in one sentence. |
| 1:15–1:40 | Re-run one batch with the same `Idempotency-Key`: show `Idempotent-Replayed: true` | "If a device retries after a timeout, it gets the original answer. No double counting." |
| 1:40–2:10 | Grafana dashboard (local) during a Locust run | "p95 latency against a 250 ms budget. The measured maximum sustained rate is X readings per second on <machine>." Use the number from docs/loadtest.md only. |
| 2:10–2:35 | `scripts/db_outage_drill.sh` output | "I kill the database on purpose. The API returns 503 with Retry-After instead of crashing, and recovers in N seconds." |
| 2:35–3:00 | GitHub Actions: CI run, then Deploy waiting for approval | "Every push runs tests against real Postgres, security scans and Terraform validation. Deploys need my approval and use short-lived OIDC credentials, with no AWS keys stored anywhere." |

Before recording: `terraform apply`, run the Deploy workflow, fill the README results
table. After recording: `terraform destroy`.
