#!/bin/sh

BASE_URL="${1:-http://127.0.0.1:8000}"
INTERVAL_SECONDS="${2:-180}"
MODE="${3:-loop}"

print_warm_cache() {
  echo "=== warm-cache ==="
  curl -fsS "$BASE_URL/api/admin/warm-cache/status" | python3 -c '
import json
import sys

d = json.load(sys.stdin)
print("state:", d.get("state", "-"))
print("docs:", f"{d.get('"'"'docs_processed'"'"', 0)}/{d.get('"'"'docs_total'"'"', 0)}")
print("entries_written:", d.get("entries_written", 0))
errors = d.get("errors", []) or []
print("errors:", len(errors))
if errors:
    print("first_error:", str(errors[0])[:200])
'
}

print_deploy_intelligence() {
  echo "=== Knowledge Builder ==="
  curl -fsS "$BASE_URL/api/admin/deploy-intelligence/status" | python3 -c '
import json
import sys
import time

d = json.load(sys.stdin)
started = d.get("started_at", 0)
elapsed = int(time.time() - started) if started else 0
print("state:", d.get("state", "-"))
print("stage:", d.get("current_stage", "-"))
print("progress:", f"{d.get('"'"'completion_percent'"'"', 0)}%")
print("elapsed_sec:", elapsed)
errors = d.get("errors", []) or []
print("errors:", len(errors))
for stage in d.get("stages", []):
    print(f"- {stage.get('"'"'name'"'"')}: {stage.get('"'"'state'"'"')} {stage.get('"'"'details'"'"', {})}")
'
}

print_snapshot() {
  clear
  date
  echo
  print_warm_cache || echo "warm-cache status unavailable"
  echo
  print_deploy_intelligence || echo "deploy-intelligence status unavailable"
}

while true; do
  print_snapshot

  if [ "$MODE" = "--once" ]; then
    exit 0
  fi

  echo
  echo "Next refresh in ${INTERVAL_SECONDS} seconds..."
  sleep "$INTERVAL_SECONDS"
done