#!/bin/bash
# Run reindex, warm-cache and deploy-intelligence jobs with feedback

BASE_URL="${1:-http://127.0.0.1:8000}"
RETRIES=10

trigger_reindex() {
    for i in $(seq 1 $RETRIES); do
        result=$(curl -fsS -X POST "$BASE_URL/api/admin/reindex" \
            -H 'Content-Type: application/json' 2>&1)
        if [ $? -eq 0 ]; then
            files=$(echo "$result" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("processed_files",0))' 2>/dev/null || echo '?')
            chunks=$(echo "$result" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("indexed_chunks",0))' 2>/dev/null || echo '?')
            echo "✓ reindex completed: $files files, $chunks chunks"
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
trigger_reindex

echo "Step 2/3: Starting warm-cache + deploy-intelligence in parallel..."
trigger_warm_cache &
trigger_deploy_intelligence &
wait
echo "All jobs submitted. Check status with: make watch-status"
