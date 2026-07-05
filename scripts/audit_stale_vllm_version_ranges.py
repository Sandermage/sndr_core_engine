#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit for stale `vllm_version_range` upper bounds in PATCH_REGISTRY.

CLAUDE.md Class 5 known-bug surface: "Anchor drift after vllm pin bump."
This audit catches a softer variant — patches whose `applies_to.vllm_version_range`
upper bound EXCLUDES the current operational pin, causing:

  - `applies_to` constraint check fails on every boot
  - When env_flag is set (opt-in), the patch still applies but logs a
    WARNING about the mismatch — spurious noise in production boot logs
  - When env_flag is unset (default_on path), the patch silently skips
    via the strict-opt-in guard (which fires first), so the version
    range never gets checked — but the range field is still wrong

Behaviour
---------

The audit examines every PATCH_REGISTRY entry's
`applies_to.vllm_version_range` and reports cases where the upper
bound looks stale (would exclude the current operational pin).

Operational pin ("the pin we target"): resolved SSOT-first — the `--pin`
override wins; else the `sndr/pins.yaml` `current` field (read directly,
package-import-free, so CI and local agree); else the `sndr.pins` accessor;
else the guards KNOWN_GOOD freshest promotion; else the static `DEFAULT_PIN`.
The installed `vllm.__version__` is deliberately NOT consulted — the target
pin is a repo fact, not whatever wheel happens to be in the venv (that trust
was the 2026-07-05 CI-only divergence: CI's older vllm mis-flagged
forward-dated patches whose lower bound == the current pin).

Severity classification:

  CRITICAL — patch is `default_on=True` + version range excludes current
             pin. Patch silently skips for every operator without
             opt-in override. (As of v11.3.0 audit: 0 entries.)

  WARN     — patch is opt-in (default_on=False) but enabled by some
             prod-* preset. Operator gets spurious WARN noise on boot.

  INFO     — patch is opt-in and not enabled by any preset. Only shows
             up if operator explicitly enables.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Status: v11.3.0+ audit (CLAUDE.md Class 5 surface).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# Default current-pin assumption when vllm not importable.
# Update on each pin bump (or pull dynamically when vllm is installed).
# 2026-06-13 (wave-2): bumped from the stale 0.21.1rc1.dev354 to the
# canonical pin so torch-less audit runs (CI / collection envs) evaluate
# ranges against the version actually deployed — the 0.21.1 default
# false-flagged every correct `>=0.22.0` range as stale.
DEFAULT_PIN = "0.23.1rc1.dev748+g2dfaae752"  # static last-resort fallback; keep in sync with pins.yaml current on bump (bump_pin maintains it). Real resolution reads pins.yaml directly first.


