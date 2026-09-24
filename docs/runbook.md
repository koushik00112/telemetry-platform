# Runbook

## First-time AWS setup (about 30 minutes)

Prerequisites: an AWS account on the **Free Plan**, the AWS CLI logged in as an admin user
(`aws sts get-caller-identity` works), Terraform 1.10 or newer, and the repo pushed to GitHub.

1. **Bootstrap** (budget alarm, state bucket, CI roles). It runs once and keeps local state.
   ```bash
   cd infra/bootstrap
   terraform init
   terraform apply -var github_repo=<owner>/<repo> -var budget_email=<you@example.com>
   ```
   Confirm the AWS Budgets subscription email. Keep `infra/bootstrap/terraform.tfstate`
   somewhere safe (it is gitignored).

2. **GitHub settings** (repo → Settings):
   - *Secrets and variables → Actions → Variables*: `AWS_BUILD_ROLE_ARN` = `ci_build_role_arn` output.
   - *Environments → New environment* `production`: add yourself under **Required
     reviewers**, and add the variable `AWS_DEPLOY_ROLE_ARN` = `ci_deploy_role_arn` output.

3. **App stack:**
   ```bash
   cd infra/app
   cp backend.hcl.example backend.hcl   # set bucket = state_bucket output
   terraform init -backend-config=backend.hcl
   terraform apply -var alarm_email=<you@example.com>
   ```
   The services start with no image yet, so ECS shows failing tasks. That's expected.

4. **First deploy:** Actions → Deploy → *Run workflow*, then approve the `production` job.
   The job summary links to the ALB URL.

5. **Get the admin token:**
   ```bash
   aws secretsmanager get-secret-value --secret-id telemetry/admin-token --query SecretString --output text
   ```

## Everyday deploys
Merge to `main`, CI passes, the build job pushes the image, you approve, and it deploys.
Deploy time is printed at the end of the job (`deployed in Ns`). Record it in the README.

## Tear down (do this after demos)
```bash
cd infra/app && terraform destroy
```
The bootstrap stack (budget, state bucket, roles) costs almost nothing, so leave it.
To redeploy before an interview: `terraform apply`, then run the Deploy workflow. That takes
about 15 minutes; RDS creation is the slow part.

## Incidents

### API returns 503 "database unavailable"
1. Check RDS status: `aws rds describe-db-instances --db-instance-identifier telemetry --query 'DBInstances[0].DBInstanceStatus'`.
2. If it's `stopped` (AWS restarts stopped instances after 7 days, and you may have stopped
   it to save money): `aws rds start-db-instance --db-instance-identifier telemetry`.
3. No action is needed on the API. Tasks stay up (`/livez`) and recover on their own once
   the DB is back. Clients should retry batches with the same `Idempotency-Key`.

### Alert backlog growing
- Symptom: `alert_worker_backlog` climbing (Grafana), or alerts arriving late.
- Check worker logs: `aws logs tail /ecs/telemetry/worker --follow`.
- Short term: `aws ecs update-service --cluster telemetry --service worker --desired-count 2`.
  Two workers are safe (SKIP LOCKED), but per-device ordering isn't guaranteed (ADR 0002).

### Bad deploy
- The ECS circuit breaker rolls back automatically if new tasks never get healthy.
- Manual rollback: re-run the Deploy workflow on the previous good commit
  (Actions → Deploy → Run workflow, from that commit), or
  `aws ecs update-service --cluster telemetry --service api --task-definition telemetry-api:<previous-revision>`.
- If a migration failed, services were not updated. Fix the migration and redeploy.
  Migrations must stay compatible with the version already running (expand, then contract).

### Leaked admin token or device key
- **Admin token:** `terraform apply -replace=random_password.admin_token`, then force a new
  deployment of both services so they pick up the new secret.
- **Device key:** there is no key rotation endpoint yet (see the threat model). Delete the
  device row and re-register it.

## Local drills
```bash
docker compose up -d --build
scripts/db_outage_drill.sh          # 503 during the outage, measures time to recovery
docker compose --profile observability up -d   # Grafana on http://localhost:3000
```
