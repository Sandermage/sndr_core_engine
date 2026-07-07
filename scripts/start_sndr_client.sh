#!/bin/bash
# Canonical CLIENT launcher (Mac / Windows / no-GPU) — drive a REMOTE rig.
#
# The engine (vLLM) cannot run on a host without a CUDA GPU. This launcher
# starts the sndr CLI + Control Center GUI locally and points them at a remote
# rig engine + memory. It mirrors scripts/start_sndr_daemon.sh's env discipline
# (engine URL + key + DSN) for the client case — but runs `sndr up --no-engine`
# natively instead of launching the vLLM container.
#
# Config precedence (docker-compose semantics): an exported shell var wins,
# then ./.env (KEY=VALUE, read literally — NOT sourced), then these defaults.
# The zero-friction path: `install.sh --client` writes a prefilled ./.env; run
# this from that directory. See docs/RUN_ON_MAC.md.
set -euo pipefail

# Load ./.env literally (KEY=VALUE only; tolerate quotes / CRLF / comments)
# WITHOUT sourcing it, so a stray shell metacharacter cannot execute.
ENV_FILE="${SNDR_ENV_FILE:-.env}"
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"                       # strip CR (CRLF tolerance)
    case "$line" in ''|'#'*) continue ;; esac  # skip blanks / comments
    case "$line" in *=*) : ;; *) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"       # ltrim key
    key="${key%"${key##*[![:space:]]}"}"       # rtrim key
    case "$key" in [A-Za-z_]*) : ;; *) continue ;; esac
    val="${val%\"}"; val="${val#\"}"           # strip surrounding quotes
    val="${val%\'}"; val="${val#\'}"
    # Shell env wins: only set from .env when not already exported.
    if [ -z "${!key:-}" ]; then export "$key=$val"; fi
  done < "$ENV_FILE"
fi

# The remote-client triplet (the only genuinely manual surface).
ENGINE_URL="${SNDR_OPENAI_BASE_URL:-http://YOUR_RIG_HOST:8102/v1}"
ENGINE_KEY="${SNDR_ENGINE_API_KEY:-genesis-local}"
MEM_DSN="${GENESIS_MEMORY_DSN:-}"
GUI_PORT="${SNDR_GUI_PORT:-8765}"

case "$ENGINE_URL" in
  *YOUR_RIG_HOST*)
    echo "warn: SNDR_OPENAI_BASE_URL still points at the placeholder YOUR_RIG_HOST" >&2
    echo "      edit ./.env (or export SNDR_OPENAI_BASE_URL) to your rig, e.g." >&2
    echo "      http://rig.local:8102/v1  — see docs/RUN_ON_MAC.md" >&2
    ;;
esac
if [ -z "$MEM_DSN" ]; then
  echo "note: GENESIS_MEMORY_DSN unset -> memory is ephemeral (empties on restart)." >&2
  echo "      set it to your rig's pgvector DSN for durable memory." >&2
fi

export SNDR_OPENAI_BASE_URL="$ENGINE_URL"
export SNDR_ENGINE_API_KEY="$ENGINE_KEY"
export SNDR_GUI_PORT="$GUI_PORT"

echo "sndr client -> engine=$ENGINE_URL, GUI=:$GUI_PORT (no local engine)"
exec sndr up --no-engine "$@"