# v11.3.0 BUG #14 baseline allowlist — known patches with stale
# upper bounds whose verification on the current pin is queued for a
# bulk-update PR. Each entry documents the patch's status. `--strict`
# mode exits 1 only on CRITICAL entries NOT in this allowlist — new
# additions force review without blocking known-debt entries.
#
# Cleanup workflow when bumping a range:
#   1. Verify patch applies cleanly on the new pin (anchor + smoke).
#   2. Update `applies_to.vllm_version_range` in registry.py.
#   3. Remove the patch ID from this set + add a one-line "verified
#      on pin <X> via bench <Y>" note in commit message.
_BASELINE_CRITICAL_STALE: frozenset[str] = frozenset({
    # Default-on (always-skip without env override) — ZERO entries: PN252,
    # the sole former default_on member, was formally RETIRED 2026-07-05
    # (lifecycle=retired) once vllm#45252 (GHSA-33cg-gxv8-3p8g) was verified
    # engine-native on pristine dev748 — see the breadcrumb at the end of this
    # set. `legacy`/`retired`/`deprecated` lifecycles are filtered out by
    # `_audit`, so retired patches never surface here and need no baseline row.
    #
    # v11.3.0 BUG #14 follow-through (commit pending): empirically
    # verified on rig 0.21.1rc1 via direct apply() probe — 17 of the
    # original 19 patches now bumped to `<0.22.0` (P70, P72, P82,
    # P103, P107, PN12, PN14, PN16, PN71, PN91, PN92, PN96, PN106,
    # PN125, PN201, SNDR_WORKSPACE_001, PN90). Each verified by:
    #   - apply() returns "applied" on writable mount, OR
    #   - apply() returns "skipped" with "read_only_mount" reason
    #     (PN14, PN96 — bind-mount issue, not patch breakage), OR
    #   - apply() returns "skipped" with self-detected drift marker
    #     (PN90 — upstream merged equivalent, intentional self-skip)
    #
    # v11.3.0 P0.1+P0.2 anchor rework: both originally-baseline patches
    # (P67, PN73) had their anchors refreshed to match upstream
    # 0.21.x refactors. Baseline now empty — any new CRITICAL entry
    # forces review.
    # P67 — fixed: anchor updated for `mm_prefix_range_tensor` +
    #       multi-line `if (` form introduced by upstream multimodal-
    #       prefix-range refactor.
    # PN73 — fixed: anchor updated for `function = item.get("function")`
    #        extracted-variable refactor in _postprocess_messages.
    #
    # 2026-06-13 (wave-2): DEFAULT_PIN bumped 0.21.1 → 0.22.1 (canonical).
    # That correctly surfaces two PRE-EXISTING 0.21-era entries whose
    # `<0.22.0` upper bound now excludes the deployed pin and which are
    # enabled in builtin YAMLs — pre-existing debt unrelated to the
    # wave-2 registry integration, queued for per-patch re-verification
    # on 0.22.1 before the range is bumped (audit workflow step 1):
    # PN90 removed 2026-07-05 (verified by code on pristine dev748): all 4
    # anchors gone (runner `None,  # draft_probs` literal absent -> apply()
    # self-retires; proposer _greedy_sample gained a use_heterogeneous_vocab
    # branch) and upstream #40269 native symbols present -> PN90 self-skips.
    # All model YAMLs now set the flag '0' and the QA profile disables it, so
    # PN90 is WARN (not CRITICAL) at dev748 — its CRITICAL-waiver entry was
    # vestigial. Kept lifecycle=experimental (NOT retired: related_not_
    # superseding, test-locked in test_audit_upstream_status EXPECTED_SPECIAL;
    # #40269 is a different-approach landing empirically rejected on our shape).
    # Dropping it re-arms the guard: re-enabling the flag to '1' now trips
    # --strict instead of being silently waived.
    # PN125 CLEARED 2026-07-05 (dev748 reverify): anchor PRESENT+APPLICABLE on
    # 0.23.1rc1.dev748 — Qwen3_5ForConditionalGenerationConfig + MambaModelConfig
    # .verify_and_update_config both live in vllm.model_executor.models.config and
    # MODELS_CONFIG_MAP routes both our arches to the target (verified via
    # `docker run --rm nightly-2dfaae752`). apply() returns "applied". The
    # config-class gap PN125 targets is NOT closed natively (class still only sets
    # mamba_ssm_cache_dtype); the FULL_AND_PIECEWISE effect is redundant with the
    # v1 resolver but harmless, and the patch is deliberately kept ON in 4 YAMLs as
    # upstream-bypass insurance. Range bumped <0.22.0 -> <0.24.0 (registry.py) so
    # the insurance installs on dev748 instead of being version-gate-skipped.
    # Anchor present => BUMP not RETIRE; no longer stale-debt.
    #
    # 2026-06-14: DELIBERATE cross-pin gates (NOT debt-to-bump). The four
    # entries below are capped '<0.22.1rc1.dev491' ON PURPOSE by the
    # deep-audit #1 version-gate work. Each stays ENABLED in the shared
    # qwen3.6 / a5000-2x builtin YAMLs so a rollback to the dev259 image
    # (which still has the old code) keeps protection; the runtime
    # version-gate (GENESIS_ENFORCE_VERSION_RANGE=1) makes the per-pin
    # decision — APPLY on dev259, SKIP on dev491. They surface as CRITICAL
    # only under `--pin dev491` (the deployed pin), which is correct and
    # benign by design. Do NOT bump the bound to re-include dev491 — that
    # would re-introduce the exact corruption each one avoids. These became
    # visible only once the `--pin dev491` audit crash (_ver_key TypeError
    # on rc/dev bounds) was fixed in this commit; before that the dev491
    # audit could not run, so the version-gate work never allowlisted them.
    # 2026-06-19 (dev148 TIER-1 audit): the three qwen3_coder wraps below had
    # their cap WIDENED from <0.22.1rc1.dev491 to <0.23.0 — the dev491 bound
    # did NOT exclude the 0.23.1 dev148 pin (version-semantics gap), so they
    # would have re-engaged and corrupted the native parser. #45588 DELETED
    # tool_parsers/qwen3coder_tool_parser.py + the gemma4 parser; the engine
    # state machine supersedes. Skip 0.23.x, apply <0.23.0 (dev259 rollback).
    # P64/P61c/PN56 formally RETIRED 2026-07-03 (consolidated into the single
    # registry entry "P64", lifecycle=retired, capped <0.23.0). All three patch
    # the DELETED tool_parsers/qwen3coder_tool_parser.py (#45413/#45171/#45588,
    # merged 2026-06-15). PN56 verified by code 2026-07-05 on pristine dev748
    # (2dfaae752): the file — and the whole entrypoints/openai/tool_parsers/
    # dir — is GONE; only the engine-native vllm/tool_parsers/
    # qwen3_engine_tool_parser.py remains, so _make_pn56_patcher() resolves no
    # target and the wrap is inert. As a retired entry P64 is auto-excluded from
    # _audit (lifecycle filter), so none of the three can surface as a CRITICAL
    # row — no baseline waiver is needed (PN30/PN373/P64 retire precedent).
    # P61c removed 2026-07-05: consolidated into P64 (env_flag_alias, not a
    # standalone registry id) and P64 is lifecycle=retired + auto-excluded, so
    # the audit can never emit a P61c CRITICAL — the waiver row was vestigial.
    # Verified by code on pristine dev748 (2dfaae752): qwen3coder_tool_parser.py
    # DELETED, P61C_ANCHOR_OLD (is_tool_call_started) 0 matches tree-wide.
    # PN347 formally RETIRED 2026-07-05 (lifecycle=retired, superseded by the
    # structural size_k_first caller-contract refactor at dev491+ that DELETED
    # its `w_q.shape != (...)` anchor — verified by code on pristine dev748) —
    # now auto-excluded by _audit, so no baseline entry is needed.
    # ── 0.23.1 reverify 2026-06-17 (Workflow + adversarial verify) ──────
    # Intentionally capped <0.23.0 on the 0.23.1 pin — each verified live.
    # (a) Upstream supersedes on 0.23.x (the fix shipped / the bug is gone):
    # PN30 formally RETIRED 2026-07-05 (lifecycle=retired) — the DS conv
    # spec-decode NotImplementedError anchor is GONE on dev748 (upstream
    # fused-postprocess kernel; the `assert offset == 0` form re-verified by
    # code on pristine 2dfaae752, mamba_utils.py:305-310), so PN30 is
    # auto-excluded from this audit and no longer needs a baseline entry
    # (P64/P61b/PN287 retire precedent).
    # PN133 formally RETIRED 2026-07-05 (lifecycle=retired) — vllm#42722's
    # accounting fix is native on dev748 (scheduler.py:1585-1593); pre-fix
    # anchor PN133_OLD gone (grep 0). Auto-excluded by _audit, no baseline row.
    # PN362 formally RETIRED 2026-07-05 (lifecycle=retired) — vllm#42425 merged
    # 2026-06-16 ships vllm/triton_utils/force_first_config.py natively on
    # dev748. Auto-excluded by _audit, no baseline row.
    # PN370 formally RETIRED 2026-07-05 (lifecycle=retired) — vllm#45100 merged;
    # native `batch_size = m.num_reqs` + `needs_cpu_accepted_counts` guard on
    # pristine dev748. Auto-excluded by _audit, no baseline row.
    # PN373 (parallel_tool_calls null, vllm#44955 merged 2026-06-15) formally
    # RETIRED 2026-07-05 (lifecycle=retired) — `is not False` + the merged
    # docstring verified native in pristine dev748 tool_calls_utils.py:22-24;
    # auto-excluded from _audit, so no baseline entry needed (P64/P61b/PN287 class).
    # PN378 formally RETIRED 2026-07-05 (lifecycle=retired) — the complete
    # vllm#45060 (mask + OOV clamp) is native in pristine dev748
    # rejection_sampler.py L945/L952; dev259 splice anchor gone (count 0).
    # Auto-excluded by _audit, no baseline row.
    # PN383 formally RETIRED 2026-07-05 (lifecycle=retired) — vllm#44784 merged
    # 2026-06-16; eagle-group offload gating is native+evolved in pristine
    # dev748 offloading/scheduler.py. Auto-excluded by _audit, no baseline row.
    # PN51 (qwen3 enable_thinking=false streaming content routing, vllm#40816,
    # fixed upstream by #40820) was CONSOLIDATED into P61b on 2026-06-20 (it is
    # an env_flag_alias, not a standalone registry key) and P61b is
    # lifecycle=retired — so PN51 never surfaces as an _audit row and this
    # allowlist line suppressed nothing. Superseded on dev748 by the
    # #45413/#45588 parser-engine refactor: reasoning/qwen3_reasoning_parser.py
    # (PN51's target) is DELETED and the anchor text is absent tree-wide on
    # pristine 2dfaae752 — the engine-native qwen3_engine_reasoning_parser.py
    # owns thinking-disabled routing. Baseline entry removed 2026-07-05
    # (P64/P61b/PN287/PN30/PN373 retire precedent).
    # P29_HEAL formally RETIRED 2026-07-05 (lifecycle=retired, superseded by
    # #45413/#45171/#45588 — target file + anchors gone on pristine dev748).
    # Auto-excluded by _audit, no baseline row.
    # G4_14 formally RETIRED 2026-07-05 (lifecycle=retired, default_on=False):
    # Gemma4ToolParser is DELETED by #45588; the surviving Gemma4EngineToolParser
    # is a skip_special_tokens=False rewrite so the #39392 raw-token pad-leak
    # mode is gone. _find_gemma_tool_parser() misses -> graceful no-op. Cap kept
    # <0.23.0 (anchor GONE, NOT bumped). Auto-excluded by _audit, no baseline
    # row. #39392 still OPEN: redesign vs the new class with a failing repro
    # test before lifting the cap.
    # SNDR_MTP_DYNAMIC_K_001 formally RETIRED (lifecycle=retired) — superseded by
    # native Dynamic SD (vllm#32374, MERGED 2026-06-14) verified in-pin on
    # pristine dev748 (vllm/v1/spec_decode/dynamic/utils.py: "Dynamic SD batch-size
    # schedule"). The DraftModelProposer monkey-patch target still exists
    # (draft_model.py:19) but the #26504 port is redundant and bench NOT_SIGNIFICANT.
    # Auto-excluded from _audit (lifecycle=retired), so no baseline entry needed
    # (P64/PN30/PN373 retire precedent). default_on=False.
    # PN374 formally RETIRED 2026-07-05 (lifecycle=retired, superseded by the
    # #45588 parser-engine refactor that DELETED tool_parsers/
    # qwen3xml_tool_parser.py; native vllm/parser/qwen3.py json.dumps escapes
    # keys+values so the quoted-key corruption cannot occur — verified by code
    # on pristine dev748). Auto-excluded from _audit (WARN-only anyway, never
    # enabled by a builtin YAML/compose), so no baseline entry is needed.
    # ── 0.23.1 dev148 full-patch audit 2026-06-18 ──────────────────────
    "PN66",   # multiturn </think> leak fix. Re-verified live on dev748
              # 2026-07-05: DelegatingParser is PRESENT (not gone) but the
              # reasoning stack was rewritten to an engine-based incremental
              # adapter (Qwen3ParserReasoningAdapter). The leak is ABSENT on
              # dev748 for two independent reasons: (1) parser_engine.is_reasoning_end
              # now returns False when a <think> start precedes any </think> on
              # the backward scan — the guard the original buggy prompt-scan
              # lacked — and parse_delta's else-branch calls
              # adjust_initial_state_from_prompt; (2) the Qwen3.6 chat template
              # (chat_template.jinja:100-104) STRIPS prior-turn reasoning from
              # history, so no stale </think> enters prompt_token_ids in normal
              # multiturn. #41696 CLOSED-unmerged. Skip 0.23.x, apply <0.23.0.
    # PN110 — RETIRED 2026-07-05 (lifecycle=retired, auto-excluded from this
    #   audit). By-code verify on pristine dev748 (block_pool.py:614): the
    #   free_blocks region PN110 anchored on is GONE (LRU-split rewrite) and
    #   the new per-block `if block.ref_cnt == 0` append-guard structurally
    #   prevents the double-append symptom. #42615 OPEN but SimpleCPUOffload-
    #   only; non-offload PROD. See registry superseded_by. Cap <0.23.0 kept.
    # P61b + PN287 formally RETIRED 2026-07-03 (lifecycle=retired, superseded by
    # the #45413/#45588 parser-engine refactor that DELETED their target files —
    # verified live on dev714) — now auto-excluded from this audit, so they no
    # longer need a baseline entry.
    # PN252 (M-RoPE prompt_embeds-only DoS, GHSA-33cg-gxv8-3p8g) formally
    # RETIRED 2026-07-05 (lifecycle=retired, superseded by vllm#45252 MERGED
    # 2026-06-13). By-code re-verification on pristine dev748 (2dfaae752):
    # _init_mrope_positions at gpu_model_runner.py:1607-1637 is the engine-
    # native fix verbatim — NO fatal `assert prompt_token_ids is not None`,
    # instead `input_tokens` is derived from prompt_token_ids-or-prompt_embeds-
    # length else a per-request ValueError; the fatal assert survives only in
    # the sibling _init_xdrope_positions (line 1642), which PN252 never
    # targeted. Both PN252 required anchors count=0 on pristine dev748, so the
    # patcher self-skips. lifecycle=retired → auto-excluded from `_audit`, so no
    # baseline row is needed (P64/P61b/PN287/PN373/PN110 class). The default_on-
    # enable flag was also removed from the a5000-2x hardware YAML the same day,
    # closing the "enabled flag on a version-gated no-op" landmine.
})


