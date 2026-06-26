#!/usr/bin/env bash
#
# Genesis quality-gate — STRESS / boundary harness.
#
# Public quality standard for a Genesis-served OpenAI-compatible endpoint.
# Runs the boundary probes that take real time and exercise the KV-cache /
# prefill-activation paths where the Genesis cliffs live. Run before publishing
# a config, after a vLLM pin bump, or when investigating a prefill-OOM
# regression. SLOW (large prompts, NIAH ladder up to ~92% of n_ctx); allow
# ~10-20 min on dual-card, longer on single-card.
#
# This is the EXTENDED Genesis port of club-3090's scripts/verify-stress.sh
# (github.com/noonghunna/club-3090, MIT). Adaptation notes + credit:
# docs/QUALITY_GATE.md. Genesis additions: every failing probe is cross-
# referenced to the Genesis cliff (docs/TROUBLESHOOTING.md "Named cliffs") AND
# the responsible patch ID (PN17 / P103 / PN59 / P67 / ...), so a red probe
# points at the exact Genesis path + mitigation. Payload generation + verdict
# logic live in the unit-tested tools/quality_gate core, not inline here.
#
# Probes (Cliff 2 territory deferred to last so an OOM there doesn't cascade):
#   1. NIAH small rungs (10K + 30K)      — mid-context recall, no Cliff 2.
#   2. Tool-response prefill OOM (~25K)   — Cliff 1 activation-peak class.
#   3. IDE-agent one-shot (tool_choice=none) — Cliff 1 mech B inductor leak.
#   4. Multi-turn agent (4-turn history)  — different inductor compile path.
#   5. LCB-coding shape (structured plan) — DS conv-state crash class.
#   6. Reasoning-heavy (max_tokens=8192)  — spec-decode AL-collapse class.
#   7. NIAH large rungs (60K + 90K)       — Cliff 2 / 2a (GDN fwd_h OOM).
#   8. Context CEILING ladder (95K -> 0.92*n_ctx) — false-ceiling detector with
#      per-rung VRAM-margin capture. First failing rung IS the real ceiling.
#
# Usage:
#   scripts/verify_stress.sh                       # auto-detect endpoint + model
#   URL=http://localhost:8000 scripts/verify_stress.sh
#   PRESET=qwen36-27b-single-3090 scripts/verify_stress.sh   # resolve via sndr
#   scripts/verify_stress.sh --dry-run             # print the plan, send nothing
#   scripts/verify_stress.sh --help
#
# Env (optional):
#   URL                   Endpoint (default http://localhost:8000).
#   MODEL                 served-model-name (default: first from /v1/models).
#   API_KEY               Bearer key (default genesis-local).
#   CONTAINER             Container name for VRAM scoping (default: auto / none).
#   PRESET                sndr preset key; resolves URL/MODEL via `sndr launch
#                         --dry-run` when URL/MODEL unset (best-effort).
#   SKIP_LONGCTX=1        Skip the NIAH ladder (probes 1, 7, 8).
#   SKIP_TOOL_PREFILL=1   Skip probe 2.
#   SKIP_CEILING=1        Skip probe 8.
#   PREFILL_TARGET_CHARS  Tool-prefill payload chars (default 100000 ~ 25K tok).
#   CEILING_FRACTION      Top ceiling rung as fraction of n_ctx (default 0.92).
#   CEILING_STEP_TOKENS   Ladder step (default 30000).
#   CEILING_START_TOKENS  First ceiling rung (default 95000).
#   VRAM_MARGIN_MB        Min free-VRAM after the ceiling (default 1024).
#   STRESS_LONGCTX_TIMEOUT_S    Long-ctx curl/send timeout (default 300).
#   STRESS_TOOL_PREFILL_TIMEOUT_S  Tool-prefill timeout (default 240).

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER=(python3 -m quality_gate.runner)
export PYTHONPATH="${ROOT_DIR}/tools${PYTHONPATH:+:${PYTHONPATH}}"

DRY_RUN=0
print_usage() {
  sed -n '2,60p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) print_usage; exit 0 ;;
    *) echo "verify_stress.sh: unknown argument: $1" >&2
       echo "  run with --help for usage." >&2
       exit 2 ;;
  esac
done

URL="${URL:-}"
MODEL="${MODEL:-}"
API_KEY="${API_KEY:-genesis-local}"
CONTAINER="${CONTAINER:-}"
PRESET="${PRESET:-}"

