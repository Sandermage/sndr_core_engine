#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# run_clean_venv_test.sh — verify the wheel installs cleanly + the CLI
# self-bootstraps without any vllm/torch/triton dependency.
#
# T1.7 (audit closure 2026-05-09 / production roadmap §P1-2). The audit
# called out that `pip install vllm-sndr-core` in a clean venv (no vllm
# yet) MUST succeed and produce a working `sndr --help`. Until this
# script existed, that property was tested ad-hoc; now CI can run it
# end-to-end.
#
# Exit codes:
#   0 — clean install + every smoke command exits 0
#   1 — wheel build failed
#   2 — pip install failed
#   3 — `sndr --help` failed
#   4 — at least one CLI smoke command failed
#
# Usage:
#   ./scripts/run_clean_venv_test.sh                 # uses repo HEAD
#   WHEEL_PATH=/path/to/whl ./scripts/run_clean_venv_test.sh
#   USE_CONSTRAINTS=1 ./scripts/run_clean_venv_test.sh  # apply constraints.txt
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${VENV_DIR:-/tmp/sndr-clean-venv}"
WHEEL_PATH="${WHEEL_PATH:-}"
USE_CONSTRAINTS="${USE_CONSTRAINTS:-0}"

# ─── 1. Build the wheel (unless caller already provided one) ──────────
if [ -z "$WHEEL_PATH" ]; then
    echo "::: Building wheel from $REPO_ROOT"
    rm -rf dist build *.egg-info
    if ! python3 -m build --wheel . 2>&1 | tail -5; then
        echo "FAIL: wheel build failed"
        exit 1
    fi
    WHEEL_PATH="$(ls dist/vllm_sndr_core-*.whl 2>/dev/null | head -1)"
fi

if [ -z "$WHEEL_PATH" ] || [ ! -f "$WHEEL_PATH" ]; then
    echo "FAIL: no wheel at $WHEEL_PATH"
    exit 1
fi
echo "::: Using wheel: $WHEEL_PATH"

# ─── 2. Create + populate clean venv ──────────────────────────────────
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

PIP_ARGS=("$WHEEL_PATH")
if [ "$USE_CONSTRAINTS" = "1" ]; then
    PIP_ARGS=("-c" "$REPO_ROOT/constraints.txt" "${PIP_ARGS[@]}")
fi

echo "::: Installing in clean venv: pip install ${PIP_ARGS[*]}"
if ! "$VENV_DIR/bin/pip" install --quiet "${PIP_ARGS[@]}" 2>&1 | tail -5; then
    echo "FAIL: pip install failed"
    exit 2
fi

# ─── 3. Smoke-test the console scripts ─────────────────────────────────
SNDR="$VENV_DIR/bin/sndr"

echo "::: smoke: sndr --help"
if ! "$SNDR" --help >/dev/null 2>&1; then
    echo "FAIL: sndr --help non-zero"
    exit 3
fi

declare -a SMOKE=(
    "patches doctor --json"
    "patches list --json"
    "patches bundles list --json"
    "memory doctor --json"
)

failures=0
for cmd in "${SMOKE[@]}"; do
    echo "::: smoke: sndr $cmd"
    # shellcheck disable=SC2086
    if ! "$SNDR" $cmd >/dev/null 2>&1; then
        echo "FAIL: sndr $cmd"
        failures=$((failures + 1))
    fi
done

if [ "$failures" -gt 0 ]; then
    echo "FAIL: $failures CLI smoke commands failed"
    exit 4
fi

# ─── 4. Verify no vllm/torch deps got pulled in ───────────────────────
# Dataset deps that should NOT be installed by `pip install
# vllm-sndr-core`. If any appear, our wheel is leaking heavy deps.
FORBIDDEN=("vllm" "torch" "triton" "tensorrt" "deepspeed")
echo "::: Verifying no heavy deps leaked into clean venv"
for pkg in "${FORBIDDEN[@]}"; do
    if "$VENV_DIR/bin/pip" show "$pkg" >/dev/null 2>&1; then
        echo "FAIL: $pkg got installed as a transitive dep — wheel is not self-contained"
        exit 4
    fi
done

echo "PASS: clean-venv install + smoke tests succeeded ($WHEEL_PATH)"
deactivate || true