def _canonical_pin_from_guards() -> str | None:
    """Derive the current canonical pin from the guards allowlist (last
    version-form KNOWN_GOOD entry) so this default AUTO-TRACKS pin bumps
    instead of drifting stale (it was hardcoded 600+ revs behind at dev101)."""
    try:
        from sndr.engines.vllm.detection.guards import KNOWN_GOOD_VLLM_PINS
        # entries alternate version-form ("0.23.1rc1.devN+g…") and tag-form
        # ("nightly-<sha>"); the last version-form is the freshest promotion.
        versions = [p for p in KNOWN_GOOD_VLLM_PINS if p and p[0].isdigit()]
        return versions[-1] if versions else None
    except Exception:  # noqa: BLE001
        return None


def _pin_from_pins_yaml() -> str | None:
    """Read the current pin straight from ``sndr/pins.yaml`` — the SSOT —
    WITHOUT importing the ``sndr`` package. CI runs a lean env where
    ``import sndr`` (and thus ``sndr.pins`` / the guards module) can fail on
    an optional dependency, which silently dropped resolution to the stale
    static default (dev714) and mis-flagged forward-dated patches. A bare
    file read needs only PyYAML + the committed pins.yaml, both always
    present, so the gate resolves identically on CI and locally."""
    try:
        import yaml
        with (REPO_ROOT / "sndr" / "pins.yaml").open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        cur = (data or {}).get("current")
        return str(cur) if cur else None
    except Exception:  # noqa: BLE001,S110 — SSOT read is best-effort; degrade to package/guards
        return None


