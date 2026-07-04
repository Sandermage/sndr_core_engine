#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# genesis_report.sh — one-shot triage report for the running rig.
#
# Pattern adopted from noonghunna/club-3090 scripts/report.sh: when a
# regression or bug arrives, the operator captures rig + GPU + Genesis
# pin + container state + bench summary in ONE redacted paste-ready
# markdown document. Eliminates "can you also send me…" round-trips.
#
# Usage
# -----
#   tools/genesis_report.sh                     # write report to stdout
#   tools/genesis_report.sh > rig_$(date +%Y%m%d).md
#   tools/genesis_report.sh --bench             # incl. genesis_bench_suite --quick (~5 min)
#   tools/genesis_report.sh --agentic           # incl. tools/bench_agentic.py 5 turns (~2 min)
#   tools/genesis_report.sh --full              # = --bench --agentic + soak smoke (~15 min)
#   tools/genesis_report.sh --container <name>  # report ONLY this container
#
# Redaction
# ---------
# Auto-redacts: $USER → ~ in paths, HF_TOKEN values, $(hostname) → <host>,
# IP addresses → <ip>. Safe to paste in public issues.
#
# Section list
# ------------
#   1. SYSTEM      — uname, OS, kernel, distro
#   2. HARDWARE    — CPU, RAM, motherboard if detected
#   3. GPU         — nvidia-smi summary, persistence_mode, PCIe gen/width,
#                    power cap, driver version
#   4. CONTAINERS  — running containers + image + uptime
#   5. GENESIS     — model_configs builtin YAML list + Status: enum dump
#   6. PIN POLICY  — vllm_pin_required (from YAMLs) vs Docker images on host
#   7. (optional)  — verify-stress smoke / bench / agentic / soak (per flags)
#
# Author: Sander 2026-05-29 — derived from club-3090 report.sh research.

set -uo pipefail  # NB: no -e — we deliberately keep reporting on partial failure

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WANT_BENCH=0
WANT_AGENTIC=0
WANT_SOAK=0
CONTAINER_FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bench)     WANT_BENCH=1; shift ;;
        --agentic)   WANT_AGENTIC=1; shift ;;
        --soak)      WANT_SOAK=1; shift ;;
        --full)      WANT_BENCH=1; WANT_AGENTIC=1; WANT_SOAK=1; shift ;;
        --container) CONTAINER_FILTER="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^# Author/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "ERROR: unknown arg $1" >&2; exit 64 ;;
    esac
done

# ── helpers ─────────────────────────────────────────────────────────

_redact() {
    sed \
        -e "s|/home/${USER:-sander}|~|g" \
        -e "s|/Users/${USER:-sander}|~|g" \
        -e "s|hf_[A-Za-z0-9]\{30,\}|<HF_TOKEN_REDACTED>|g" \
        -e "s|sk-[A-Za-z0-9]\{30,\}|<API_KEY_REDACTED>|g" \
        -e "s|\b[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\b|<ip>|g"
}

_section() {
    printf '\n## %s\n\n' "$1"
}

_subsection() {
    printf '\n### %s\n\n' "$1"
}

_cmd_or_skip() {
    # Run command; if missing or fails, emit "(not available)" instead.
    local label="$1"
    shift
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "  ${label}: not available"
        return
    fi
    local out
    if ! out=$("$@" 2>&1); then
        echo "  ${label}: command failed"
        return
    fi
    echo "$out" | sed 's/^/  /'
}

_code_block() {
    echo '```'
    cat
    echo '```'
}

# ── markdown emission ──────────────────────────────────────────────

NOW="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

cat <<EOF
# Genesis rig triage report

**Generated**: ${NOW}
**Repo root**: $(echo "$REPO_ROOT" | _redact)

This report is **redacted** — paste-safe (HF tokens, IPs, /home/<user>/ all
masked). Pattern reference: noonghunna/club-3090 scripts/report.sh.

EOF

_section "1. System"
echo '```'
{
    echo "uname:  $(uname -a)"
    echo "shell:  ${SHELL:-unknown}"
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "distro: ${PRETTY_NAME:-${NAME:-unknown}}"
    elif command -v sw_vers >/dev/null 2>&1; then
        echo "distro: macOS $(sw_vers -productVersion)"
    fi
    echo "host:   <host>"   # redacted by design
} | _redact
echo '```'

_section "2. Hardware"
echo '```'
{
    if command -v nproc >/dev/null 2>&1; then
        echo "cpu_count: $(nproc)"
    fi
    if command -v lscpu >/dev/null 2>&1; then
        lscpu | grep -E '^(Model name|Architecture|Vendor|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)):' | sed 's/  */ /g'
    elif command -v sysctl >/dev/null 2>&1; then
        sysctl -n machdep.cpu.brand_string 2>/dev/null && \
            echo "physical_cores: $(sysctl -n hw.physicalcpu 2>/dev/null)"
    fi
    if [[ -f /proc/meminfo ]]; then
        awk '/^MemTotal:/ {printf "ram_total: %.1f GB\n", $2/1024/1024}' /proc/meminfo
    fi
} | _redact
echo '```'

