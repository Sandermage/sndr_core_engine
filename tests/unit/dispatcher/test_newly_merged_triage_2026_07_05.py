# SPDX-License-Identifier: Apache-2.0
"""NEWLY-MERGED triage batch 2026-07-05 — post-release-audit finding #12.

Pins the adjudication of the 11-patch NEWLY-MERGED queue (audit
2026-07-04 finding #12; PN387 + PN8 were retired in the previous batch).
Every verdict below was produced by the six-step deep-diff against the
PRISTINE dev748 image tree (rig /tmp/pristine_dev748_2dfaae752, extracted
via docker create+cp from vllm/vllm-openai:nightly-2dfaae752, verified
_version.py = 0.23.1rc1.dev748+g2dfaae752), with `gh pr view` merge
verification and `gh api compare` ancestor proofs against BOTH live pins
(dev714 base 09663abde, dev748 base 2dfaae752) on 2026-07-05.

ABSORBED -> retired with superseded_by (+ range cap where the old range
included a live pin):

  PN398  vllm#45100 MERGED 06-22: `needs_cpu_accepted_counts` guard and
         `batch_size = m.num_reqs` byte-identical native in pristine
         dev748 (gpu_model_runner.py:2057-2062, gdn_attn.py:413-416).
  PN370  same PR, 0.22.x variant of PN398 — range already <0.23.0.
  PN383  vllm#44784 MERGED 06-16: eagle-group offload gating native and
         EVOLVED (is_eagle_group is a first-class KVCacheGroup field set
         by the engine core, kv_cache_utils.py:1693; the volatile
         trailing block is excluded at scheduler level). The 0.22.x
         offloading_connector.py monolith our anchors target no longer
         exists (split into offloading/ package).
  PN252  vllm#45252 MERGED 06-13 (fix native since dev148): pristine
         dev748 _init_mrope_positions is the evolved passthrough-modality
         form with no fatal assert.
  PN362  vllm#42425 MERGED 06-16: vllm/triton_utils/force_first_config.py
         and the VLLM_TRITON_FORCE_FIRST_CONFIG env knob native
         (envs.py:113) — the module whose existence the patch's own
         credit names as its retire trigger.
  PN373  vllm#44955 MERGED 06-15: `is not False` + the merged docstring
         native at entrypoints/serve/utils/tool_calls_utils.py:22-24.
  PN379  vllm#45196 MERGED 06-17: all three vendored guard classes native
         (SafetensorsLoadStrategy Literal in config/load.py:14,
         extra-config ValueErrors + multithread/strategy reject in
         default_loader.py:80-128).
  G4_80  vllm#45040 MERGED 06-18: arm 1 (allow fp8_e5m2 KV for
         weight-only checkpoints) native evolved in
         model_executor/layers/attention/attention.py:168-183. Arm 2
         (query_quant nulling for e5m2) is NOT fixed upstream — dev748
         still creates QuantFP8 for kv_cache_dtype.startswith("fp8") and
         asserts e4m3/nvfp4 in forward — but its anchors are 0.22.x and
         the only consumer profile is archived; re-vendor trigger
         recorded in superseded_by.

KEPT — merged upstream PR does NOT supersede the Genesis patch; routed
out of the NEWLY-MERGED bucket by an explicit relationship:

  PN354  extends MERGED-pre-vendor vllm#43195 (KDA-only exp2) to the GDN
         consumers; pristine dev748 GDN chunk files still have ZERO
         USE_EXP2/RCP_LN2 (greps empty) and the chunk_o exp-site anchor
         still matches byte-identical -> related_not_superseding.
  PN293  early-exit guards on top of MERGED vllm#42430's per-build CPU
         overhead (block still present in dev748 mamba_attn.py
         _compute_common_metadata; PN293 anchor matches in the dev748
         anchor-SOT manifest) -> counter_regression.
  PN294  force-merges the attention groups MERGED vllm#43543 splits
         (num_heads_q still in the dev748 group key,
         gpu_model_runner.py:6820-6823; anchor matches in the manifest)
         -> intentional_inverse (P98 precedent). PN293/PN294 also move
         from URL-string upstream_pr to integers (audit finding #47).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

PN252_FLAG = "GENESIS_ENABLE_PN252_MROPE_PROMPT_EMBEDS_DOS"

PROD_COMPOSES = [
    "compose/prod-35b.yml",
    "compose/prod-35b-multiconc.yml",
    "compose/prod-27b-tq.yml",
    "compose/prod-27b-tq-multiconc.yml",
]

# patch_id -> upstream PR that supersedes it
RETIRED_ABSORBED = {
    "PN398": "45100",
    "PN370": "45100",
    "PN383": "44784",
    "PN252": "45252",
    "PN362": "42425",
    "PN373": "44955",
    "PN379": "45196",
    "G4_80": "45040",
}

RETIRED_MODULE_PATHS = [
    "sndr/engines/vllm/patches/spec_decode/pn398_async_accepted_counts_race.py",
    "sndr/engines/vllm/patches/spec_decode/pn370_async_accepted_counts_race.py",
    "sndr/engines/vllm/patches/offload/pn383_offload_mtp_eagle_gate.py",
    "sndr/engines/vllm/patches/worker/pn252_mrope_prompt_embeds_dos.py",
    "sndr/engines/vllm/patches/kernels/pn362_triton_force_first_config.py",
    "sndr/engines/vllm/patches/serving/pn373_parallel_toolcalls_null.py",
    "sndr/engines/vllm/patches/loader/pn379_load_config_fail_fast.py",
    "sndr/engines/vllm/patches/attention/turboquant/g4_80_fp8e5m2_kv_weight_only.py",
]


def _registry() -> dict:
    from sndr.dispatcher.registry import PATCH_REGISTRY
    return PATCH_REGISTRY


def test_absorbed_batch_retired_with_supersession():
    """All 8 absorbed patches: lifecycle=retired + superseded_by naming
    the verified-MERGED upstream PR (never a bare range-cap retire)."""
    reg = _registry()
    for pid, pr in RETIRED_ABSORBED.items():
        body = reg[pid]
        assert body["lifecycle"] == "retired", f"{pid}: lifecycle != retired"
        assert pr in str(body.get("superseded_by", "")), (
            f"{pid}: superseded_by must cite merged vllm#{pr}"
        )


def test_range_caps_on_patches_that_included_live_pins():
    """PN398 / PN379 ranges included the live 0.23.1 pins — they must cap
    below dev714 (earliest pin verified native; both PRs are ancestors of
    the dev714 base 09663abde per `gh api compare`)."""
    reg = _registry()
    for pid in ("PN398", "PN379"):
        body = reg[pid]
        rng_parts = []
        rng = body.get("vllm_version_range")
        if rng:
            rng_parts += list(rng) if isinstance(rng, (tuple, list)) else [rng]
        arng = body.get("applies_to", {}).get("vllm_version_range")
        if arng:
            rng_parts += list(arng) if isinstance(arng, (tuple, list)) else [arng]
        assert any("<0.23.1rc1.dev714" in str(p) for p in rng_parts), (
            f"{pid}: no <0.23.1rc1.dev714 cap in ranges {rng_parts!r}"
        )


def test_kept_patches_carry_honest_relationships():
    """The 3 keeps route out of NEWLY-MERGED via explicit relationship,
    NOT via retirement — the merged PRs do not supersede them."""
    reg = _registry()
    expectations = {
        "PN354": ("related_not_superseding", 43195),
        "PN293": ("counter_regression", 42430),
        "PN294": ("intentional_inverse", 43543),
    }
    for pid, (rel, pr) in expectations.items():
        body = reg[pid]
        assert body["lifecycle"] != "retired", f"{pid} must stay live"
        assert body.get("upstream_pr_relationship") == rel, (
            f"{pid}: relationship must be {rel!r}, "
            f"got {body.get('upstream_pr_relationship')!r}"
        )
        assert isinstance(body.get("upstream_pr"), int), (
            f"{pid}: upstream_pr must be an integer "
            f"(URL-string form defeats relationship routing, audit #47)"
        )
        assert body.get("upstream_pr") == pr, (
            f"{pid}: upstream_pr must be {pr}, got {body.get('upstream_pr')!r}"
        )


def test_no_backport_relationship_left_on_merged_queue():
    """Offline invariant behind the weekly gate: every patch from the
    2026-07-04 NEWLY-MERGED queue is either retired or carries a
    non-backport relationship, so `audit_upstream_status.py
    --fail-on-newly-merged` goes green once PR states are fetched."""
    reg = _registry()
    queue = list(RETIRED_ABSORBED) + ["PN354", "PN293", "PN294"]
    for pid in queue:
        body = reg[pid]
        if body["lifecycle"] == "retired":
            continue
        rel = body.get("upstream_pr_relationship")
        assert rel is not None, f"{pid}: missing upstream_pr_relationship"
        assert rel != "backport", (
            f"{pid}: still lifecycle={body['lifecycle']} with backport "
            f"relationship — would re-enter the NEWLY-MERGED action queue"
        )


def test_retired_module_docstrings_carry_marker():
    """Docstring<->lifecycle sync (audit-lifecycle-docstring-sync gate):
    the wiring modules must announce the retirement up front."""
    for rel in RETIRED_MODULE_PATHS:
        head = (REPO_ROOT / rel).read_text(encoding="utf-8")[:2500]
        assert "RETIRED 2026-07-05" in head, (
            f"{rel}: no RETIRED marker in docstring head"
        )


def test_no_pn252_flag_in_hardware_yaml():
    """PN252 was version-gated OFF on every 0.23.x pin while its '1' flag
    stayed in the shared hardware YAML — the 'enabled flag on a no-op
    patch' landmine class (PN399/PN8 precedent)."""
    hw = REPO_ROOT / "sndr/model_configs/builtin/hardware"
    offenders = [y.name for y in sorted(hw.glob("*.yaml"))
                 if PN252_FLAG in y.read_text(encoding="utf-8")]
    assert offenders == [], f"PN252 flag still set in hardware YAMLs: {offenders}"


