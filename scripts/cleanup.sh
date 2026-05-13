#!/usr/bin/env bash
# cleanup.sh — Reset data, container caches, and wiki for a fresh rebuild.
#
# Usage:
#   ./scripts/cleanup.sh              # interactive (prompts for confirmation)
#   ./scripts/cleanup.sh --force      # skip confirmation prompt
#   ./scripts/cleanup.sh --cache-only # clear API caches only (no data deletion)
#   ./scripts/cleanup.sh --wiki-only  # clear wiki directory only
#
# What it cleans:
#   1. API semantic cache   — POST /api/admin/semantic-cache/clear
#   2. Retrieval search cache — POST /api/admin/retrieval-search-cache/clear
#   3. data/wiki/           — all generated wiki pages
#   4. data/indexes/        — knowledge cards, manifests, reports, eval sets
#   5. data/processed/      — processed document artefacts
#   6. data/traces/         — LLM trace logs
#   7. data/visual_previews/— visual preview thumbnails
#   8. data/qdrant/         — Qdrant vector storage (requires qdrant container restart)
#   9. data/raw/            — raw ingested copies (optional, prompted separately)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { printf "${CYAN}[cleanup]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}[  ok  ]${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[ warn ]${RESET} %s\n" "$*"; }
err()  { printf "${RED}[error ]${RESET} %s\n" "$*" >&2; }

# ── argument parsing ──────────────────────────────────────────────────────────
FORCE=false
CACHE_ONLY=false
WIKI_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --force)      FORCE=true ;;
    --cache-only) CACHE_ONLY=true ;;
    --wiki-only)  WIKI_ONLY=true ;;
    --help|-h)
      sed -n '2,20p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *)
      err "Unknown option: $arg  (use --help for usage)"
      exit 1 ;;
  esac
done

# ── confirmation ──────────────────────────────────────────────────────────────
if [[ "$FORCE" == false && "$CACHE_ONLY" == false && "$WIKI_ONLY" == false ]]; then
  printf "\n${BOLD}${RED}WARNING:${RESET} This will delete all local data, wiki pages, indexes, and\n"
  printf "         container cache state. Qdrant will be fully wiped.\n\n"
  printf "  Project: %s\n\n" "$PROJECT_ROOT"
  read -r -p "Type 'yes' to confirm: " CONFIRM
  if [[ "$CONFIRM" != "yes" ]]; then
    warn "Aborted."
    exit 0
  fi
  echo
fi

# ── helpers ───────────────────────────────────────────────────────────────────
api_clear_cache() {
  local name="$1" endpoint="$2"
  log "Clearing $name via API..."
  if curl -fsS -X POST "${API_BASE}${endpoint}" -o /dev/null 2>/dev/null; then
    ok "$name cleared"
  else
    warn "API unavailable — skipping $name (container may not be running)"
  fi
}

wipe_dir_contents() {
  local label="$1" dir="$2"
  if [[ -d "$dir" ]]; then
    find "$dir" -mindepth 1 -delete
    ok "$label cleared  ($dir)"
  else
    warn "$label directory not found — skipping  ($dir)"
  fi
}

# ── 1. API container caches ───────────────────────────────────────────────────
log "--- Container cache ---"
api_clear_cache "semantic cache"         "/api/admin/semantic-cache/clear"
api_clear_cache "retrieval search cache" "/api/admin/retrieval-search-cache/clear"
api_clear_cache "material insight cache" "/api/admin/material-insight-cache/clear"

# Flush Redis exact-cache (runs under the 'redis' compose profile)
log "Flushing Redis exact cache..."
if docker exec self-learning-console-redis redis-cli FLUSHALL &>/dev/null 2>&1; then
  ok "Redis flushed"
else
  warn "Redis container not running — skipping FLUSHALL"
fi

