#!/bin/sh

set -eu

BASE_URL="${1:-http://127.0.0.1:8000}"
SEED_CONCURRENCY="${2:-3}"
RETRIES=20

wait_for_ready() {
  echo "Waiting for API to be ready at ${BASE_URL} ..."
  for i in $(seq 1 "$RETRIES"); do
    if curl -fsS "${BASE_URL}/ready" >/dev/null 2>&1 || curl -fsS "${BASE_URL}/api/ready" >/dev/null 2>&1; then
      echo "API ready."
      return 0
    fi
    echo "  Not ready yet (attempt $i/$RETRIES). Retrying in 3s..."
    sleep 3
  done
  echo "ERROR: API readiness check failed after $RETRIES attempts."
  return 1
}

wait_for_ready

echo ""
echo "Generating material insights for all indexed documents ..."
echo ""

SOURCES_FILE="$(mktemp)"
trap 'rm -f "$SOURCES_FILE"' EXIT INT TERM

curl -fsS "${BASE_URL}/api/admin/retrieval-overview" \
  | jq -r '.materials[]? | select((.status // "") == "indexed") | .source' > "$SOURCES_FILE"

TOTAL="$(wc -l < "$SOURCES_FILE" | tr -d ' ')"
if [ "$TOTAL" = "0" ]; then
  echo "No indexed materials found in retrieval overview."
  exit 1
fi

echo "Indexed sources found: $TOTAL"

SUCCESS=0
FAIL=0
INDEX=0
PER_DOC_RETRIES=2
PER_DOC_TIMEOUT=120
PER_DOC_CONNECT_TIMEOUT=8

while IFS= read -r SOURCE; do
  INDEX=$((INDEX + 1))
  [ -n "$SOURCE" ] || continue

  PAYLOAD="$(jq -nc --arg source "$SOURCE" '{source:$source,domain_context:"",use_cache:true}')"

  DOC_OK=0
  TRY=1
  while [ "$TRY" -le "$PER_DOC_RETRIES" ]; do
    if curl -fsS \
      --connect-timeout "$PER_DOC_CONNECT_TIMEOUT" \
      --max-time "$PER_DOC_TIMEOUT" \
      -X POST "${BASE_URL}/api/admin/material-insight" \
      -H 'Content-Type: application/json' \
      -d "$PAYLOAD" >/dev/null; then
      DOC_OK=1
      break
    fi
    TRY=$((TRY + 1))
    if [ "$TRY" -le "$PER_DOC_RETRIES" ]; then
      echo "[$INDEX/$TOTAL] retry $TRY/$PER_DOC_RETRIES - $SOURCE"
    fi
  done

  if [ "$DOC_OK" -eq 1 ]; then
    SUCCESS=$((SUCCESS + 1))
    echo "[$INDEX/$TOTAL] OK  - $SOURCE"
  else
    FAIL=$((FAIL + 1))
    echo "[$INDEX/$TOTAL] FAIL - $SOURCE"
  fi
done < "$SOURCES_FILE"

echo ""
echo "Insight generation summary: ok=$SUCCESS fail=$FAIL total=$TOTAL"
echo ""

echo "Running suggested-question seeder ..."
sh scripts/seed-suggested-questions.sh "$BASE_URL" --concurrency "$SEED_CONCURRENCY"

echo ""
echo "Done. Full all-documents suggested-question seeding completed."