def _resolve_current_pin(override: str | None = None) -> str:
    if override:
        return override
    # pins.yaml is the SSOT for "the pin we target" — prefer it over whatever
    # vllm happens to be installed in the venv. CI installs an older vllm than
    # the declared current pin, and trusting the package made forward-dated
    # patches (lower bound == current pin) falsely flag as stale on CI while
    # passing locally (regression 2026-07-05). Fall back to the installed
    # package, then guards, then the static default.
    # SSOT-first, package-import-free: direct pins.yaml read, then the sndr
    # package accessor, then guards KNOWN_GOOD, then the static default. The
    # installed vllm package is deliberately NOT consulted — "the pin we
    # target" is a repo fact, not whatever wheel is in the venv.
    direct = _pin_from_pins_yaml()
    if direct:
        return direct
    try:
        from sndr import pins
        cur = pins.current()
        if cur:
            return cur
    except Exception:  # noqa: BLE001,S110 — package accessor best-effort; degrade to guards
        pass
    return _canonical_pin_from_guards() or DEFAULT_PIN


def _parse_pep440(spec: str) -> tuple[str | None, str | None]:
    """Best-effort parse of a single PEP 440 specifier like `<0.21.0`
    or `>=0.20.2rc1.dev9`. Returns (operator, version) or (None, None)
    on parse fail."""
    spec = spec.strip()
    m = re.match(r"^(>=|<=|>|<|==|!=|~=)\s*(\S+)$", spec)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _excludes_pin(constraint: str, pin: str) -> bool:  # noqa: PLR0911 — one early-return per PEP440 operator; flat is clearer than nested
    """Does this single PEP 440 specifier EXCLUDE the current pin?

    Returns True iff the constraint is well-formed AND it deterministically
    rejects pin. Conservative: returns False on parse fail.

    Uses ``packaging.version`` for PEP 440-correct ordering — the same parser
    the runtime version-gate relies on (``sndr/compat/version_check.py``). The
    prior hand-rolled ``_ver_key`` tokeniser built mixed int/str tuples that
    raised ``TypeError: '<' not supported between 'str' and 'int'`` whenever a
    range bound carried rc/dev components (e.g. ``<0.22.1rc1.dev491``), which
    crashed the audit under ``--pin dev491``. Version objects order
    final > rc > dev natively, so a ``.devN`` upper bound now compares cleanly.
    """
    op, ver = _parse_pep440(constraint)
    if op is None:
        return False
    try:
        from packaging.version import Version
        # Drop the vllm local `+gSHA` segment; keep pre/dev components.
        pin_v = Version(pin.split("+", 1)[0])
        ver_v = Version(ver.split("+", 1)[0])
    except Exception:
        return False
    if op == "<":
        return pin_v >= ver_v
    if op == "<=":
        return pin_v > ver_v
    if op == ">":
        return pin_v <= ver_v
    if op == ">=":
        return pin_v < ver_v
    if op == "==":
        return pin_v != ver_v
    return False


