#!/bin/bash
# Run reindex, warm-cache and deploy-intelligence jobs with feedback

BASE_URL="${1:-http://127.0.0.1:8000}"
RETRIES=10

wait_for_api_ready() {
    local attempts=${1:-30}
    for i in $(seq 1 "$attempts"); do
        if curl -fsS "$BASE_URL/ready" >/dev/null 2>&1 || curl -fsS "$BASE_URL/api/ready" >/dev/null 2>&1; then
            echo "✓ API readiness check passed"
            return 0
        fi
        echo "API not ready yet (attempt $i/$attempts), retrying..."
        sleep 2
    done
    echo "✗ API readiness failed after $attempts attempts"
    return 1
}

wait_for_reindex_completion() {
    local attempts=${1:-180}
    for i in $(seq 1 "$attempts"); do
        status=$(curl -fsS "$BASE_URL/api/admin/ingestion/status" 2>/dev/null | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("state","unknown"))
except Exception:
    print("unknown")' 2>/dev/null)

        if [ "$status" = "completed" ]; then
            report=$(curl -fsS "$BASE_URL/api/admin/report" 2>/dev/null || echo '{}')
            files=$(echo "$report" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("processed_files",0))
except Exception:
    print("?")' 2>/dev/null)
            chunks=$(echo "$report" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("indexed_chunks",0))
except Exception:
    print("?")' 2>/dev/null)
            echo "✓ reindex completed: $files files, $chunks chunks"
            return 0
        fi

        if [ "$status" = "failed" ]; then
            echo "✗ reindex failed"
            return 1
        fi

        echo "reindex state=$status (poll $i/$attempts)"
        sleep 2
    done

    echo "✗ reindex did not complete in time"
    return 1
}

trigger_reindex() {
    for i in $(seq 1 $RETRIES); do
        result=$(curl -fsS -X POST "$BASE_URL/api/admin/reindex" \
            -H 'Content-Type: application/json' 2>&1)
        if [ $? -eq 0 ]; then
            echo "✓ reindex triggered"
            wait_for_reindex_completion || return 1
            return 0
        fi
        echo "reindex attempt $i/$RETRIES failed, retrying..."
        sleep 3
    done
    echo "✗ reindex failed after $RETRIES retries"
    return 1
}

trigger_warm_cache() {
    for i in $(seq 1 $RETRIES); do
        if curl -fsS -X POST "$BASE_URL/api/admin/warm-cache/run" \
            -H 'Content-Type: application/json' \
            -d '{"force": false}' >/dev/null 2>&1; then
            echo "✓ warm-cache triggered"
            return 0
        fi
        echo "warm-cache attempt $i/$RETRIES failed, retrying..."
        sleep 2
    done
    echo "✗ warm-cache trigger failed after $RETRIES retries"
    return 1
}

trigger_deploy_intelligence() {
    for i in $(seq 1 $RETRIES); do
        if curl -fsS -X POST "$BASE_URL/api/admin/deploy-intelligence/run" \
            -H 'Content-Type: application/json' \
            -d '{"force": false, "blocking": false}' >/dev/null 2>&1; then
            echo "✓ deploy-intelligence triggered"
            return 0
        fi
        echo "deploy-intelligence attempt $i/$RETRIES failed, retrying..."
        sleep 2
    done
    echo "✗ deploy-intelligence trigger failed after $RETRIES retries"
    return 1
}

echo "Step 1/3: Running reindex (must complete before wiki/cache can run)..."
wait_for_api_ready || exit 1
trigger_reindex

echo "Step 2/3: Starting warm-cache + deploy-intelligence in parallel..."
trigger_warm_cache &
trigger_deploy_intelligence &
wait
echo "All jobs submitted. Check status with: make watch-status"
