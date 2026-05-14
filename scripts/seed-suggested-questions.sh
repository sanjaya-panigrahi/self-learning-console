#!/bin/sh
# seed-suggested-questions.sh
# Retrieves answers for all suggested questions across all indexed documents
# and pre-warms the semantic cache. When a user later clicks a suggested
# question in the UI the answer is served instantly from cache.
#
# Usage:
#   ./scripts/seed-suggested-questions.sh [BASE_URL] [--force] [--concurrency N]
#
# Options:
#   BASE_URL       API base URL (default: http://127.0.0.1:8000)
#   --force        Re-seed even if a question is already cached
#   --concurrency  Number of parallel question requests (default: 3)
#
# The script runs inside Docker when the container is accessible, otherwise
# it calls the API directly over HTTP.

set -eu

BASE_URL="${1:-http://127.0.0.1:8000}"
FORCE=false
CONCURRENCY=3

# Parse remaining args
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --force)       FORCE=true ;;
    --concurrency) shift; CONCURRENCY="${1:-3}" ;;
  esac
  shift || true
done

RETRIES=12
POST_RETRIES=5

wait_for_ready() {
  echo "Waiting for API to be ready at ${BASE_URL} ..."
  for i in $(seq 1 "$RETRIES"); do
    if curl -fsS "${BASE_URL}/ready" >/dev/null 2>&1; then
      echo "API ready."
      return 0
    fi
    echo "  Not ready yet (attempt $i/$RETRIES). Retrying in 3s..."
    sleep 3
  done
  echo "ERROR: API readiness check failed after $RETRIES attempts."
  exit 1
}

wait_for_ready

echo ""
echo "Running suggested-question seeder (force=$FORCE, concurrency=$CONCURRENCY) ..."
echo ""

# Use a temp file so we can show the raw body on error
TMP_RESPONSE="$(mktemp)"
HTTP_CODE=""
LAST_CURL_EXIT=0

for i in $(seq 1 "$POST_RETRIES"); do
  LAST_CURL_EXIT=0
  HTTP_CODE=""
  if HTTP_CODE=$(curl -sS -o "$TMP_RESPONSE" -w "%{http_code}" \
    --connect-timeout 8 \
    --max-time 180 \
    -X POST "${BASE_URL}/api/admin/seed-suggested-questions" \
    -H 'Content-Type: application/json' \
    -d "{\"force\": ${FORCE}, \"concurrency\": ${CONCURRENCY}}"); then
    LAST_CURL_EXIT=0
  else
    LAST_CURL_EXIT=$?
  fi

  if [ "$LAST_CURL_EXIT" -eq 0 ] && [ "$HTTP_CODE" = "200" ]; then
    break
  fi

  if [ "$i" -lt "$POST_RETRIES" ]; then
    if [ "$LAST_CURL_EXIT" -ne 0 ]; then
      echo "  Seeder request failed (curl exit $LAST_CURL_EXIT, attempt $i/$POST_RETRIES). Retrying in 3s..."
    else
      echo "  Seeder request returned HTTP $HTTP_CODE (attempt $i/$POST_RETRIES). Retrying in 3s..."
    fi
    sleep 3
  fi
done

if [ "$LAST_CURL_EXIT" -ne 0 ]; then
  echo "ERROR: seeder request failed after $POST_RETRIES attempts (curl exit $LAST_CURL_EXIT)."
  rm -f "$TMP_RESPONSE"
  exit 1
fi

if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: API returned HTTP $HTTP_CODE"
  echo "Response body:"
  cat "$TMP_RESPONSE"
  rm -f "$TMP_RESPONSE"
  exit 1
fi

python3 - "$TMP_RESPONSE" << 'PYEOF'
import json, sys
from pathlib import Path

try:
  d = json.loads(Path(sys.argv[1]).read_text())
except Exception as e:
    print("ERROR: could not parse response:", e)
    sys.exit(1)
print("status     :", d.get("status", "-"))
print("sources    :", d.get("sources_processed", 0))
print("questions  :", d.get("questions_found", 0))
print("cached     :", d.get("answers_cached", 0))
print("skipped    :", d.get("skipped", 0))
print("errors     :", d.get("errors", 0))
if d.get("elapsed_seconds"):
    print("elapsed    :", d["elapsed_seconds"], "s")
if d.get("error_details"):
    print("error detail:", d["error_details"][0])
if d.get("detail"):
    print("detail     :", d["detail"])
PYEOF

rm -f "$TMP_RESPONSE"

echo ""
echo "Done. Suggested questions are now pre-cached."