def _check_range_excludes_pin(rng, pin: str) -> bool:
    """Given a vllm_version_range (tuple, list, or string), does it
    exclude the current pin?"""
    if isinstance(rng, str):
        # Comma-separated specifier string
        parts = [p.strip() for p in rng.split(",")]
        return any(_excludes_pin(p, pin) for p in parts if p)
    if isinstance(rng, (tuple, list)):
        return any(_excludes_pin(p, pin) for p in rng if isinstance(p, str))
    return False


def _import_registry():
    sys.path.insert(0, str(REPO_ROOT))
    from sndr.dispatcher.registry import PATCH_REGISTRY
    return PATCH_REGISTRY


def _build_builtin_yaml_env_map() -> dict[str, list[str]]:
    """v11.3.0 BUG #14 helper: walk every model_configs/builtin/**.yaml
    and return {env_flag → [yaml_filename, ...]} for truthy
    `GENESIS_ENABLE_<X>: '1'` lines.

    Used by the severity classifier to escalate opt-in patches that
    are enabled by some builtin YAML — those are operationally critical
    when the version range excludes the current pin (operators set the
    flag expecting the patch; the patch silently no-ops).
    """
    out: dict[str, list[str]] = {}
    yaml_dir = REPO_ROOT / "sndr" / "model_configs" / "builtin"
    if not yaml_dir.is_dir():
        return out
    flag_re = re.compile(
        r"^\s*(GENESIS_ENABLE_[A-Z0-9_]+)\s*:\s*['\"]?([^'\"\s#]+)"
    )
    for yp in yaml_dir.rglob("*.yaml"):
        try:
            text = yp.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = yp.name
        for line in text.splitlines():
            m = flag_re.match(line)
            if not m:
                continue
            value = m.group(2).strip()
            if value not in ("1", "true", "True"):
                continue
            flag = m.group(1)
            out.setdefault(flag, []).append(rel)
    return out


