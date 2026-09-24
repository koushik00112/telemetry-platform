# Threat model

Scope: the API, worker, database and deploy pipeline as deployed by `infra/`. The method
is STRIDE applied to each trust boundary, kept short on purpose. Last reviewed: 2026-09-24.

## Assets
Device readings and alerts (integrity matters more than secrecy), device API keys, the admin
token, the database password, the AWS account (cost and resources), and the CI pipeline.

## Trust boundaries
1. Internet → ALB → API
2. API/worker → database
3. GitHub Actions → AWS
4. Developer machine → Terraform state

## Threats and mitigations

| # | Boundary | Threat (STRIDE) | Mitigation in place | Gap / next step |
|---|---|---|---|---|
| 1 | Internet → API | **Spoofing** a device | 256-bit random API keys; only SHA-256 hashes stored; compared by indexed lookup of the hash | No key rotation or expiry endpoint |
| 2 | Internet → API | **Spoofing** an admin | Admin token (48 chars) from Secrets Manager; constant-time compare; app refuses to start in production with the dev default | Single shared token; no per-user identity or audit trail |
| 3 | Internet → API | **Tampering**: one device writes as another | Device id comes from the key, never from the request body; reads are limited to the caller's own device (403 otherwise) | none |
| 4 | Internet → API | **Tampering**: poisoned values (NaN, huge timestamps) | Pydantic validation: finite numbers, timezone required, ≤5 min future skew, metric name pattern, batch ≤1000 | No per-device plausibility ranges |
| 5 | Internet → API | **Repudiation**: a device denies sending data | `received_at` stored; request id on every log line | Logs keep 14 days; no signed payloads |
| 6 | Internet → API | **Information disclosure** via errors or metrics | 503 handler hides DB errors; `/metrics` is blocked at the ALB (a deploy check verifies it's a 404); keys never logged | HTTP only until a domain and ACM certificate are added (`certificate_arn`), so **keys cross the internet in cleartext** |
| 7 | Internet → API | **Denial of service**: floods or huge batches | Batch cap 1000; query row cap 10k; ALB drops invalid headers | **No rate limiting.** Add AWS WAF rate rules (about $6/month) or per-key limits |
| 8 | API → DB | **Information disclosure**: DB exposed | Private subnets, no internet route, SG allows only tasks, TLS forced (`rds.force_ssl`), storage encrypted | Single DB user with DDL rights; split migration and runtime users |
| 9 | API → DB | **Tampering**: SQL injection | SQLAlchemy parameterised queries only; no string-built SQL | none |
| 10 | GitHub → AWS | **Elevation of privilege**: stolen CI credentials | OIDC, no stored keys; build role can only push to one ECR repo; deploy role limited to one cluster, `PassRole` only to `telemetry-ecs-*`, and only from the `production` environment, which needs manual approval | Third-party actions pinned to tags, not commit SHAs (Dependabot watches them) |
| 11 | Supply chain | **Tampering**: vulnerable or malicious dependencies | pip-audit, Trivy (deps, image, IaC, secrets) in CI; images scanned before push; ECR scan on push; immutable tags | Python deps are ranges, not a hash-locked file |
| 12 | Dev → state | **Information disclosure**: secrets in Terraform state | State in a private, versioned, encrypted, TLS-only S3 bucket | Anyone with state access sees the DB password and admin token. Could move to RDS-managed secrets with rotation (needs app support for reconnect-on-rotate) |
| 13 | AWS account | **Denial of wallet** | Budget with $1, 100% and forecast alerts; `demo_mode` teardown; no NAT; small instance sizes | Alerts don't stop spend; a cap needs a Budgets action or manual teardown |

## Accepted risks (demo scope)
- HTTP without TLS when no domain is configured (#6). **Don't send real data in this mode.**
- No rate limiting (#7).
- One admin identity (#2).

## Checks that enforce this model
- `tests/unit/test_api.py`: auth failures, cross-device read is 403, validation.
- `tests/unit/test_ops.py`: 503 without a stack trace; production refuses the dev token;
  metrics labels contain no raw ids.
- CI `security` job: pip-audit plus Trivy (secrets, dependencies, IaC).
- `scripts/deploy_ecs.sh`: fails the deploy if `/metrics` is publicly reachable.