# Best-effort preset resolution: if a PRESET is named and URL/MODEL are unset,
# ask the sndr CLI to render the launch script and scrape the port + served
# model name out of it. Failure here is non-fatal — the explicit URL/MODEL env
# vars (or the localhost defaults) always win.
resolve_preset() {
  [[ -z "$PRESET" ]] && return 0
  command -v sndr >/dev/null 2>&1 || return 0
  local rendered
  rendered="$(sndr launch --dry-run "$PRESET" 2>/dev/null || true)"
  [[ -z "$rendered" ]] && return 0
  if [[ -z "$URL" ]]; then
    local port
    port="$(printf '%s\n' "$rendered" | grep -oE '(-p|--port)[ =]+[0-9]+' | grep -oE '[0-9]+' | head -1 || true)"
    [[ -n "$port" ]] && URL="http://localhost:${port}"
  fi
  if [[ -z "$MODEL" ]]; then
    MODEL="$(printf '%s\n' "$rendered" | grep -oE 'served-model-name[ =]+[^ ]+' | awk '{print $2}' | head -1 || true)"
  fi
}
resolve_preset

URL="${URL:-http://localhost:8000}"

# Resolve the served model from /v1/models when MODEL is unset.
if [[ -z "$MODEL" && "$DRY_RUN" == "0" ]]; then
  MODEL="$(curl -sf -m 5 -H "Authorization: Bearer ${API_KEY}" "${URL}/v1/models" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || true)"
fi
MODEL="${MODEL:-qwen3.6-27b}"

STRESS_LONGCTX_TIMEOUT_S="${STRESS_LONGCTX_TIMEOUT_S:-300}"
STRESS_TOOL_PREFILL_TIMEOUT_S="${STRESS_TOOL_PREFILL_TIMEOUT_S:-240}"
PREFILL_TARGET_CHARS="${PREFILL_TARGET_CHARS:-100000}"
CEILING_FRACTION="${CEILING_FRACTION:-0.92}"
CEILING_STEP_TOKENS="${CEILING_STEP_TOKENS:-30000}"
CEILING_START_TOKENS="${CEILING_START_TOKENS:-95000}"
VRAM_MARGIN_MB="${VRAM_MARGIN_MB:-1024}"

C_PASS=$'\033[32m'; C_FAIL=$'\033[31m'; C_WARN=$'\033[33m'; C_OFF=$'\033[0m'
pass() { printf "  %s✓%s %s\n" "$C_PASS" "$C_OFF" "$1"; }
failp() { printf "  %s✗%s %s\n" "$C_FAIL" "$C_OFF" "$1"; }
warnp() { printf "  %s△%s %s\n" "$C_WARN" "$C_OFF" "$1"; }
skipp() { printf "  %s⊘%s %s (skipped)\n" "$C_WARN" "$C_OFF" "$1"; }

FAILED=0

# jq-free JSON field reader (the rig may not have jq).
json_get() { python3 -c "import sys,json; print(json.load(sys.stdin).get('$1',''))"; }

# Apply a runner verdict JSON (read from a file): print the right colour and
# bump FAILED on FAIL. Emits the Genesis cliff/patch remediation for non-PASS.
apply_verdict() {
  local vfile="$1" label="$2"
  local status detail cliff patch remediation
  status="$(json_get status < "$vfile")"
  detail="$(json_get detail < "$vfile")"
  cliff="$(json_get cliff < "$vfile")"
  patch="$(json_get patch < "$vfile")"
  remediation="$(json_get remediation < "$vfile")"
  case "$status" in
    PASS) pass "${label}: ${detail}" ;;
    WARN) warnp "${label}: ${detail}" ;;
    SKIP) skipp "${label}: ${detail}" ;;
    FAIL)
      failp "${label}: ${detail}"
      if [[ -n "$cliff" ]]; then
        printf "      %s→%s %s (patch %s)\n" "$C_WARN" "$C_OFF" "$cliff" "$patch"
        printf "        %s\n" "$remediation"
      fi
      FAILED=$((FAILED + 1))
      ;;
    *) failp "${label}: unparseable verdict"; FAILED=$((FAILED + 1)) ;;
  esac
}

# VRAM free (MB) for the model's GPU(s). Returns 0 when nvidia-smi is absent.
vram_free_mb() {
  command -v nvidia-smi >/dev/null 2>&1 || { echo 0; return; }
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null \
    | awk '{s+=$1} END {printf "%.0f\n", s}' 2>/dev/null || echo 0
}