def _audit(pin: str) -> dict:
    registry = _import_registry()
    builtin_yaml_envs = _build_builtin_yaml_env_map()
    rows: list[dict] = []
    for pid, meta in registry.items():
        if not isinstance(meta, dict):
            continue
        lifecycle = meta.get("lifecycle", "")
        if lifecycle in ("retired", "deprecated", "legacy"):
            continue
        applies_to = meta.get("applies_to") or {}
        if not isinstance(applies_to, dict):
            continue
        rng = applies_to.get("vllm_version_range")
        if not rng:
            continue
        if not _check_range_excludes_pin(rng, pin):
            continue
        # v11.3.0 BUG #14 severity escalation: pre-compute enabled-in-prod
        # status. Patches that are opt-in (default_on=False) BUT enabled
        # by some builtin model/profile YAML are operationally CRITICAL
        # even though the legacy severity tagged them WARN — operators
        # set the env flag expecting the patch to apply, but on the
        # current pin it silently no-ops via version-range mismatch.
        default_on = bool(meta.get("default_on"))
        env_flag = meta.get("env_flag")
        enabled_in_yamls = bool(env_flag) and (env_flag in builtin_yaml_envs)
        if default_on:
            severity = "CRITICAL"
            severity_reason = "default_on=True; silently skips on every boot"
        elif enabled_in_yamls:
            severity = "CRITICAL"
            severity_reason = (
                f"enabled in {len(builtin_yaml_envs.get(env_flag, []))} "
                f"builtin YAML(s); silent no-op on this pin"
            )
        else:
            severity = "WARN"
            severity_reason = "opt-in only; not enabled by any builtin YAML"
        rows.append({
            "patch_id": pid,
            "severity": severity,
            "severity_reason": severity_reason,
            "vllm_version_range": rng,
            "lifecycle": lifecycle,
            "default_on": default_on,
            "env_flag": env_flag,
            "family": meta.get("family"),
            "enabled_in_yamls": enabled_in_yamls,
            "yaml_consumers": builtin_yaml_envs.get(env_flag, []),
        })
    # Sort by severity (CRITICAL first) then patch_id
    rows.sort(key=lambda r: (0 if r["severity"] == "CRITICAL" else 1,
                              r["patch_id"]))
    return {
        "pin": pin,
        "total_stale_ranges": len(rows),
        "critical_count": sum(1 for r in rows if r["severity"] == "CRITICAL"),
        "warn_count": sum(1 for r in rows if r["severity"] == "WARN"),
        "rows": rows,
    }


