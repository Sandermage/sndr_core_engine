# SPDX-License-Identifier: Apache-2.0
"""Retire batch 2026-07-05 — post-release-audit remediation (PN387 + PN8).

Pins the adjudication produced by the six-step deep-diff (2026-07-05):

  PN387 (vendor of vllm#45346, degenerate-structured-outputs DoS guard):
    #45346 MERGED 2026-06-30 (merge commit ac521f62); both guards verified
    byte-identical NATIVE in the pristine dev714 AND dev748 images (docker
    run --entrypoint python3 ... sampling_params.py greps, 2026-07-05).
    Outcome (a) byte-identical -> retired with superseded_by + range cap.
    The Genesis Layer-2 edge guard was defence-in-depth over the same
    reject; the native validation-time fix already returns the 400.

  PN8 (backport of vllm#40849, MTP draft online-quant propagation):
    #40849 is still OPEN (gh pr view 2026-07-05: mergedAt null) and the
    feature is NOT native — pristine dev748 get_draft_quant_config() is
    the vanilla non-inheriting form with no OnlineQuantizationConfig import
    in utils.py. The dev672 CHANGELOG "native now" adjudication was a
    title-match-class error: only the IMPORTS anchor drifted (the
    QuantizationConfig import moved), so PN8 benign-skips since dev672.
    Retired WITHOUT supersession (waiver): unmaintained no-op stop-gap; no
    current lane runs online-quant + external draft. Re-vendor if #40849
    merges or an FP8-target + external-draft stack lands.

  Flag hygiene: the enabled-'1' PN8 flags in 4 model YAMLs and the 4
  generated prod composes were the "enabled flag on a no-op patch"
  landmine class (PN399 precedent) with a misleading "~1 GiB/rank" VRAM
  comment; composes regenerated (which also picks up the dev748
  image_digest fixed in the audit-remediation branch).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

PN8_FLAG = "GENESIS_ENABLE_PN8_MTP_DRAFT_ONLINE_QUANT"

PROD_COMPOSES = [
    "compose/prod-35b.yml",
    "compose/prod-35b-multiconc.yml",
    "compose/prod-27b-tq.yml",
    "compose/prod-27b-tq-multiconc.yml",
]


def _registry() -> dict:
    from sndr.dispatcher.registry import PATCH_REGISTRY
    return PATCH_REGISTRY


def test_pn387_retired_with_supersession_provenance():
    """PN387 Layer 1 is byte-identical native in every live pin — outcome
    (a) of the deep-diff table: retired + superseded_by + range cap."""
    body = _registry()["PN387"]
    assert body["lifecycle"] == "retired"
    assert "45346" in str(body.get("superseded_by", "")), (
        "PN387 superseded_by must name the merged upstream PR #45346")
    rng = body.get("vllm_version_range")
    assert rng, "PN387 needs a top-level vllm_version_range cap"
    assert any("<0.23.1rc1.dev714" in str(part) for part in
               (rng if isinstance(rng, (tuple, list)) else (rng,))), (
        f"PN387 range must cap below dev714 (earliest pin verified native), got {rng!r}")


def test_pn8_retired_without_supersession():
    """PN8's upstream PR #40849 is OPEN and the feature is NOT native —
    retiring it as 'absorbed' would repeat the title-matching class error.
    It retires as an unmaintained no-op stop-gap via the no-supersede
    waiver, with an honest range cap at the last pin the anchor applied."""
    body = _registry()["PN8"]
    assert body["lifecycle"] == "retired"
    # Honest provenance: NOT superseded (PR open, feature absent upstream).
    assert "40849" not in str(body.get("superseded_by", "")) or \
        "OPEN" in str(body.get("superseded_by", "")), (
        "PN8 must not claim supersession by the still-OPEN #40849")
    rng = body.get("vllm_version_range")
    assert rng, "PN8 needs a top-level vllm_version_range cap"
    assert any("<0.23.1rc1.dev672" in str(part) for part in
               (rng if isinstance(rng, (tuple, list)) else (rng,))), (
        f"PN8 range must cap below dev672 (anchor gone since), got {rng!r}")
    # The meta-test waiver must carry PN8 (retire-without-supersede path).
    meta = (REPO_ROOT / "tests/unit/dispatcher/test_iron_rule_11_enforcement.py"
            ).read_text(encoding="utf-8")
    assert '"PN8"' in meta.split("_RETIRED_NO_SUPERSEDE_WAIVER = {")[1].split("}")[0], (
        "PN8 missing from _RETIRED_NO_SUPERSEDE_WAIVER")


def test_retired_module_docstrings_carry_marker():
    """Docstring<->lifecycle sync: both wiring modules must open with the
    RETIRED marker so a future reader does not re-enable them by habit."""
    for rel in (
        "sndr/engines/vllm/patches/serving/pn387_reject_degenerate_structured_outputs.py",
        "sndr/engines/vllm/patches/loader/pn8_mtp_draft_online_quant_propagation.py",
    ):
        head = (REPO_ROOT / rel).read_text(encoding="utf-8")[:2500]
        assert "RETIRED 2026-07-05" in head, f"{rel}: no RETIRED marker in docstring head"


def test_no_pn8_flag_in_builtin_model_yamls():
    """The '1' flags on the no-op patch were VRAM-budgeting landmines
    (operators budgeted ~1 GiB/rank for a patch that never applies)."""
    mdir = REPO_ROOT / "sndr/model_configs/builtin/model"
    offenders = [y.name for y in sorted(mdir.glob("*.yaml"))
                 if PN8_FLAG in y.read_text(encoding="utf-8")]
    assert offenders == [], f"PN8 flag still set in model YAMLs: {offenders}"


def test_no_pn8_flag_in_prod_composes_and_digest_current():
    """The 4 generated prod composes must be REGENERATED (not hand-edited):
    PN8 flag gone AND the image digest equal to the SSOT current digest
    (they were stuck on the dev714 digest before the regen)."""
    from sndr import pins
    cur_digest = pins.current_image_digest()
    for rel in PROD_COMPOSES:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert PN8_FLAG not in txt, f"{rel}: PN8 flag still present"
        assert cur_digest in txt, (
            f"{rel}: image is not the SSOT current digest — compose not regenerated")
