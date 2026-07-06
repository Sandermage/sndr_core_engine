#!/bin/bash
# Canonical standalone sndr GUI daemon launcher (single-host / rig).
# Fixes two classes of "GUI can't find engine" + "memory Error: Not Found"
# that bite when the daemon is (re)created without the right env:
#   - engine detection: the vLLM engine on :8102 needs its API key, else the
#     probe gets 401 and falls back to an empty :8000.
#   - persistent memory: GENESIS_MEMORY_DSN -> pgvector, and psycopg (NOT in the
#     vLLM base image) must be pip-installed at boot, else it silently falls
#     back to the ephemeral in-memory store (empties on every restart).
# Override the engine/key/DSN via env before running. PROD engine is untouched.
set -euo pipefail
ENGINE_URL="${SNDR_OPENAI_BASE_URL:-http://127.0.0.1:8102/v1}"
ENGINE_KEY="${SNDR_ENGINE_API_KEY:-genesis-local}"
MEM_DSN="${GENESIS_MEMORY_DSN:-postgresql://genesis:genesis_mem_dev@127.0.0.1:55432/genesis_memory}"
# Path to the canonical sndr/ package dir (e.g. <your-repo>/sndr or the
# rig sync tree). Required — no operator-specific default is baked in.
SNDR_SRC="${SNDR_SRC_DIR:?set SNDR_SRC_DIR to the sndr package directory}"
IMAGE="${SNDR_DAEMON_IMAGE:-vllm/vllm-openai:nightly}"
docker rm -f sndr-daemon >/dev/null 2>&1 || true
docker run -d --name sndr-daemon --network host --restart unless-stopped \
  -e SNDR_OPENAI_BASE_URL="$ENGINE_URL" \
  -e SNDR_ENGINE_API_KEY="$ENGINE_KEY" \
  -e SNDR_METRICS_URL="${SNDR_METRICS_URL:-http://127.0.0.1:8102/metrics}" \
  -e GENESIS_MEMORY_DSN="$MEM_DSN" \
  -e GENESIS_MEMORY_EMBEDDER="${GENESIS_MEMORY_EMBEDDER:-hash}" \
  -e GENESIS_MEMORY_DIM="${GENESIS_MEMORY_DIM:-256}" \
  -e SNDR_ALLOW_ALL_ORIGINS=1 -e SNDR_RUNTIME_HOST=127.0.0.1 -e SNDR_GUI_PORT=8765 \
  -e SNDR_ADMIN_PASSWORD="${SNDR_ADMIN_PASSWORD:-123456}" -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$SNDR_SRC":/usr/local/lib/python3.12/dist-packages/sndr:ro \
  -v /nfs/genesis/models:/models:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --entrypoint sh "$IMAGE" \
  -c 'pip install --quiet "psycopg[binary]>=3.1" 2>&1 | tail -1; exec python3 -c "from sndr.product_api.legacy.http_app import run_server; run_server(host=\"0.0.0.0\", port=8765, enable_apply=False)"'
echo "sndr-daemon (re)created — engine=$ENGINE_URL, memory=pgvector"