def _print_human(result: dict) -> None:
    print("=" * 70)
    print(f"Stale vllm_version_range audit — pin = {result['pin']}")
    print("=" * 70)
    print()
    print(f"Total stale ranges:    {result['total_stale_ranges']}")
    print(f"  CRITICAL: {result['critical_count']} "
          f"(default_on=True silent-skip OR enabled-in-builtin-YAML silent-no-op)")
    print(f"  WARN:     {result['warn_count']} "
          f"(opt-in only, not enabled by any YAML)")
    print()
    if result["critical_count"] > 0:
        print(
            "⚠⚠⚠ CRITICAL entries — patch silently skips when version "
            "range excludes current pin. v11.3.0 BUG #14 escalation: "
            "opt-in patches that are ENABLED IN BUILTIN YAMLs are also "
            "critical (operator-visible silent no-op)."
        )
        print()
    if result["rows"]:
        print(f"{'Severity':<10} {'Patch':<25} {'Range':<35} {'env_flag':<40}")
        print("-" * 110)
        for r in result["rows"]:
            range_str = str(r["vllm_version_range"])
            if len(range_str) > 34:
                range_str = range_str[:31] + "..."
            print(
                f"{r['severity']:<10} {r['patch_id']:<25} {range_str:<35} "
                f"{r.get('env_flag') or '':<40}"
            )
        print()
    if result["total_stale_ranges"] == 0:
        print(
            "✓ No stale version ranges. All active patches' ranges "
            "include the current pin."
        )
    else:
        print(
            f"Recommendation: bulk-update the {result['total_stale_ranges']} "
            "stale ranges to reflect the current support window. Common "
            "fix: bump upper bound from `<0.21.0` to `<0.22.0` if the "
            "patch is verified working on 0.21.x."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--pin", help="override current pin (default: pins.yaml SSOT current; "
                      "then sndr.pins, guards KNOWN_GOOD, DEFAULT_PIN)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="exit 1 if any CRITICAL entries found",
    )
    args = parser.parse_args()

    pin = _resolve_current_pin(args.pin)
    result = _audit(pin)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)

    if args.strict:
        # v11.3.0 BUG #14: --strict fails on CRITICAL entries NOT in
        # baseline allowlist. Baseline entries surface as INFO in the
        # human report but don't block CI.
        new_critical = [
            r for r in result["rows"]
            if r["severity"] == "CRITICAL"
            and r["patch_id"] not in _BASELINE_CRITICAL_STALE
        ]
        if new_critical:
            print(
                f"\n⚠ --strict failed: {len(new_critical)} CRITICAL "
                f"stale-range entries not in v11.3.0 baseline allowlist:"
            )
            for r in new_critical:
                print(
                    f"  - {r['patch_id']}: {r['vllm_version_range']} "
                    f"({r['severity_reason']})"
                )
            print(
                "\nEither bump the upper bound in registry.py (recommended) "
                "OR add to _BASELINE_CRITICAL_STALE with a justification."
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
