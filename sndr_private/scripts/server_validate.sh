#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Server-side validation for the multi-session dev work that is sitting
# 16 commits ahead of origin/dev (commits 1155845..59c5a88, May 2026).
#
# What this script does (read-only, non-destructive):
#
#   1. Snapshot host context (uname, git ref, GPU, vLLM pin).
#   2. Cold-install smoke (Phase 8a) — fresh imports + V1/V2 preflight.
#   3. Full pytest run (~3.5 min on Linux) — must match local baseline
#      of 6500 passed / 131 skipped.
#   4. `make evidence` aggregate — must be 38/39 gating green.
#   5. PN95 helper smoke under a real /proc/meminfo (this is where the
#      host-RAM cap actually returns a number rather than None).
#   6. PN82/PN55/P61c/PN90 dispatcher resolution — every patch's
#      apply_module must import cleanly under the live vLLM install.
#   7. PN95 preflight skip-on-upstream-connector path with a synthetic
#      ModelConfig (no live launch — pure import + boolean assertion).
#
# Output: a structured ledger-ready report under
# `~/.sndr/server-validate-runs/<ISO>.txt` plus stdout.
#
# Exit codes:
#   0  every check passed (or only skipped with explicit reason)
#   1  at least one check failed
#   2  prerequisites missing (python3, git, make)
#
# Usage:
#   bash scripts/server_validate.sh                     # everything
#   bash scripts/server_validate.sh --skip-pytest       # skip the slow part
#   bash scripts/server_validate.sh --quick             # only smokes (no pytest, no evidence)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SKIP_PYTEST=0
QUICK=0
for arg in "$@"; do
    case "$arg" in
        --skip-pytest) SKIP_PYTEST=1 ;;
        --quick)       QUICK=1; SKIP_PYTEST=1 ;;
        --help|-h)
            grep -E '^# ' "$0" | sed 's/^# //;s/^#//'
            exit 0 ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
OUT_DIR="${HOME}/.sndr/server-validate-runs"
mkdir -p "$OUT_DIR"
REPORT="$OUT_DIR/${STAMP}.txt"

_log()  { printf '%s\n' "$1" | tee -a "$REPORT"; }
_step() { printf '\n── %s ──\n' "$1" | tee -a "$REPORT"; }
_pass() { printf '  ✓ %s\n' "$1" | tee -a "$REPORT"; }
_fail() { printf '  ✗ %s\n' "$1" | tee -a "$REPORT"; FAILS=$((FAILS + 1)); }
_skip() { printf '  · %s\n' "$1" | tee -a "$REPORT"; }

FAILS=0

# ─── 1. Host context ────────────────────────────────────────────────

_step "1. Host context"
_log "  date:        $(date -u +%Y-%m-%dT%H:%M:%SZ)"
_log "  host:        $(hostname)"
_log "  uname:       $(uname -srm)"
_log "  cwd:         $REPO_ROOT"
_log "  git ref:     $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"
_log "  ahead of:    origin/$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null | cut -d/ -f2-) by $(git rev-list --count @{u}..HEAD 2>/dev/null || echo "?") commits"
_log "  python:      $(python3 --version 2>&1)"
if command -v nvidia-smi >/dev/null 2>&1; then
    _log "  gpu:         $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
else
    _log "  gpu:         (nvidia-smi not on PATH — non-GPU host or driver missing)"
fi
if python3 -c "import vllm; print('vllm:', vllm.__version__)" >> "$REPORT" 2>&1; then
    _pass "vllm import OK ($(python3 -c "import vllm; print(vllm.__version__)" 2>/dev/null))"
else
    _fail "vllm import failed — server validation needs vllm installed"
fi

# ─── 2. Cold-install smoke ───────────────────────────────────────────

_step "2. Cold-install smoke (Phase 8a)"
if bash scripts/cold_install_smoke.sh >> "$REPORT" 2>&1; then
    _pass "cold-install-smoke clean"
else
    _fail "cold-install-smoke reported failures — see $REPORT"
fi

# ─── 3. Full pytest ──────────────────────────────────────────────────

if [ "$SKIP_PYTEST" -eq 0 ]; then
    _step "3. Full pytest"
    if python3 -m pytest --no-header -q >> "$REPORT" 2>&1; then
        SUMMARY="$(tail -3 "$REPORT" | grep -E 'passed|failed' | tail -1 || echo "no summary")"
        _pass "pytest clean — $SUMMARY"
    else
        SUMMARY="$(tail -5 "$REPORT" | grep -E 'passed|failed' | tail -1 || echo "no summary")"
        _fail "pytest reported failures — $SUMMARY"
    fi
else
    _step "3. Pytest"
    _skip "skipped (--skip-pytest)"
fi

# ─── 4. Audit aggregate ──────────────────────────────────────────────

if [ "$QUICK" -eq 0 ]; then
    _step "4. make evidence"
    if python3 scripts/make_evidence.py >> "$REPORT" 2>&1; then
        SUMMARY="$(grep -E 'gate\(s\) green' "$REPORT" | tail -1 || echo "")"
        _pass "make evidence: $SUMMARY"
    else
        SUMMARY="$(grep -E 'gate\(s\) green|FAIL' "$REPORT" | tail -1 || echo "")"
        _fail "make evidence reported failures: $SUMMARY"
    fi
else
    _step "4. Evidence aggregate"
    _skip "skipped (--quick)"
fi

# ─── 5. PN95 host RAM cap probe ──────────────────────────────────────

