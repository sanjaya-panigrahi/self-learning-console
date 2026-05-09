.PHONY: help build deploy deploy-trace-on deploy-trace-off reindex warm-cache warm-cache-blocking deploy-intelligence deploy-intelligence-blocking precompute-parallel watch-status clean

PROJECT_NAME := self-learning-console
DOCKER_COMPOSE := docker compose --env-file .env -f infra/docker/docker-compose.yml
API_PORT ?= 8000
WARM_CACHE_ON_DEPLOY ?= true
WARM_CACHE_BLOCKING ?= false
DEPLOY_AI_PRECOMPUTE_ON_DEPLOY ?= true
DEPLOY_AI_PRECOMPUTE_BLOCKING ?= false
DEPLOY_AI_GATE_ENFORCE ?= false

help:
	@echo "$(PROJECT_NAME)"
	@echo ""
	@echo "  make build    Fresh Docker build (clear cache + no-cache rebuild)"
	@echo "  make deploy   Start stack (build + run, default host port: 8000)"
	@echo "                Example: make deploy API_PORT=8001"
	@echo "  make deploy-trace-on   Deploy with LangSmith tracing enabled (demo mode)"
	@echo "  make deploy-trace-off  Deploy with LangSmith tracing disabled (local mode)"
	@echo "  make reindex           Run ingestion + index all documents"
	@echo "  make warm-cache        Trigger semantic warm-cache job via admin API"
	@echo "  make deploy-intelligence Trigger full AI precompute + benchmark gate"
	@echo "  make precompute-parallel Run reindex + warm-cache + deploy-intelligence"
	@echo "  make watch-status       Watch warm-cache + deploy-intelligence status"
	@echo "  make clean    Stop containers and remove volumes + local cache"

build:
	docker builder prune -af
	docker image rm -f docker-self-learning-console-api >/dev/null 2>&1 || true
	$(DOCKER_COMPOSE) build --no-cache --pull self-learning-console-api

deploy: build
	@# Remove stale fixed-name containers left from failed compose runs.
	docker rm -f self-learning-console-api self-learning-console-qdrant >/dev/null 2>&1 || true
	API_PORT=$(API_PORT) $(DOCKER_COMPOSE) up -d --force-recreate self-learning-console-api qdrant
	@if [ "$(WARM_CACHE_ON_DEPLOY)" = "true" ] && [ "$(WARM_CACHE_BLOCKING)" != "true" ] && [ "$(DEPLOY_AI_PRECOMPUTE_ON_DEPLOY)" = "true" ] && [ "$(DEPLOY_AI_PRECOMPUTE_BLOCKING)" != "true" ]; then \
		$(MAKE) precompute-parallel API_PORT=$(API_PORT); \
		echo "✓ Stack running"; \
		exit 0; \
	fi
	@if [ "$(WARM_CACHE_ON_DEPLOY)" = "true" ]; then \
		if [ "$(WARM_CACHE_BLOCKING)" = "true" ]; then \
			$(MAKE) warm-cache-blocking API_PORT=$(API_PORT); \
		else \
			$(MAKE) warm-cache API_PORT=$(API_PORT); \
		fi; \
	fi
	@if [ "$(DEPLOY_AI_PRECOMPUTE_ON_DEPLOY)" = "true" ]; then \
		if [ "$(DEPLOY_AI_PRECOMPUTE_BLOCKING)" = "true" ]; then \
			$(MAKE) deploy-intelligence-blocking API_PORT=$(API_PORT) DEPLOY_AI_GATE_ENFORCE=$(DEPLOY_AI_GATE_ENFORCE); \
		else \
			$(MAKE) deploy-intelligence API_PORT=$(API_PORT); \
		fi; \
	fi
	@echo "✓ Stack running"

precompute-parallel:
	@sh scripts/run-precompute-parallel.sh http://localhost:$(API_PORT)

reindex:
	@echo "Running reindex on http://localhost:$(API_PORT)"
	@curl -fsS -X POST "http://localhost:$(API_PORT)/api/admin/reindex" | \
		python3 -c 'import sys,json; d=json.load(sys.stdin); print("source_dir:", d.get("source_dir")); print("processed_files:", d.get("processed_files")); print("indexed_chunks:", d.get("indexed_chunks")); print("status:", d.get("status"))'