# Wipe warm-cache manifest so next warm-cache run starts from scratch
WARM_MANIFEST="$PROJECT_ROOT/data/indexes/warm_cache_manifest.json"
if [[ -f "$WARM_MANIFEST" ]]; then
  rm -f "$WARM_MANIFEST"
  ok "Warm-cache manifest removed"
fi

if [[ "$CACHE_ONLY" == true ]]; then
  ok "Cache-only mode complete."
  exit 0
fi

# ── 2. Wiki ───────────────────────────────────────────────────────────────────
log "--- Wiki ---"
wipe_dir_contents "wiki"    "$PROJECT_ROOT/data/wiki"

if [[ "$WIKI_ONLY" == true ]]; then
  ok "Wiki-only mode complete."
  exit 0
fi

# ── 3. Indexes & manifests ────────────────────────────────────────────────────
log "--- Indexes ---"
wipe_dir_contents "indexes" "$PROJECT_ROOT/data/indexes"

# ── 4. Processed artefacts ────────────────────────────────────────────────────
log "--- Processed artefacts ---"
wipe_dir_contents "processed" "$PROJECT_ROOT/data/processed"

# ── 5. Traces ─────────────────────────────────────────────────────────────────
log "--- Traces ---"
wipe_dir_contents "traces"    "$PROJECT_ROOT/data/traces"

# ── 6. Visual previews ────────────────────────────────────────────────────────
log "--- Visual previews ---"
wipe_dir_contents "visual_previews" "$PROJECT_ROOT/data/visual_previews"

# ── 7. Qdrant storage (requires container restart) ────────────────────────────
log "--- Qdrant vector storage ---"
QDRANT_STORAGE="$PROJECT_ROOT/data/qdrant"
if [[ -d "$QDRANT_STORAGE" ]] && [[ -n "$(ls -A "$QDRANT_STORAGE" 2>/dev/null)" ]]; then
  log "Stopping qdrant container to safely wipe storage..."
  if docker stop self-learning-console-qdrant &>/dev/null; then
    wipe_dir_contents "qdrant storage" "$QDRANT_STORAGE"
    log "Restarting qdrant container..."
    if docker start self-learning-console-qdrant &>/dev/null; then
      ok "Qdrant restarted with empty storage"
    else
      warn "Could not restart qdrant — start it manually: docker start self-learning-console-qdrant"
    fi
  else
    warn "Could not stop qdrant container — skipping storage wipe (container may not exist)"
  fi
else
  ok "Qdrant storage already empty — nothing to wipe"
fi

# ── 8. Raw data (optional) ────────────────────────────────────────────────────
RAW_DIR="$PROJECT_ROOT/data/raw"
if [[ -d "$RAW_DIR" ]] && [[ -n "$(ls -A "$RAW_DIR" 2>/dev/null)" ]]; then
  printf "\n"
  read -r -p "Also wipe data/raw/ (original ingested copies)? [y/N] " WIPE_RAW
  if [[ "$WIPE_RAW" =~ ^[Yy]$ ]]; then
    wipe_dir_contents "raw data" "$RAW_DIR"
  else
    log "Skipping data/raw/"
  fi
fi

# ── 9. Restart API so in-memory caches are fully flushed ─────────────────────
log "--- API container ---"
if docker restart self-learning-console-api &>/dev/null; then
  log "Waiting for API to become healthy..."
  for i in $(seq 1 12); do
    sleep 3
    if curl -fsS "${API_BASE}/api/health" -o /dev/null 2>/dev/null; then
      ok "API is healthy"
      break
    fi
    [[ "$i" -eq 12 ]] && warn "API did not become healthy within 36s — check container logs"
  done
else
  warn "Could not restart API container — skipping (container may not exist)"
fi

# ── summary ───────────────────────────────────────────────────────────────────
printf "\n${BOLD}${GREEN}Cleanup complete.${RESET}\n"
printf "Run 'make deploy' or trigger an ingestion job to rebuild from scratch.\n\n"
