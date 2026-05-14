#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Genesis memory observability — snapshot+diff helper for bench harness.
#
# Combines two sources of truth:
#   1. nvidia-smi          — absolute per-GPU VRAM (MiB used/free/total)
#   2. vllm /metrics       — KV-cache usage_perc + cache_config (num_gpu_blocks,
#                            block_size, dtype). KV pool size derives from these.
#
# Designed for surgical memory work: snapshot before bench, snapshot after,
# diff to see exactly where MiB moved. Read-only — never touches container state.
#
# WHY NOT torch.cuda.memory_stats(): would need either a source-level edit
# to vllm core (rebuild) or a runtime monkey-patch (doesn't reach spawn'd
# workers — see feedback_genesis_patches_are_source_level memory). nvidia-smi
# + /metrics gives us 95% of the diagnostic value at 0% intrusion cost.
#
# Usage:
#   memory_observability.sh snapshot [host:port]              # JSON to stdout
#   memory_observability.sh diff <before.json> <after.json>   # human delta
#
# Author: Sandermage(Sander)-Barzov Aleksandr — Ukraine, Odessa.

set -euo pipefail

CMD="${1:-}"
DEFAULT_ENDPOINT="localhost:8000"

usage() {
    cat <<EOF
Usage:
  $0 snapshot [host:port]              JSON snapshot to stdout
  $0 diff <before.json> <after.json>   human-readable delta
EOF
    exit 1
}

snapshot() {
    local endpoint="${1:-$DEFAULT_ENDPOINT}"
    local ts gpu_json metrics_raw kv_usage cache_info num_blocks block_size kv_dtype
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # Per-GPU VRAM via nvidia-smi (handles 1..N GPUs uniformly)
    gpu_json=$(nvidia-smi \
        --query-gpu=index,memory.used,memory.free,memory.total \
        --format=csv,noheader,nounits \
        | awk -F', ' 'BEGIN{print "["} NR>1{print ","} {printf "  {\"id\":%d,\"used_mib\":%d,\"free_mib\":%d,\"total_mib\":%d}", $1, $2, $3, $4} END{print "\n]"}')

    # vllm /metrics (gracefully handle endpoint down)
    metrics_raw=$(curl -fs --max-time 3 "http://${endpoint}/metrics" 2>/dev/null || echo "")

    if [[ -z "$metrics_raw" ]]; then
        kv_usage="null"
        num_blocks="null"
        block_size="null"
        kv_dtype="null"
    else
        # vllm:kv_cache_usage_perc — single gauge value
        kv_usage=$(echo "$metrics_raw" | awk '/^vllm:kv_cache_usage_perc{/ {gsub(/.*} /,""); print; exit}')
        kv_usage="${kv_usage:-null}"

        # vllm:cache_config_info — labels include num_gpu_blocks, block_size, cache_dtype.
        # Note label proximity: regex must avoid mamba_ssm_cache_dtype, mamba_block_size,
        # _block_size_resolved, num_gpu_blocks_override siblings.
        cache_info=$(echo "$metrics_raw" | grep '^vllm:cache_config_info{' | head -1)
        num_blocks=$(echo "$cache_info" | sed -n 's/.*[,{]num_gpu_blocks="\([^"]*\)".*/\1/p')
        block_size=$(echo "$cache_info" | sed -n 's/.*[,{]block_size="\([^"]*\)".*/\1/p')
        kv_dtype=$(echo "$cache_info" | sed -n 's/.*[,{]cache_dtype="\([^"]*\)".*/\1/p')
        num_blocks="${num_blocks:-null}"
        block_size="${block_size:-null}"
        kv_dtype="${kv_dtype:-null}"
        # Quote string values for JSON (numbers stay bare)
        [[ "$kv_dtype" != "null" ]] && kv_dtype="\"$kv_dtype\""
    fi

    # Derived: KV pool token capacity (num_blocks × block_size).
    local kv_tokens="null"
    if [[ "$num_blocks" != "null" && "$block_size" != "null" ]]; then
        kv_tokens=$((num_blocks * block_size))
    fi

    cat <<EOF
{
  "ts": "$ts",
  "endpoint": "$endpoint",
  "gpu": $gpu_json,
  "vllm": {
    "kv_usage_perc": $kv_usage,
    "num_gpu_blocks": $num_blocks,
    "block_size": $block_size,
    "kv_pool_tokens": $kv_tokens,
    "kv_dtype": $kv_dtype
  }
}
EOF
}

diff_snapshots() {
    local before="$1"
    local after="$2"

    [[ -f "$before" && -f "$after" ]] || {
        echo "ERROR: snapshot files not found" >&2
        exit 1
    }

    # GPU delta — iterate by id to handle multi-GPU
    echo "=== GPU VRAM delta ==="
    jq -r --slurpfile a "$after" '
        .gpu[] as $b
        | ($a[0].gpu[] | select(.id == $b.id)) as $a_gpu
        | "[GPU \($b.id)]  used: \($b.used_mib) → \($a_gpu.used_mib) MiB  (Δ \(($a_gpu.used_mib - $b.used_mib) | tostring))   free: \($b.free_mib) → \($a_gpu.free_mib) MiB"
    ' "$before"

    echo ""
    echo "=== vllm KV cache ==="
    jq -r --slurpfile a "$after" '
        .vllm as $b | $a[0].vllm as $a_vllm
        | "  KV usage:        \($b.kv_usage_perc) → \($a_vllm.kv_usage_perc) (perc)",
          "  KV pool tokens:  \($b.kv_pool_tokens) → \($a_vllm.kv_pool_tokens)",
          "  KV dtype:        \($b.kv_dtype)"
    ' "$before"

    echo ""
    echo "=== window ==="
    jq -r --slurpfile a "$after" '"  before: \(.ts)  →  after: \($a[0].ts)  (endpoint: \(.endpoint))"' "$before"
}

case "$CMD" in
    snapshot)  snapshot "${2:-$DEFAULT_ENDPOINT}" ;;
    diff)      [[ $# -ge 3 ]] || usage; diff_snapshots "$2" "$3" ;;
    *)         usage ;;
esac
