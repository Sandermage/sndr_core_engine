# SPDX-License-Identifier: Apache-2.0
"""Open-PR triage 2026-07-05 — vllm#47609 / #47611 / #47593 verdicts.

Pins the six-step adjudication of the three OPEN upstream PRs studied on
2026-07-05 (gh pr view/diff captured; pristine dev748 tree line-reads on
the rig /tmp/pristine_dev748_2dfaae752, _version.py verified
0.23.1rc1.dev748+g2dfaae752):

  #47609 [Bugfix][TurboQuant] preserve KV cache dtype in backend shape —
         NOT needed on dev748 (attn_utils.py has no KVQuantMode.NONE
         conditional; cache_dtype passes straight through at :308) but a
         MANDATORY next-bump gate item: its regression source #42890
         (MERGED 2026-07-04, AFTER the dev748 cut 2026-07-03T04:11Z)
         makes the v1 reshape pass cache_dtype_str='auto' for
         KVQuantMode.NONE while TQFullAttentionSpec still needs the real
         'turboquant_k8v4' string -> engine startup ValueError. BOTH
         heavy lanes run TQ k8v4, so any pin cut after 2026-07-04
         HARD-FAILS BOOT unless #47609 (or an equivalent backport) is in.
         Gate wiring pinned here: two UPSTREAM_MARKERS entries (regression
         arrival + fix arrival, byte-exact strings from the PR diffs,
         both verified ABSENT on pristine dev748) + sweep rows for #47609
         and #42890 (the latter binding the G4_60E vendored-mirror
         re-study — g4_60e_kv_cache_utils.py mirrors the exact
         _reshape_kv_cache logic #42890 rewrites).

  #47611 [Bugfix][MoE] older FlashInfer FP8 MoE signatures — IRRELEVANT:
         regression source #45723 IS in dev748 (unconditional gemm1_alpha
         at trtllm_fp8_moe.py:234/405) but the dispatch is gated
         is_device_capability_family(100) + has_flashinfer_trtllm_fused_moe
         (trtllm_fp8_moe.py:98-99) = Blackwell SM100 only; 2x A5000 =
         SM86 never selects TrtLlmFp8Experts. No Genesis patch touches
         trtllm_fp8_moe.py. Recorded as a sweep row so future sweeps do
         not re-study it.

  #47593 [Kernel][Perf] tokens-per-expert M-tile heuristic — IRRELEVANT
         to the current stack: the fp8_w8a8 [128,128] triton branch it
         rewrites never executes on our rig (Ampere FP8 MoE -> FP8
         Marlin; 35B PROD AWQ Marlin; G4 26B WNA16 branch untouched;
         decode M under the unchanged M<=64 floor). Anchor-collision
         audited: P24 anchor-1 targets the exact line #47593 rewrites but
         is ALREADY dead on dev748 (pre-existing #46642-era drift, soft
         required=False skip); #47593 does not touch P24's live anchor-2
         region. P81 = idea-family overlap, different kernel/file,
         outcome (c) both keep.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

WATCHLIST = REPO_ROOT / "tools" / "upstream_watchlist.yaml"

# Byte-exact strings from the PR diffs (gh pr diff 42890 / 47609,
# captured 2026-07-05). Both verified ABSENT in pristine dev748
# vllm/v1/worker/gpu/attn_utils.py so neither marker can false-fire as
# newly_merged on the current pin.
MARKER_42890 = "if kv_cache_spec.kv_quant_mode == KVQuantMode.NONE"
MARKER_47609 = "and not isinstance(kv_cache_spec, TQFullAttentionSpec)"
ATTN_UTILS_REL = "v1/worker/gpu/attn_utils.py"


def _sweep_rows() -> dict[int, dict]:
    import yaml
    doc = yaml.safe_load(WATCHLIST.read_text(encoding="utf-8"))
    return {row["pr"]: row for row in doc.get("sweep", [])}


def test_sweep_rows_exist_for_all_three_prs_plus_regression_source():
    rows = _sweep_rows()
    for pr in (47609, 42890, 47611, 47593):
        assert pr in rows, f"missing sweep row for vllm#{pr}"
        assert rows[pr]["trigger"] == "review-on-merge", (
            f"vllm#{pr}: expected advisory review-on-merge, got "
            f"{rows[pr]['trigger']!r}"
        )


def test_47609_row_records_the_boot_blocker_gate():
    """The #47609 row is the pin-bump preflight watchlist item: it must
    name the regression source, the TQ k8v4 boot-blocker class, and the
    backport plan for the still-unmerged case."""
    row = _sweep_rows()[47609]
    # No vendored patch yet — backport only if still unmerged at bump time.
    assert row["genesis_patch"].lower().startswith("planned:")
    note = row["note"]
    for needle in ("42890", "turboquant_k8v4", "BOOT", "layer_cache_dtype = ("):
        assert needle in note, f"#47609 note missing {needle!r}"


def test_42890_row_binds_the_g4_60e_mirror_restudy():
    """#42890 entering a pin stales the G4_60E vendored mirror of
    _reshape_kv_cache — the row must bind that re-study to a LIVE patch."""
    row = _sweep_rows()[42890]
    assert "G4_60E" in row["genesis_patch"]
    note = row["note"]
    for needle in ("_reshape_kv_cache", "47609", "g4_60e_kv_cache_utils"):
        assert needle in note, f"#42890 note missing {needle!r}"
    # The bound patch must be live (review rows are not tool-checked).
    from sndr.dispatcher.registry import PATCH_REGISTRY
    assert PATCH_REGISTRY["G4_60E"]["lifecycle"] != "retired"


def test_47611_row_records_sm100_dormancy():
    row = _sweep_rows()[47611]
    assert row["genesis_patch"] == "watch-only"
    note = row["note"]
    for needle in ("45723", "SM100", "SM86", "trtllm_fp8_moe.py"):
        assert needle in note, f"#47611 note missing {needle!r}"


def test_47593_row_records_dormant_branch_and_p24_audit():
    row = _sweep_rows()[47593]
    assert "P24" in row["genesis_patch"]
    note = row["note"]
    for needle in ("fp8_w8a8", "Marlin", "P81", "46642"):
        assert needle in note, f"#47593 note missing {needle!r}"
    # P24 must still be live for the note's anchor facts to stay auditable.
    from sndr.dispatcher.registry import PATCH_REGISTRY
    assert PATCH_REGISTRY["P24"]["lifecycle"] != "retired"


def test_new_rows_pass_the_sweep_schema():
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from check_upstream_watchlist import load_sweep, validate_rows
    rows = load_sweep(WATCHLIST)
    assert validate_rows(rows) == []


def test_upstream_markers_gate_the_42890_boot_blocker():
    """Mechanical next-bump gate: the preflight marker walk must flag
    newly_merged the moment a candidate pin carries #42890 (regression
    arrival) and, independently, #47609 (fix arrival)."""
    from sndr.engines.vllm.upstream_compat import UPSTREAM_MARKERS

    reg = {k: v for k, v in UPSTREAM_MARKERS.items() if "42890" in k}
    assert len(reg) == 1, "expected exactly one PR_42890 marker entry"
    entry = next(iter(reg.values()))
    assert entry["file"] == ATTN_UTILS_REL
    assert entry["marker"] == MARKER_42890
    # A regression-arrival marker must never be pre-waived as known-merged.
    assert not any(entry.get(k) for k in entry
                   if k.startswith("verified_in_main_"))
    assert "47609" in entry["description"]

    fix = {k: v for k, v in UPSTREAM_MARKERS.items() if "47609" in k}
    assert len(fix) == 1, "expected exactly one PR_47609 marker entry"
    fentry = next(iter(fix.values()))
    assert fentry["file"] == ATTN_UTILS_REL
    assert fentry["marker"] == MARKER_47609
    assert not any(fentry.get(k) for k in fentry
                   if k.startswith("verified_in_main_"))
