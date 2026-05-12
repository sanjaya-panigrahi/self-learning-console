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

post_json() {
  endpoint="$1"
  payload="$2"
  curl -fsS -X POST "$BASE_URL$endpoint" \
    -H 'Content-Type: application/json' \
    -d "$payload"
}

wait_for_ready

echo "Seeding indexed content..."
post_json "/api/admin/reindex" '{}'

echo "Seeding semantic cache..."
post_json "/api/admin/warm-cache/run" '{"force": false}'

echo "Seeding deploy-intelligence artifacts..."
post_json "/api/admin/deploy-intelligence/run" '{"force": false, "blocking": false}'

echo "✓ Seed workflow submitted"