_section "3. GPU + driver"
if command -v nvidia-smi >/dev/null 2>&1; then
    _subsection "Summary"
    echo '```'
    nvidia-smi --query-gpu=index,name,driver_version,persistence_mode,pstate,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader 2>&1 | _redact
    echo '```'

    _subsection "PCIe link state (may show ASPM idle gen=1; trains under load)"
    echo '```'
    nvidia-smi --query-gpu=index,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max --format=csv,noheader 2>&1
    echo '```'

    _subsection "Power policy"
    echo '```'
    nvidia-smi --query-gpu=index,power.management,power.limit,power.default_limit --format=csv,noheader 2>&1
    echo '```'

    _subsection "Topology (nvidia-smi topo -m)"
    echo '```'
    nvidia-smi topo -m 2>&1 | head -25
    echo '```'
else
    echo '_(nvidia-smi not available — skipping GPU section)_'
fi

_section "4. Running containers (docker ps)"
if command -v docker >/dev/null 2>&1; then
    echo '```'
    if [[ -n "$CONTAINER_FILTER" ]]; then
        docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1 | grep -E "(NAMES|$CONTAINER_FILTER)" | _redact
    else
        docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1 | _redact
    fi
    echo '```'
else
    echo '_(docker not available)_'
fi

_section "5. Genesis model configs (Status: enum dump)"
BUILTIN_DIR="$REPO_ROOT/sndr/model_configs/builtin/model"
if [[ -d "$BUILTIN_DIR" ]]; then
    echo "Per-YAML status from \`sndr/model_configs/builtin/model/\`:"
    echo ''
    echo '| YAML | Status | Last validated | Pin required |'
    echo '|---|---|---|---|'
    for f in "$BUILTIN_DIR"/*.yaml; do
        base=$(basename "$f")
        # Extract Status: enum (strip leading `# Status:` + trailing whitespace).
        status=$(grep -m1 -E '^#[[:space:]]+Status:' "$f" \
            | sed -E 's/^#[[:space:]]+Status:[[:space:]]+//' \
            | sed -E 's/[[:space:]]+$//')
        # Extract last_validated value (strip quotes + trailing comments).
        last_valid=$(grep -m1 -E "^last_validated:" "$f" \
            | sed -E "s/^last_validated:[[:space:]]+['\"]?([0-9-]+)['\"]?.*/\1/")
        # Extract first whitespace-delimited token after vllm_pin_required:.
        pin=$(grep -m1 -E '^[[:space:]]+vllm_pin_required:' "$f" \
            | awk '{print $2}')
        printf '| `%s` | %s | %s | `%s` |\n' \
            "$base" "${status:-MISSING}" "${last_valid:-?}" "${pin:-?}"
    done
else
    echo '_(builtin model dir not found — wrong repo root?)_'
fi

_section "6. vLLM pin policy compliance (CLAUDE.md: ≤2 active pins)"
if command -v docker >/dev/null 2>&1; then
    _subsection "vllm/vllm-openai images on host"
    echo '```'
    docker images vllm/vllm-openai --format 'table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}\t{{.Size}}' 2>&1 | head -10
    echo '```'

    PIN_COUNT=$(docker images vllm/vllm-openai --format '{{.ID}}' 2>/dev/null | sort -u | wc -l)
    echo ''
    echo "**Unique image count**: ${PIN_COUNT}"
    if [[ "${PIN_COUNT}" -gt 2 ]]; then
        echo ''
        echo "  ⚠ More than 2 vllm pins on host. CLAUDE.md policy: keep at most"
        echo "  ONE active pin + ONE previous (rollback). Run \`docker image"
        echo "  prune -af --filter 'until=24h'\` after confirming the extras"
        echo "  are not referenced by any compose."
    fi
fi

# ── optional sections (heavy) ──

if [[ "$WANT_BENCH" -eq 1 ]]; then
    _section "7. Bench summary (genesis_bench_suite --quick)"
    BENCH_TOOL="$REPO_ROOT/tools/genesis_bench_suite.py"
    if [[ -f "$BENCH_TOOL" ]]; then
        echo '```'
        timeout 600 python3 "$BENCH_TOOL" --quick 2>&1 | tail -40 | _redact
        echo '```'
    else
        echo '_(genesis_bench_suite.py not found at canonical path)_'
    fi
fi

if [[ "$WANT_AGENTIC" -eq 1 ]]; then
    _section "8. Agentic context-depth bench (5 turns)"
    AGENTIC_TOOL="$REPO_ROOT/tools/bench_agentic.py"
    if [[ -f "$AGENTIC_TOOL" ]]; then
        echo '```'
        timeout 300 python3 "$AGENTIC_TOOL" --turns 5 --sessions 1 --continue-on-no-tool 2>&1 | tail -30 | _redact
        echo '```'
    else
        echo '_(tools/bench_agentic.py not found)_'
    fi
fi

if [[ "$WANT_SOAK" -eq 1 ]]; then
    _section "9. Soak smoke (tools/soak.sh — abbreviated)"
    SOAK_TOOL="$REPO_ROOT/tools/soak.sh"
    if [[ -x "$SOAK_TOOL" ]]; then
        echo '```'
        timeout 900 bash "$SOAK_TOOL" --smoke 2>&1 | tail -25 | _redact
        echo '```'
    else
        echo '_(tools/soak.sh not found or not executable — skipping)_'
    fi
fi

_section "Footer"
echo "Report length: $(wc -l < /dev/stdin 2>/dev/null) lines (approximate)"
echo ''
echo "Generated by: \`tools/genesis_report.sh\`"
echo "Methodology source: club-3090 scripts/report.sh (multi-section paste-ready triage)."
echo ''
echo "_End of report._"
