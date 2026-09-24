#!/usr/bin/env bash
# Kill the database on purpose and check the API fails cleanly, then measure recovery.
#
# Needs the compose stack running (docker compose up -d). Prints one result line to paste
# into README "Results". Measures the local Docker stack: label it that way.
set -euo pipefail

URL="${URL:-http://localhost:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-dev-admin-token}"

now_ms() { python3 -c 'import time; print(int(time.time() * 1000))'; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

key=$(curl -sf -X POST "$URL/devices" -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d "{\"name\":\"drill-$(date +%s)\"}" |
  python3 -c 'import sys, json; print(json.load(sys.stdin)["api_key"])')
post_reading() {
  status -X POST "$URL/readings" -H "X-API-Key: $key" -H 'Content-Type: application/json' \
    -d "{\"metric\":\"drill\",\"value\":1,\"ts\":\"$(python3 -c 'from datetime import datetime, UTC; print(datetime.now(UTC).isoformat())')\"}"
}

echo "baseline: /healthz=$(status "$URL/healthz") ingest=$(post_reading)"

echo "stopping db..."
docker compose stop db >/dev/null
sleep 2
during_ingest=$(post_reading)
during_health=$(status "$URL/healthz")
during_live=$(status "$URL/livez")
echo "during outage: ingest=$during_ingest /healthz=$during_health /livez=$during_live"

fail=0
[[ "$during_ingest" == "503" ]] || { echo "FAIL: ingest should return 503 while the DB is down"; fail=1; }
[[ "$during_health" == "503" ]] || { echo "FAIL: /healthz should return 503 while the DB is down"; fail=1; }
[[ "$during_live" == "200" ]] || { echo "FAIL: /livez should stay 200 (process is fine)"; fail=1; }

echo "starting db..."
start=$(now_ms)
docker compose start db >/dev/null
until [[ "$(post_reading)" =~ ^20[01]$ ]]; do
  sleep 0.2
  if (( $(now_ms) - start > 120000 )); then echo "FAIL: no recovery within 120 s"; exit 1; fi
done
recovered=$(( $(now_ms) - start ))

echo
echo "RESULT $(date -u +%Y-%m-%d): DB restart -> first successful ingest in $((recovered / 1000)).$(( (recovered % 1000) / 100 ))s (local Docker; includes Postgres startup)"
exit $fail