# Detect n_ctx from /v1/models max_model_len (vLLM/SGLang shape).
get_n_ctx() {
  curl -sf -m 5 -H "Authorization: Bearer ${API_KEY}" "${URL}/v1/models" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0].get('max_model_len',0))" 2>/dev/null \
    || echo 0
}

echo "Genesis quality-gate STRESS harness"
echo "  url=${URL}  model=${MODEL}  container=${CONTAINER:-auto}"
echo "  core=tools/quality_gate (unit-tested)  doc=docs/QUALITY_GATE.md"
echo ""

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] plan (no requests sent):"
  echo "  probe 1: NIAH small rungs (scale 150, 450)"
  echo "  probe 2: tool-response prefill OOM (~${PREFILL_TARGET_CHARS} chars)"
  echo "  probe 3: IDE-agent one-shot (tool_choice=none)"
  echo "  probe 4: multi-turn agent (4-turn history)"
  echo "  probe 5: LCB-coding structured plan"
  echo "  probe 6: reasoning-heavy (max_tokens=8192)"
  echo "  probe 7: NIAH large rungs (scale 900, 1400) — Cliff 2 territory"
  echo "  probe 8: ceiling ladder (start=${CEILING_START_TOKENS} step=${CEILING_STEP_TOKENS} frac=${CEILING_FRACTION})"
  echo "  example ladder for n_ctx=262144:"
  "${RUNNER[@]}" ladder --n-ctx 262144 --start "$CEILING_START_TOKENS" \
    --step "$CEILING_STEP_TOKENS" --fraction "$CEILING_FRACTION" | sed 's/^/    /'
  echo "  example NIAH secret + payload size:"
  dry_req="$(mktemp)"; dry_sec="$(mktemp)"
  "${RUNNER[@]}" gen-niah --model "$MODEL" --scale 150 --req "$dry_req" \
    --secret-out "$dry_sec" --seed 0 | sed 's/^/    /'
  printf "    niah payload chars: %s\n" "$(wc -c < "$dry_req" | tr -d ' ')"
  rm -f "$dry_req" "$dry_sec"
  echo "  example verdicts (logic only, no engine):"
  "${RUNNER[@]}" verdict-probe --kind lcb --http 500 \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('    lcb 500 ->', d['status'], d['cliff'], d['patch'])"
  "${RUNNER[@]}" verdict-probe --kind multiturn --http 500 \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('    multiturn 500 ->', d['status'], d['cliff'], d['patch'])"
  echo ""
  echo "[dry-run] OK — harness wiring is sound. A full live run needs the GPU rig."
  exit 0
fi

# Reachability gate.
if ! curl -sf -m 10 -H "Authorization: Bearer ${API_KEY}" "${URL}/v1/models" >/dev/null 2>&1; then
  echo "${C_FAIL}ERROR${C_OFF}: endpoint not reachable at ${URL}/v1/models" >&2
  echo "  Start a config first (e.g. sndr launch <preset>) or set URL=..." >&2
  exit 1
fi

# Run one NIAH rung at the given filler scale. Args: <probe_kind> <scale> <timeout>.
run_niah_rung() {
  local kind="$1" scale="$2" timeout="$3"
  local req sec res content vfile http prompt_tok secret
  req="$(mktemp)"; sec="$(mktemp)"; res="$(mktemp)"; content="$(mktemp)"; vfile="$(mktemp)"
  secret="$("${RUNNER[@]}" gen-niah --model "$MODEL" --scale "$scale" --req "$req" \
    --secret-out "$sec" | json_get secret)"
  "${RUNNER[@]}" send --url "$URL" --req "$req" --timeout "$timeout" --out "$res" >/dev/null
  http="$(json_get http_code < "$res")"
  prompt_tok="$(json_get prompt_tokens < "$res")"
  python3 -c "import json; print(json.load(open('$res')).get('content',''))" > "$content" 2>/dev/null || true
  "${RUNNER[@]}" verdict-niah --kind "$kind" --http "${http:-0}" \
    --secret "$secret" --content-file "$content" --prompt-tokens "${prompt_tok:-0}" > "$vfile"
  apply_verdict "$vfile" "scale=${scale} (${prompt_tok:-?} tok)"
  rm -f "$req" "$sec" "$res" "$content" "$vfile"
}

