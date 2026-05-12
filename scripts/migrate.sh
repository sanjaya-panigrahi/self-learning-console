#!/bin/sh

set -eu

BASE_URL="${1:-http://127.0.0.1:8000}"
RETRIES=10

wait_for_ready() {
  for i in $(seq 1 "$RETRIES"); do
    if curl -fsS "$BASE_URL/ready" >/dev/null 2>&1; then
      return 0
    fi
    echo "API not ready yet (attempt $i/$RETRIES). Retrying..."
    sleep 2
  done
  echo "API readiness check failed after retries"
  return 1
}

wait_for_ready

echo "Running blocking deploy-intelligence refresh..."
curl -fsS -X POST "$BASE_URL/api/admin/deploy-intelligence/run" \
  -H 'Content-Type: application/json' \
  -d '{"force": false, "blocking": true}'

echo "✓ Migration workflow completed"