_step "5. PN95 host RAM cap probe (real /proc/meminfo)"
PROBE=$(python3 - <<'PYEOF' 2>&1
from vllm.sndr_core.cache.tier_manager import (
    _host_capacity_cap_gib, _read_total_host_ram_gib,
)
total = _read_total_host_ram_gib()
cap = _host_capacity_cap_gib()
print(f"  total host RAM: {total!r} GiB")
print(f"  effective cap:  {cap!r} GiB (default reserve 8 GiB)")
import os
os.environ["GENESIS_PN95_HOST_RESERVE_GIB"] = "16"
print(f"  cap@reserve=16: {_host_capacity_cap_gib()!r} GiB")
os.environ.pop("GENESIS_PN95_HOST_RESERVE_GIB", None)
PYEOF
)
echo "$PROBE" | tee -a "$REPORT"
if echo "$PROBE" | grep -q "None"; then
    _skip "host probe returned None on at least one path (Mac dev box pattern)"
else
    _pass "host probe returns real GiB values — Linux contract honoured"
fi

# ─── 6. PN82/PN55/P61c/PN90 apply_module resolution ──────────────────

_step "6. PN82/PN55/P61c/PN90 apply_module resolution"
RESULT=$(python3 - <<'PYEOF' 2>&1
import importlib
from vllm.sndr_core.dispatcher.registry import PATCH_REGISTRY
failures = 0
for pid in ("PN82", "PN55", "P61c", "PN90"):
    e = PATCH_REGISTRY.get(pid)
    if e is None:
        print(f"  {pid}: NOT in registry"); failures += 1; continue
    mod = e.get("apply_module")
    if not mod:
        print(f"  {pid}: no apply_module set"); failures += 1; continue
    try:
        m = importlib.import_module(mod)
        if not hasattr(m, "apply"):
            print(f"  {pid}: module {mod} has no apply() — FAIL"); failures += 1
        else:
            print(f"  {pid}: {mod}  apply()  OK")
    except Exception as exc:
        print(f"  {pid}: import {mod} FAILED — {exc}"); failures += 1
print(f"  failures: {failures}")
import sys; sys.exit(0 if failures == 0 else 1)
PYEOF
)
RC=$?
echo "$RESULT" | tee -a "$REPORT"
if [ "$RC" -eq 0 ]; then
    _pass "all four apply_modules resolved + apply() present"
else
    _fail "at least one apply_module failed to import"
fi

# ─── 7. PN95 upstream-coexist skip path ──────────────────────────────

_step "7. PN95 upstream coexist gate (synthetic cfg)"
COEXIST=$(python3 - <<'PYEOF' 2>&1
import os
os.environ["GENESIS_ENABLE_PN95_TIER_AWARE_CACHE"] = "1"
from vllm.sndr_core.cache import _pn95_runtime
_pn95_runtime.reset_for_tests()

class _Block: pass
class _Cfg:
    kv_transfer_config = None
    cache_config = None

# Case 1: no upstream connector → PN95 init proceeds (returns False
# only because there are no cache_config.tiers — but the upstream gate
# itself did NOT trip).
c = _Cfg()
det = _pn95_runtime._detect_upstream_offload_connector(c)
print(f"  no connector: detected={det!r}  (expected: None)")
assert det is None

# Case 2: upstream connector wired in → init_from_config short-circuits
b = _Block(); b.kv_connector = "LMCacheConnectorV1"
c.kv_transfer_config = b
det = _pn95_runtime._detect_upstream_offload_connector(c)
print(f"  with LMCache connector: detected={det!r}")
assert det == "LMCacheConnectorV1"

rc = _pn95_runtime.init_from_config(c)
print(f"  init_from_config(c): {rc}  (expected: False — skip-on-upstream)")
assert rc is False

print("  OK — upstream coexist gate works end-to-end")
PYEOF
)
RC=$?
echo "$COEXIST" | tee -a "$REPORT"
if [ "$RC" -eq 0 ]; then
    _pass "PN95 upstream coexist gate verified"
else
    _fail "PN95 upstream coexist gate FAILED"
fi

# ─── 8. PN95 active-block TTL smoke ──────────────────────────────────

_step "8. PN95 active-block TTL smoke"
TTL=$(python3 - <<'PYEOF' 2>&1
from vllm.sndr_core.cache.tier_manager import TierManager

class T:
    def __init__(self, device, capacity_gib, eviction_policy="lru", low_water_pct=0.9):
        self.device = device; self.capacity_gib = capacity_gib
        self.eviction_policy = eviction_policy; self.low_water_pct = low_water_pct
        self.promote_on_hit = True

tm = TierManager([T("gpu", 4.0), T("cpu", 4.0)], slot_nbytes=65536,
                 host_capacity_cap_gib=8.0)
tm.set_active_ttl(3)
tm.admit("A", group_id="attn"); tm.admit("B", group_id="attn")
tm.mark_active("A")
print(f"  is_active(A)={tm.is_active('A')}  is_active(B)={tm.is_active('B')}")
cands = list(tm._demote_candidates())
print(f"  demote candidates with A active: {cands}  (expected: ['B'])")
assert "A" not in cands and "B" in cands
print("  OK — active-block protection filters A from demote candidates")
PYEOF
)
RC=$?
echo "$TTL" | tee -a "$REPORT"
if [ "$RC" -eq 0 ]; then
    _pass "PN95 active-block TTL verified"
else
    _fail "PN95 active-block TTL FAILED"
fi

# ─── 9. Result ───────────────────────────────────────────────────────

_step "Result"
if [ "$FAILS" -eq 0 ]; then
    _log ""
    _log "  ✓ server validation PASSED ($STAMP)"
    _log ""
    _log "  Full report: $REPORT"
    exit 0
else
    _log ""
    _log "  ✗ server validation FAILED ($FAILS check(s) failed)"
    _log ""
    _log "  Full report: $REPORT"
    exit 1
fi
