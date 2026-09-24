# ADR 0003: ECS Fargate in public subnets, no NAT gateway

Date: 2026-09-24
Status: Accepted

## Context
The platform runs on AWS on free-tier credits. A textbook layout puts containers in
private subnets behind a NAT gateway, but one NAT gateway costs about $32/month plus data
charges, more than the rest of the stack combined. The containers only need outbound
access to AWS APIs (ECR, Secrets Manager, CloudWatch Logs).

## Decision
- **Compute:** ECS on Fargate (ARM64), one API service behind an ALB and one worker
  service. No servers to patch, and deploys are rolling with a circuit breaker.
- **Networking:** tasks run in public subnets with public IPs. Their security group
  accepts inbound traffic only from the ALB on port 8000, so nothing on the internet can
  reach a task directly. Outbound is limited to HTTPS (AWS APIs) and Postgres (the DB).
- **Database:** RDS Postgres 16 in private subnets with no route to the internet,
  reachable only from the tasks' security group. Single-AZ, `db.t4g.micro`, TLS enforced.
- **Health checks:** the ALB checks `/livez`, which doesn't touch the database. If
  `/healthz` (DB-backed) were used, a DB outage would mark every task unhealthy and ECS
  would restart them all in a loop, slowing recovery.
- **Teardown by default:** `demo_mode = true` turns off deletion protection and the
  final snapshot, so `terraform destroy` removes everything in one step.

## Consequences
- Each task holds a public IPv4 address, which AWS bills at about $3.60/month each (the
  ALB's two addresses are billed the same way). That's still cheaper than NAT.
- If the tasks' security group were misconfigured, they would be directly exposed.
  Mitigated by Terraform review and the Trivy IaC scan in CI.
- Single-AZ RDS means an AZ outage takes the DB down. Accepted for a demo; production
  would use `multi_az = true` (about double the DB cost).
- The alternative, VPC interface endpoints for ECR/Secrets/Logs, costs about $7/month
  per endpoint per AZ, so it's no cheaper at this scale.

## Rough monthly cost (estimate, not measured)
Fargate 2 × 0.25 vCPU/0.5 GB ARM, about $17; ALB, about $18; RDS `db.t4g.micro` with
20 GB gp3, about $16; public IPv4 × 4 (2 tasks + 2 ALB), about $15; Secrets Manager, logs
and ECR, about $2. Total **about $65/month** if left running, or roughly $2 a day.
Record the real figure from Cost Explorer in the README, and tear it down between demos
(see the runbook).
