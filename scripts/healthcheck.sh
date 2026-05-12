#!/bin/sh

set -eu

BASE_URL="${1:-http://127.0.0.1:8000}"

check_endpoint() {
  endpoint="$1"
  label="$2"
  response=$(curl -fsS "$BASE_URL$endpoint")
  printf '%s\n' "$response" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
print(payload)
'
  echo "✓ $label"
}

check_endpoint "/health" "liveness"
check_endpoint "/ready" "readiness"