#!/usr/bin/env bash
# Long-context smoke test for Genesis PROD configs.
#
# Probes the live API at progressively larger context sizes and records
# the largest stable input length (no OOM, no truncation, response
# survives the full window). One-shot bench; complements the soak.
#
# Usage:
#   HOST=http://127.0.0.1:8101 API_KEY=genesis-local MODEL=qwen3.6-27b \
#     tools/long_ctx_smoke.sh
#
# Defaults target 27B PROD on the homelab rig. Override env vars for
# other configs (35B PORT=8000 MODEL=qwen3.6-35b-a3b).

set -euo pipefail

# Default to localhost; community operators must explicitly set
# HOST=http://<host>:<port>. Hardcoding a private LAN IP in public
# tools breaks them (hits someone else's rig instead of your own).
PORT="${PORT:-8101}"
HOST="${HOST:-http://127.0.0.1:${PORT}}"
API_KEY="${API_KEY:-genesis-local}"
MODEL="${MODEL:-qwen3.6-27b}"
START_CTX="${START_CTX:-4096}"
MAX_CTX="${MAX_CTX:-131072}"
STEP="${STEP:-2}"   # multiplicative factor between probes
OUTPUT="${OUTPUT:-/tmp/long_ctx_smoke_$(date +%Y%m%d_%H%M%S).log}"

echo "=== Genesis long-ctx smoke ==="
echo "  HOST   = $HOST"
echo "  MODEL  = $MODEL"
echo "  START  = $START_CTX"
echo "  MAX    = $MAX_CTX"
echo "  STEP   = ×$STEP"
echo "  OUTPUT = $OUTPUT"
echo ""

# Generate a prompt of N tokens using simple repetition. The actual token
# count depends on the tokenizer; the heuristic ~4 chars/token is close
# enough for smoke purposes (we treat under-shoot as "fits", over-shoot
# would fail at vllm side and we'd back off).
gen_prompt() {
    local target_tokens=$1
    local chars=$(( target_tokens * 4 ))
    yes "The quick brown fox jumps over the lazy dog." 2>/dev/null \
        | head -c "$chars"
}

ctx=$START_CTX
last_pass=0
while [ "$ctx" -le "$MAX_CTX" ]; do
    echo "[probe ctx≈$ctx tokens]"
    prompt=$(gen_prompt "$ctx")
    body=$(jq -nc --arg model "$MODEL" --arg p "$prompt" '{
        model: $model,
        messages: [{role:"user", content: $p}],
        max_tokens: 16,
        temperature: 0
    }')
    rc=0
    response=$(
        curl -fsS --max-time 600 \
            -H "Authorization: Bearer $API_KEY" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "$HOST/v1/chat/completions" 2>&1
    ) || rc=$?
    if [ $rc -ne 0 ]; then
        echo "  FAIL (rc=$rc) — backing off; last stable=$last_pass" \
            | tee -a "$OUTPUT"
        break
    fi
    finish=$(echo "$response" | jq -r '.choices[0].finish_reason // "?"')
    content_len=$(echo "$response" | jq -r '.choices[0].message.content // "" | length')
    echo "  ok  finish=$finish content_chars=$content_len" \
        | tee -a "$OUTPUT"
    last_pass=$ctx
    ctx=$(( ctx * STEP ))
done

echo ""
echo "=== Summary ==="
echo "  Largest stable context: $last_pass tokens"
echo "  Log: $OUTPUT"