# Run one HTTP probe. Args: <probe_kind> <gen-kind> <timeout> <label>.
run_http_probe() {
  local kind="$1" gen_kind="$2" timeout="$3" label="$4"
  local req res vfile http clen tc comp finish mintok
  req="$(mktemp)"; res="$(mktemp)"; vfile="$(mktemp)"
  "${RUNNER[@]}" gen-probe --kind "$gen_kind" --model "$MODEL" --req "$req" \
    --target-chars "$PREFILL_TARGET_CHARS" >/dev/null
  "${RUNNER[@]}" send --url "$URL" --req "$req" --timeout "$timeout" --out "$res" >/dev/null
  http="$(json_get http_code < "$res")"
  clen="$(json_get content_len < "$res")"
  tc="$(json_get tool_calls < "$res")"
  comp="$(json_get completion_tokens < "$res")"
  finish="$(json_get finish_reason < "$res")"
  mintok=0
  [[ "$kind" == "reasoning" ]] && mintok=500
  "${RUNNER[@]}" verdict-probe --kind "$kind" --http "${http:-0}" \
    --content-len "${clen:-0}" --tool-calls "${tc:-0}" --completion "${comp:-0}" \
    --finish "${finish:-}" --min-tokens "$mintok" > "$vfile"
  apply_verdict "$vfile" "$label"
  rm -f "$req" "$res" "$vfile"
}

# -- Probe 1: NIAH small rungs ----------------------------------------------
echo "[1/8] NIAH small rungs (10K / 30K) ..."
if [[ "${SKIP_LONGCTX:-0}" == "1" ]]; then
  skipp "SKIP_LONGCTX=1"
else
  run_niah_rung "longctx_small" 150 "$STRESS_LONGCTX_TIMEOUT_S"
  run_niah_rung "longctx_small" 450 "$STRESS_LONGCTX_TIMEOUT_S"
fi

# -- Probe 2: tool-response prefill OOM -------------------------------------
echo "[2/8] Tool-response prefill OOM (~25K-token mock tool reply) ..."
if [[ "${SKIP_TOOL_PREFILL:-0}" == "1" ]]; then
  skipp "SKIP_TOOL_PREFILL=1"
else
  run_http_probe "tool_prefill" "tool_prefill" "$STRESS_TOOL_PREFILL_TIMEOUT_S" "tool-prefill"
fi

# -- Probe 3: IDE-agent one-shot --------------------------------------------
echo "[3/8] IDE-agent one-shot (sys + 10 tool schemas + refactor request) ..."
run_http_probe "ide_agent" "ide_agent" 180 "ide-agent"

# -- Probe 4: multi-turn agent ----------------------------------------------
echo "[4/8] Multi-turn agent (sys + tools + 4-turn history) ..."
run_http_probe "multiturn" "multiturn" 180 "multi-turn"

# -- Probe 5: LCB-coding shape ----------------------------------------------
echo "[5/8] LCB-coding shape (LeetCode-style + structured plan) ..."
run_http_probe "lcb_coding" "lcb" 240 "lcb-coding"

# -- Probe 6: reasoning-heavy -----------------------------------------------
echo "[6/8] Reasoning-heavy (math proof, max_tokens=8192) ..."
run_http_probe "reasoning" "reasoning" 600 "reasoning"

# -- Probe 7: NIAH large rungs (Cliff 2 territory) --------------------------
echo "[7/8] NIAH large rungs (60K / 90K — Cliff 2 / 2a territory) ..."
if [[ "${SKIP_LONGCTX:-0}" == "1" ]]; then
  skipp "SKIP_LONGCTX=1"
else
  run_niah_rung "longctx_large" 900 "$STRESS_LONGCTX_TIMEOUT_S"
  run_niah_rung "longctx_large" 1400 "$STRESS_LONGCTX_TIMEOUT_S"
fi