def test_no_pn252_flag_in_prod_composes_and_digest_current():
    """The 4 generated prod composes must be REGENERATED (not hand-edited):
    PN252 flag gone AND image digest still the SSOT current digest."""
    from sndr import pins
    cur_digest = pins.current_image_digest()
    for rel in PROD_COMPOSES:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert PN252_FLAG not in txt, f"{rel}: PN252 flag still present"
        assert cur_digest in txt, (
            f"{rel}: image is not the SSOT current digest — compose not regenerated"
        )


def test_watchlist_stale_rows_refreshed():
    """Audit findings #27/#28: watchlist rows contradicted live GitHub.
    Pin the corrected statuses from the 2026-07-05 network sweep."""
    import yaml
    doc = yaml.safe_load((REPO_ROOT / "tools/upstream_watchlist.yaml")
                         .read_text(encoding="utf-8"))
    rows = {e["upstream"]: e for e in doc["watch"]}
    # claimed merged / absorbed-in-v0.24.0 on faith — PR is OPEN (audit #27)
    assert rows["vllm#40886"]["status"] == "open"
    # claimed merged — PR is OPEN
    assert rows["vllm#36138"]["status"] == "open"
    # merged action=port rows previously hidden as 'open' (audit #28)
    assert rows["vllm#40269"]["status"] == "merged"
    assert rows["vllm#37160"]["status"] == "merged"
    # fix #45656 is IN the live pins now; PN400 already retired 2026-06-24
    assert "in-pin" in str(rows["vllm#43409"].get("fix_status", "")), (
        "vllm#43409 fix_status must record that #45656 is in the live pins"
    )
    # closed-not-merged PRs previously listed as open
    for key in ("vllm#39598", "vllm#43432", "vllm#43887", "vllm#43878",
                "vllm#26504", "vllm#42006", "vllm#42237", "vllm#43074",
                "vllm#42102"):
        assert rows[key]["status"] == "closed", f"{key}: expected status closed"