warm-cache:
	@echo "Triggering warm-cache job in background on http://localhost:$(API_PORT)"
	@nohup sh -c "for i in 1 2 3 4 5 6 7 8 9 10; do \
		curl -fsS -X POST 'http://localhost:$(API_PORT)/api/admin/warm-cache/run' \
			-H 'Content-Type: application/json' \
			-d '{\"force\": false}' && exit 0; \
		echo 'Warm-cache endpoint not ready yet (attempt '$$i'/10). Retrying...'; \
		sleep 2; \
	done; \
	echo 'Unable to trigger warm-cache job after retries'; \
	exit 0" >/tmp/self-learning-console-warm-cache.log 2>&1 </dev/null &
	@echo "Warm-cache trigger running asynchronously (see /tmp/self-learning-console-warm-cache.log)"

warm-cache-blocking:
	@echo "Triggering warm-cache job on http://localhost:$(API_PORT)"
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		curl -fsS -X POST "http://localhost:$(API_PORT)/api/admin/warm-cache/run" \
			-H "Content-Type: application/json" \
			-d '{"force": false}' && exit 0; \
		echo "Warm-cache endpoint not ready yet (attempt $$i/10). Retrying..."; \
		sleep 2; \
	done; \
	echo "Unable to trigger warm-cache job after retries"; \
	exit 1

deploy-intelligence:
	@echo "Triggering deploy-intelligence pipeline in background on http://localhost:$(API_PORT)"
	@nohup sh -c "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		curl -fsS 'http://localhost:$(API_PORT)/ready' >/dev/null && break; \
		echo 'API readiness not available yet (attempt '$$i'/15). Retrying...'; \
		sleep 2; \
		if [ $$i -eq 15 ]; then echo 'API readiness check failed after retries'; exit 0; fi; \
	done; \
	for i in 1 2 3 4 5 6 7 8 9 10; do \
		curl -fsS -X POST 'http://localhost:$(API_PORT)/api/admin/deploy-intelligence/run' \
			-H 'Content-Type: application/json' \
			-d '{\"force\": false, \"blocking\": false}' && exit 0; \
		echo 'Deploy-intelligence endpoint not ready yet (attempt '$$i'/10). Retrying...'; \
		sleep 2; \
	done; \
	echo 'Unable to trigger deploy-intelligence pipeline after retries'; \
	exit 0" >/tmp/self-learning-console-deploy-intel.log 2>&1 </dev/null &
	@echo "Deploy-intelligence trigger running asynchronously (see /tmp/self-learning-console-deploy-intel.log)"

deploy-intelligence-blocking:
	@echo "Triggering blocking deploy-intelligence pipeline on http://localhost:$(API_PORT)"
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		curl -fsS "http://localhost:$(API_PORT)/ready" >/dev/null && break; \
		echo "API readiness not available yet (attempt $$i/15). Retrying..."; \
		sleep 2; \
		if [ $$i -eq 15 ]; then echo "API readiness check failed after retries"; exit 1; fi; \
	done
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		curl -fsS -X POST "http://localhost:$(API_PORT)/api/admin/deploy-intelligence/run" \
			-H "Content-Type: application/json" \
			-d '{"force": false, "blocking": true}' >/tmp/self-learning-console-deploy-intel-last.json && break; \
		echo "Deploy-intelligence endpoint not ready yet (attempt $$i/10). Retrying..."; \
		sleep 2; \
		if [ $$i -eq 10 ]; then echo "Unable to trigger deploy-intelligence pipeline after retries"; exit 1; fi; \
	done
	@if [ "$(DEPLOY_AI_GATE_ENFORCE)" = "true" ]; then \
		python3 -c "import json,sys;d=json.load(open('/tmp/self-learning-console-deploy-intel-last.json'));ok=bool((((d.get('report') or {}).get('gate_passed'))));print('Deploy AI gate passed:',ok);sys.exit(0 if ok else 2)"; \
	fi

deploy-trace-on:
	LANGSMITH_ENABLED=true LANGSMITH_TRACING=true $(MAKE) deploy API_PORT=$(API_PORT)

deploy-trace-off:
	LANGSMITH_ENABLED=false LANGSMITH_TRACING=false $(MAKE) deploy API_PORT=$(API_PORT)

watch-status:
	sh scripts/watch-status.sh http://127.0.0.1:$(API_PORT) 180

clean:
	@TEMP_ENV_CREATED=0; \
	if [ ! -f .env ]; then \
		touch .env; \
		TEMP_ENV_CREATED=1; \
	fi; \
	$(DOCKER_COMPOSE) down -v; \
	STATUS=$$?; \
	if [ "$$TEMP_ENV_CREATED" = "1" ]; then \
		rm -f .env; \
	fi; \
	exit $$STATUS
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned"

.DEFAULT_GOAL := help