# -- Probe 8: ceiling ladder ------------------------------------------------
echo "[8/8] Context ceiling ladder (95K -> ${CEILING_FRACTION} x n_ctx, per-rung VRAM) ..."
run_ceiling_ladder() {
  if [[ "${SKIP_CEILING:-0}" == "1" || "${SKIP_LONGCTX:-0}" == "1" ]]; then
    skipp "ceiling ladder"
    return 0
  fi
  local n_ctx
  n_ctx="$(get_n_ctx)"
  if [[ "${n_ctx:-0}" -le 0 ]]; then
    skipp "could not detect n_ctx (no max_model_len from /v1/models)"
    return 0
  fi
  local rungs
  rungs="$("${RUNNER[@]}" ladder --n-ctx "$n_ctx" --start "$CEILING_START_TOKENS" \
    --step "$CEILING_STEP_TOKENS" --fraction "$CEILING_FRACTION" \
    | python3 -c "import sys,json; print(' '.join(str(r) for r in json.load(sys.stdin)['rungs']))")"
  if [[ -z "$rungs" ]]; then
    skipp "n_ctx=${n_ctx} too small for a ceiling ladder above ${CEILING_START_TOKENS}"
    return 0
  fi
  echo "    n_ctx=${n_ctx}  ladder: ${rungs}"

  # Calibrate filler scale -> tokens with a small probe.
  local cal_req cal_res cal_tokens tok_per_scale
  cal_req="$(mktemp)"; cal_res="$(mktemp)"
  "${RUNNER[@]}" gen-niah --model "$MODEL" --scale 100 --req "$cal_req" \
    --secret-out /dev/null >/dev/null
  "${RUNNER[@]}" send --url "$URL" --req "$cal_req" --timeout 60 --out "$cal_res" >/dev/null
  cal_tokens="$(json_get prompt_tokens < "$cal_res")"
  rm -f "$cal_req" "$cal_res"
  if [[ "${cal_tokens:-0}" -gt 0 ]]; then
    tok_per_scale="$(python3 -c "print(round(${cal_tokens}/100, 2))")"
    echo "    calibrated: scale=100 -> ${cal_tokens} tok (tok/scale=${tok_per_scale})"
  else
    tok_per_scale=65
    echo "    calibration probe failed — fallback tok/scale=${tok_per_scale}"
  fi

  local vram_start
  vram_start="$(vram_free_mb)"
  [[ "$vram_start" -gt 0 ]] && echo "    VRAM free (ladder start): ${vram_start} MB"

  local target scale req sec res content vfile http prompt_tok secret status vram_after
  for target in $rungs; do
    scale="$("${RUNNER[@]}" scale-for --target-tokens "$target" --tok-per-scale "$tok_per_scale" | json_get scale)"
    req="$(mktemp)"; sec="$(mktemp)"; res="$(mktemp)"; content="$(mktemp)"; vfile="$(mktemp)"
    secret="$("${RUNNER[@]}" gen-niah --model "$MODEL" --scale "$scale" --req "$req" --secret-out "$sec" | json_get secret)"
    "${RUNNER[@]}" send --url "$URL" --req "$req" --timeout "${STRESS_CEILING_TIMEOUT_S:-600}" --out "$res" >/dev/null
    http="$(json_get http_code < "$res")"
    prompt_tok="$(json_get prompt_tokens < "$res")"
    python3 -c "import json; print(json.load(open('$res')).get('content',''))" > "$content" 2>/dev/null || true
    vram_after="$(vram_free_mb)"
    if [[ "${http:-0}" == "400" ]]; then
      "${RUNNER[@]}" verdict-400 --kind ceiling --target-tokens "$target" --n-ctx "$n_ctx" > "$vfile"
    else
      "${RUNNER[@]}" verdict-niah --kind ceiling --http "${http:-0}" --secret "$secret" \
        --content-file "$content" --prompt-tokens "${prompt_tok:-0}" > "$vfile"
    fi
    status="$(json_get status < "$vfile")"
    local vram_str=""
    [[ "$vram_after" -gt 0 ]] && vram_str="  VRAM_free=${vram_after}MB"
    apply_verdict "$vfile" "rung target=$((target/1000))K actual=$(( ${prompt_tok:-0} / 1000 ))K${vram_str}"
    rm -f "$req" "$sec" "$res" "$content" "$vfile"
    # Stop the ladder on the first non-PASS — that depth IS the ceiling.
    if [[ "$status" != "PASS" ]]; then
      break
    fi
  done

  # Margin check against the last observed free VRAM.
  local vram_end
  vram_end="$(vram_free_mb)"
  if [[ "$vram_end" -gt 0 && "$vram_end" -lt "$VRAM_MARGIN_MB" ]]; then
    warnp "VRAM margin thin at ceiling: ${vram_end} MB free < ${VRAM_MARGIN_MB} MB threshold"
    echo "      Sustained agent load also carries prompt-cache + checkpoint overhead;"
    echo "      target a CTX_SIZE where margin >= ${VRAM_MARGIN_MB} MB at this depth."
    FAILED=$((FAILED + 1))
  fi
}
run_ceiling_ladder

echo ""
if [[ "$FAILED" == "0" ]]; then
  printf "%sAll stress / boundary checks passed.%s KV-cache and prefill paths are sound for this config.\n" "$C_PASS" "$C_OFF"
else
  printf "%s%d stress check(s) failed.%s See the cliff/patch hints above and docs/QUALITY_GATE.md.\n" "$C_FAIL" "$FAILED" "$C_OFF"
fi
exit "$FAILED"
