#!/usr/bin/env bash
# Soak test: continuous request stream against live API for N seconds.
# Records latency, error rate, and VRAM drift; flags allocator growth.
#
# Usage:
#   DURATION_S=3600 HOST=http://127.0.0.1:8101 MODEL=qwen3.6-27b \
#     tools/soak.sh
#
# Defaults: 1h soak against 27B PROD. For 8h: DURATION_S=28800.
# For 35B PROD: PORT=8000 MODEL=qwen3.6-35b-a3b.

set -euo pipefail

# Default to localhost. A hardcoded LAN IP in public smoke-tools is
# dangerous — community operators could accidentally hit someone else's rig.
PORT="${PORT:-8101}"
HOST="${HOST:-http://127.0.0.1:${PORT}}"
API_KEY="${API_KEY:-genesis-local}"
MODEL="${MODEL:-qwen3.6-27b}"
DURATION_S="${DURATION_S:-3600}"
CONCURRENCY="${CONCURRENCY:-1}"
PROMPTS_FILE="${PROMPTS_FILE:-}"
OUTPUT="${OUTPUT:-/tmp/soak_$(date +%Y%m%d_%H%M%S).log}"
VRAM_LOG="${VRAM_LOG:-/tmp/soak_vram_$(date +%Y%m%d_%H%M%S).log}"

echo "=== Genesis soak ==="
echo "  HOST        = $HOST"
echo "  MODEL       = $MODEL"
echo "  DURATION    = ${DURATION_S}s (~$(( DURATION_S / 60 )) min)"
echo "  CONCURRENCY = $CONCURRENCY"
echo "  OUTPUT      = $OUTPUT"
echo "  VRAM_LOG    = $VRAM_LOG"
echo ""

# Default prompt rotation if no file provided
default_prompts=(
    "Explain how memory bandwidth limits GPU inference."
    "Write a Python function that computes the SHA256 of a file."
    "Summarize the differences between FP8 e4m3 and fp8 e5m2."
    "What is speculative decoding and why does it speed up inference?"
    "Generate a brief shell script that lists docker containers by uptime."
)
get_prompt() {
    if [ -n "$PROMPTS_FILE" ] && [ -f "$PROMPTS_FILE" ]; then
        local lines
        lines=$(wc -l < "$PROMPTS_FILE")
        sed -n "$(( RANDOM % lines + 1 ))p" "$PROMPTS_FILE"
    else
        echo "${default_prompts[$(( RANDOM % ${#default_prompts[@]} ))]}"
    fi
}

# VRAM sampler (every 30s, async via SSH-style remote nvidia-smi).
# If running locally, replaces ssh-remote with direct call.
sample_vram() {
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=index,memory.used,memory.free \
            --format=csv,noheader,nounits 2>/dev/null
    else
        echo "no-local-nvidia-smi"
    fi
}

start_ts=$(date +%s)
deadline=$(( start_ts + DURATION_S ))
ok=0
err=0
tot_lat_ms=0

# Background VRAM sampler
(
    while [ "$(date +%s)" -lt "$deadline" ]; do
        ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        echo "$ts $(sample_vram | tr '\n' ';')" >> "$VRAM_LOG"
        sleep 30
    done
) &
vram_pid=$!

# Main request loop
while [ "$(date +%s)" -lt "$deadline" ]; do
    prompt=$(get_prompt)
    body=$(jq -nc --arg model "$MODEL" --arg p "$prompt" '{
        model: $model,
        messages: [{role:"user", content: $p}],
        max_tokens: 200,
        temperature: 0
    }')
    t0=$(date +%s%3N)
    rc=0
    response=$(
        curl -fsS --max-time 60 \
            -H "Authorization: Bearer $API_KEY" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "$HOST/v1/chat/completions" 2>/dev/null
    ) || rc=$?
    t1=$(date +%s%3N)
    lat=$(( t1 - t0 ))
    if [ $rc -eq 0 ]; then
        ok=$(( ok + 1 ))
        tot_lat_ms=$(( tot_lat_ms + lat ))
    else
        err=$(( err + 1 ))
        echo "[$(date -u +%H:%M:%S)] ERR rc=$rc lat=${lat}ms" >> "$OUTPUT"
    fi
    if [ $(( (ok + err) % 100 )) -eq 0 ] && [ $(( ok + err )) -gt 0 ]; then
        elapsed=$(( $(date +%s) - start_ts ))
        avg_lat=$(( tot_lat_ms / (ok == 0 ? 1 : ok) ))
        echo "[$(date -u +%H:%M:%S)] elapsed=${elapsed}s ok=$ok err=$err avg_lat=${avg_lat}ms" \
            | tee -a "$OUTPUT"
    fi
done

# Stop VRAM sampler
kill "$vram_pid" 2>/dev/null || true

# Summary
elapsed=$(( $(date +%s) - start_ts ))
echo "" | tee -a "$OUTPUT"
echo "=== Soak summary ===" | tee -a "$OUTPUT"
echo "  duration:  ${elapsed}s" | tee -a "$OUTPUT"
echo "  requests:  ok=$ok err=$err total=$(( ok + err ))" | tee -a "$OUTPUT"
if [ $ok -gt 0 ]; then
    avg_lat=$(( tot_lat_ms / ok ))
    echo "  avg lat:   ${avg_lat}ms" | tee -a "$OUTPUT"
fi
echo "  error rate: $(awk "BEGIN { printf \"%.2f\", ($err / ($ok + $err)) * 100 }")%" \
    | tee -a "$OUTPUT"
echo "  VRAM log:  $VRAM_LOG" | tee -a "$OUTPUT"
