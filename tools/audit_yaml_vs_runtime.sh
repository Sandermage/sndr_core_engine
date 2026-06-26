#!/usr/bin/env bash
# audit_yaml_vs_runtime.sh — drift audit for YAML config vs live container env
#
# Compares the `genesis_env:` block of a builtin model_config YAML against
# the actual environment variables of a running vLLM container. Reports any
# drift between intended (YAML) and actual (live) state.
#
# Background: drift between YAML configs and start-scripts is a recurring
# regression source on Genesis (audit 2026-05-11 Wave 8 found 11 drift sources
# in single session; PN90 dropped from start-script alone cost -7% TPS until
# fixed). This script catches drift before it causes silent performance loss.
#
# Usage:
#   ./tools/audit_yaml_vs_runtime.sh <yaml_path> <container_name> [<ssh_host>]
#
# Examples:
#   # Audit local container (no SSH)
#   ./tools/audit_yaml_vs_runtime.sh vllm/sndr_core/model_configs/builtin/a5000-2x-27b-int4-tq-k8v4.yaml vllm-server
#
#   # Audit remote PROD container via SSH
#   ./tools/audit_yaml_vs_runtime.sh vllm/sndr_core/model_configs/builtin/a5000-2x-27b-int4-tq-k8v4.yaml vllm-pn95-2xa5000 <user>@127.0.0.1
#
# Exit codes:
#   0 — no real drift (only intentional disables / experiment-specific extras)
#   1 — real drift found (YAML enables a flag not in live env, or vice versa with non-experiment key)
#   2 — usage error or file not found
#
# Output sections:
#   - "YAML keys NOT in live env" — flags that YAML enables but container doesn't have
#   - "Live env keys NOT in YAML" — flags container has but YAML doesn't specify
#   - "Summary verdict" — drift severity assessment

set -e

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
  echo "Usage: $0 <yaml_path> <container_name> [<ssh_host>]" >&2
  exit 2
fi

YAML_PATH="$1"
CONTAINER_NAME="$2"
SSH_HOST="${3:-}"

if [ ! -f "$YAML_PATH" ]; then
  echo "ERROR: YAML file not found: $YAML_PATH" >&2
  exit 2
fi

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Extract GENESIS_* keys from YAML genesis_env block
grep -E "^\s+GENESIS_" "$YAML_PATH" \
  | sed -E 's/^[[:space:]]+//;s/:.*$//' \
  | sort -u > "$TMPDIR/yaml_keys.txt"

# Get live container env via docker inspect
if [ -n "$SSH_HOST" ]; then
  ssh "$SSH_HOST" "docker inspect $CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}'" 2>/dev/null \
    | grep -oE '^GENESIS_[A-Z0-9_]+' \
    | sort -u > "$TMPDIR/live_keys.txt"
else
  docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | grep -oE '^GENESIS_[A-Z0-9_]+' \
    | sort -u > "$TMPDIR/live_keys.txt"
fi

if [ ! -s "$TMPDIR/live_keys.txt" ]; then
  echo "ERROR: Could not get live env from container $CONTAINER_NAME (is it running?)" >&2
  exit 2
fi

YAML_COUNT=$(wc -l < "$TMPDIR/yaml_keys.txt")
LIVE_COUNT=$(wc -l < "$TMPDIR/live_keys.txt")

echo "═══════════════════════════════════════════════════════════════════════"
echo " YAML vs Runtime Drift Audit"
echo "  YAML:      $YAML_PATH (${YAML_COUNT} keys)"
echo "  Container: $CONTAINER_NAME (${LIVE_COUNT} keys) ${SSH_HOST:+via $SSH_HOST}"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""

REAL_DRIFT=0

echo "─── YAML keys NOT in live env ───"
YAML_MINUS_LIVE=$(comm -23 "$TMPDIR/yaml_keys.txt" "$TMPDIR/live_keys.txt")
if [ -z "$YAML_MINUS_LIVE" ]; then
  echo "  (none)"
else
  echo "$YAML_MINUS_LIVE" | while read key; do
    # Check if YAML sets =0 (explicit disable — not drift)
    yaml_val=$(grep -E "^\s+${key}:" "$YAML_PATH" | sed -E "s/.*${key}:[[:space:]]*//;s/[[:space:]]*#.*$//;s/[[:space:]]+$//" | tr -d "'\"")
    if [ "$yaml_val" = "0" ]; then
      echo "  $key  [OK — explicit disable in YAML, default-off in env]"
    else
      echo "  $key = $yaml_val  ⚠ DRIFT: YAML enables but container doesn't have"
    fi
  done
  # Re-count actual drift
  WHILE_DRIFT=$(echo "$YAML_MINUS_LIVE" | while read key; do
    yaml_val=$(grep -E "^\s+${key}:" "$YAML_PATH" | sed -E "s/.*${key}:[[:space:]]*//;s/[[:space:]]*#.*$//;s/[[:space:]]+$//" | tr -d "'\"")
    if [ "$yaml_val" != "0" ]; then echo "drift"; fi
  done | wc -l)
  if [ "$WHILE_DRIFT" -gt 0 ]; then REAL_DRIFT=1; fi
fi

echo ""
echo "─── Live env keys NOT in YAML ───"
LIVE_MINUS_YAML=$(comm -13 "$TMPDIR/yaml_keys.txt" "$TMPDIR/live_keys.txt")
if [ -z "$LIVE_MINUS_YAML" ]; then
  echo "  (none)"
else
  echo "$LIVE_MINUS_YAML" | while read key; do
    # PN95-related keys are often added by experiment scripts on top of canonical YAML
    if echo "$key" | grep -qE '^GENESIS_PN95_|^GENESIS_ENABLE_PN95_'; then
      echo "  $key  [INTENTIONAL — PN95 experiment additions, see start_pn95_*.sh]"
    else
      echo "  $key  ⚠ EXTRA: container has env not specified in YAML"
    fi
  done
  EXTRA_REAL=$(echo "$LIVE_MINUS_YAML" | grep -vE '^GENESIS_PN95_|^GENESIS_ENABLE_PN95_' | wc -l)
  if [ "$EXTRA_REAL" -gt 0 ]; then REAL_DRIFT=1; fi
fi

echo ""
echo "─── Summary ───"
if [ "$REAL_DRIFT" -eq 0 ]; then
  echo "  ✓ No real drift detected. YAML and live env are aligned."
  exit 0
else
  echo "  ✗ Real drift detected. See above for details."
  echo "  Action: update start-script to match YAML genesis_env, restart container, re-audit."
  exit 1
fi
