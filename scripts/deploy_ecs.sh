#!/usr/bin/env bash
# Deploy an already-pushed image to ECS: run migrations, then roll the api and worker.
#
#   scripts/deploy_ecs.sh <image-uri>
#
# Reads cluster, subnets, etc. from the SSM parameter that Terraform writes, so nothing
# is hard-coded here. Needs: aws cli v2, jq, curl. Used by .github/workflows/deploy.yml,
# and runnable by hand with the same permissions.
set -euo pipefail

IMAGE="${1:?usage: deploy_ecs.sh <image-uri>}"
PARAM="${DEPLOY_CONFIG_PARAM:-/telemetry/deploy-config}"
started=$(date +%s)

cfg=$(aws ssm get-parameter --name "$PARAM" --query Parameter.Value --output text)
cluster=$(jq -r .cluster <<<"$cfg")
subnets=$(jq -r '.subnets | join(",")' <<<"$cfg")
sg=$(jq -r .security_group <<<"$cfg")
base_url=$(jq -r .base_url <<<"$cfg")
migrate_log=$(jq -r .migrate_log <<<"$cfg")

# Register a new revision of a task family with only the image swapped.
register() {
  local family=$1
  aws ecs describe-task-definition --task-definition "$family" --query taskDefinition |
    jq --arg img "$IMAGE" '
      .containerDefinitions[0].image = $img
      | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
            .compatibilities, .registeredAt, .registeredBy, .deregisteredAt)' \
      >"/tmp/td-$family.json"
  aws ecs register-task-definition --cli-input-json "file:///tmp/td-$family.json" \
    --query taskDefinition.taskDefinitionArn --output text
}

echo "==> registering task definitions for $IMAGE"
migrate_td=$(register "$(jq -r .task_families.migrate <<<"$cfg")")
api_td=$(register "$(jq -r .task_families.api <<<"$cfg")")
worker_td=$(register "$(jq -r .task_families.worker <<<"$cfg")")

echo "==> running migrations"
task=$(aws ecs run-task --cluster "$cluster" --task-definition "$migrate_td" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
  --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task"
exit_code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task" \
  --query 'tasks[0].containers[0].exitCode' --output text)
task_id=${task##*/}
aws logs get-log-events --log-group-name "$migrate_log" \
  --log-stream-name "migrate/migrate/$task_id" --query 'events[].message' --output text || true
if [[ "$exit_code" != "0" ]]; then
  echo "migration failed (exit $exit_code); services were not updated" >&2
  exit 1
fi

# Migrations must stay backward compatible with the running version (expand, then contract),
# because old tasks keep serving until the new ones are healthy.
echo "==> updating services"
aws ecs update-service --cluster "$cluster" --service "$(jq -r .services.worker <<<"$cfg")" \
  --task-definition "$worker_td" --query service.serviceName --output text
aws ecs update-service --cluster "$cluster" --service "$(jq -r .services.api <<<"$cfg")" \
  --task-definition "$api_td" --query service.serviceName --output text

echo "==> waiting for services to become stable"
aws ecs wait services-stable --cluster "$cluster" \
  --services "$(jq -r .services.api <<<"$cfg")" "$(jq -r .services.worker <<<"$cfg")"

echo "==> smoke check $base_url"
curl -fsS "$base_url/livez"
echo
curl -fsS "$base_url/healthz"
echo
code=$(curl -s -o /dev/null -w '%{http_code}' "$base_url/metrics")
[[ "$code" == "404" ]] || { echo "/metrics is publicly reachable (HTTP $code)" >&2; exit 1; }

echo "==> deployed in $(( $(date +%s) - started ))s"
