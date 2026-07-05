# SPDX-License-Identifier: Apache-2.0
"""PN372 — eagle_step zero/negative-seqlen slot-mapping guard (vendor of vllm#45005).

Contract pinned here (TDD, written before the implementation):
  1. Patcher carries TWO sub-patches: the required zero-seqlen guard
     and the optional duplicate-seq_len-load dedup (parity with the
     upstream PR's hoist; never aborts the guard if it drifts).
  2. The guard is STRICTER than upstream: ``seq_len <= 0`` (upstream
     #45005 uses ``== 0``; #40756-class traces also showed negative
     sequence lengths on corrupted rows).
  3. apply() on the pin-form (g303916e93) kernel installs the guard,
     hoists the seq_len load (exactly one load remains), and the
     result still compiles.
  4. Second apply() is idempotent (marker short-circuit).
  5. apply() on #45005's merged form self-skips via drift markers
     (reason: upstream_merged) without touching the file.
  6. Drift markers do not collide with PN372's own replacement texts
     or its Layer-6 marker line (tools/lint_drift_markers.py contract)
     AND at least one marker is an exact substring of the merged form.
  7. Anchors are unique and drift markers absent in the pristine pin
     tree (opportunistic — skipped when the pin tree is not present).
  8. The module documents the P108 retirement criterion (A/B planned;
     P108 itself is NOT touched) and references the registry env flag.
"""
from __future__ import annotations

import os
from pathlib import Path

# The lint/preflight tools disable the Layer-0 file cache the same way;
# unit tests patch fresh tmp files, so the cache must never satisfy
# apply() from a previous run's state.
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.spec_decode import (  # noqa: E402
    pn372_eagle_step_zero_seqlen_guard as m,
)
from tests.unit.anchor_sot._pin_manifest_assert import (  # noqa: E402
    assert_anchor_recorded,
    assert_replacement_recorded,
)

# ── Fake targets ─────────────────────────────────────────────────────
# Pin-form (g303916e93): the fused eagle_step slot-mapping kernel in
# v1/spec_decode/utils.py — byte-faithful copy of the anchor regions.

PIN_UTILS = (
    "# fake v1/spec_decode/utils.py (pin g303916e93 form)\n"
    "PADDING_SLOT_ID = -1\n"
    "\n"
    "\n"
    "@triton.jit\n"
    "def eagle_step_slot_mapping_metadata_kernel(\n"
    "    positions_ptr,\n"
    "    block_table_ptr,\n"
    "    block_table_stride,\n"
    "    seq_lens_ptr,\n"
    "    out_clamped_positions_ptr,\n"
    "    out_slot_mapping_ptr,\n"
    "    block_size: tl.constexpr,\n"
    "    max_model_len: tl.constexpr,\n"
    "    n_blocks_per_req: tl.constexpr,\n"
    "    PAD_ID: tl.constexpr,\n"
    "    batch_size,\n"
    "):\n"
    "    req_idx = tl.program_id(0)\n"
    "\n"
    "    if req_idx >= batch_size:\n"
    "        tl.store(out_slot_mapping_ptr + req_idx, PAD_ID)\n"
    "        return\n"
    "\n"
    "    # Load current position and increment\n"
    "    position = tl.load(positions_ptr + req_idx)\n"
    "    new_position = position + 1\n"
    "\n"
    "    # Check bounds and compute clamped position\n"
    "    exceeds_max = new_position >= max_model_len\n"
    "    clamped_position = tl.where(exceeds_max, 0, new_position)\n"
    "\n"
    "    # Block table lookup: block_number = position // block_size\n"
    "    # Clamp block_number to avoid OOB when position is at max\n"
    "    block_number = clamped_position // block_size\n"
    "    block_number = tl.minimum(block_number, n_blocks_per_req - 1)\n"
    "\n"
    "    block_id = tl.load(block_table_ptr + req_idx * block_table_stride"
    " + block_number)\n"
    "    slot_id = block_id * block_size + (clamped_position % block_size)\n"
    "    slot_id = tl.where(exceeds_max, PAD_ID, slot_id)\n"
    "\n"
    "    # Update seq_lens: +1 normally, or 1 if exceeded\n"
    "    seq_len = tl.load(seq_lens_ptr + req_idx)\n"
    "    new_seq_len = tl.where(exceeds_max, 1, seq_len + 1)\n"
    "    new_seq_len = tl.minimum(new_seq_len, max_model_len)\n"
    "\n"
    "    # Store outputs\n"
    "    tl.store(out_clamped_positions_ptr + req_idx, clamped_position)\n"
    "    tl.store(out_slot_mapping_ptr + req_idx, slot_id)\n"
    "    tl.store(seq_lens_ptr + req_idx, new_seq_len)\n"
)

# #45005 merged form (what utils.py looks like AFTER upstream lands the
# guard) — PN372 must self-skip on this. Exact hunk text from
# `gh pr diff 45005` (2026-06-11): comment pair + `== 0` guard inserted
# after the cudagraph-padding early-return, duplicate load removed.

MERGED_UTILS = PIN_UTILS.replace(
    "    # Load current position and increment\n"
    "    position = tl.load(positions_ptr + req_idx)\n"
    "    new_position = position + 1\n",
    "    # Padded rows inside the captured batch can have seq_lens == 0 and\n"
    "    # block_table entries of -1. Do not advance them into a real request.\n"
    "    seq_len = tl.load(seq_lens_ptr + req_idx)\n"
    "    if seq_len == 0:\n"
    "        tl.store(out_clamped_positions_ptr + req_idx, 0)\n"
    "        tl.store(out_slot_mapping_ptr + req_idx, PAD_ID)\n"
    "        return\n"
    "\n"
    "    # Load current position and increment\n"
    "    position = tl.load(positions_ptr + req_idx)\n"
    "    new_position = position + 1\n",
).replace(
    "    # Update seq_lens: +1 normally, or 1 if exceeded\n"
    "    seq_len = tl.load(seq_lens_ptr + req_idx)\n"
    "    new_seq_len = tl.where(exceeds_max, 1, seq_len + 1)\n",
    "    # Update seq_lens: +1 normally, or 1 if exceeded\n"
    "    new_seq_len = tl.where(exceeds_max, 1, seq_len + 1)\n",
).replace(
    "(pin g303916e93 form)", "(post-vllm#45005 merged form)"
)

SEQ_LEN_LOAD = "seq_len = tl.load(seq_lens_ptr + req_idx)"


# ── Helpers ──────────────────────────────────────────────────────────


def _install_fake(tmp_path, monkeypatch, utils_text):
    target = tmp_path / "utils.py"
    target.write_text(utils_text, encoding="utf-8")
    monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: str(target))
    # apply() is dispatcher-gated (opt-in env flag, registry-driven) —
    # force the gate open for unit tests of the patch mechanics.
    from sndr import dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_patcher_has_guard_and_dedup_subs(self, tmp_path, monkeypatch):
        _install_fake(tmp_path, monkeypatch, PIN_UTILS)
        patcher = m._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert "pn372_zero_seqlen_guard" in by_name
        assert "pn372_seq_len_load_dedup" in by_name
        assert by_name["pn372_zero_seqlen_guard"].required is True
        # Dedup is parity with #45005's hoist — never abort the guard
        # if this anchor drifts (a second load is redundant, not wrong).
        assert by_name["pn372_seq_len_load_dedup"].required is False

    def test_guard_is_stricter_than_upstream(self):
        """Roadmap chunk-3 Theme A: `<= 0` (upstream uses `== 0`) —
        #40756-class traces showed NEGATIVE lens on corrupted rows."""
        assert "if seq_len <= 0:" in m.PN372_GUARD_NEW
        assert "if seq_len == 0:" not in m.PN372_GUARD_NEW

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        assert m._make_patcher() is None

    def test_module_documents_p108_retirement_criterion(self):
        """The docstring must carry the P108 success criterion: with the
        guard validated, P108's draft-loop synchronize becomes redundant
        (A/B planned — P108 is NOT touched by this patch)."""
        doc = m.__doc__ or ""
        assert "P108" in doc
        assert "45005" in doc
        assert "40756" in doc

    def test_module_references_registry_env_flag(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_PN372_EAGLE_ZERO_SEQLEN_GUARD" in src


# ── Apply semantics ──────────────────────────────────────────────────


class TestApply:
    def test_apply_pin_form_installs_guard_and_hoists_load(
        self, tmp_path, monkeypatch
    ):
        target = _install_fake(tmp_path, monkeypatch, PIN_UTILS)
        status, reason = m.apply()
        assert status == "applied", reason

        out = target.read_text(encoding="utf-8")
        # Stricter guard installed.
        assert "if seq_len <= 0:" in out
        # Guard parks the row: clamped position 0 + padding slot.
        guard_pos = out.index("if seq_len <= 0:")
        guard_body = out[guard_pos:guard_pos + 250]
        assert "tl.store(out_clamped_positions_ptr + req_idx, 0)" in guard_body
        assert "tl.store(out_slot_mapping_ptr + req_idx, PAD_ID)" in guard_body
        assert "return" in guard_body
        # The load is hoisted into the guard — exactly one load remains
        # (the later duplicate is removed by the dedup sub-patch).
        assert out.count(SEQ_LEN_LOAD) == 1
        assert out.index(SEQ_LEN_LOAD) < out.index("position = tl.load")
        # Guard sits BEFORE the position load (the unguarded advance).
        assert out.index("if seq_len <= 0:") < out.index("position = tl.load")
        # seq_lens of parked rows stay untouched: no store before return.
        # The only seq_lens store remains the end-of-kernel one.
        assert out.count("tl.store(seq_lens_ptr + req_idx, new_seq_len)") == 1
        # File still compiles after the splice.
        compile(out, str(target), "exec")

    def test_second_apply_is_idempotent(self, tmp_path, monkeypatch):
        _install_fake(tmp_path, monkeypatch, PIN_UTILS)
        first_status, first_reason = m.apply()
        assert first_status == "applied", first_reason
        # Canonical result_to_wiring_status contract: IDEMPOTENT maps to
        # ("skipped", "...: already applied (marker present)").
        second_status, second_reason = m.apply()
        assert second_status == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_45005_merged_form(self, tmp_path, monkeypatch):
        target = _install_fake(tmp_path, monkeypatch, MERGED_UTILS)
        status, reason = m.apply()
        assert status == "skipped"
        assert "upstream_merged" in reason
        # Self-skip must not modify the merged file.
        assert target.read_text(encoding="utf-8") == MERGED_UTILS

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        """Opt-in patch (default_on=False): with the dispatcher gate
        closed (env flag unset / registry says no), apply() must skip
        without touching the target."""
        target = tmp_path / "utils.py"
        target.write_text(PIN_UTILS, encoding="utf-8")
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: str(target))
        from sndr import dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN372_EAGLE_ZERO_SEQLEN_GUARD", raising=False
        )
        status, _reason = m.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_UTILS

    def test_apply_skips_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        from sndr import dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (True, "test override")
        )
        status, _reason = m.apply()
        assert status == "skipped"


# ── Lint contract (tools/lint_drift_markers.py) ──────────────────────


class TestDriftMarkerSelfCollision:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install_fake(tmp_path, monkeypatch, PIN_UTILS)
        patcher = m._make_patcher()
        marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
        assert patcher.upstream_drift_markers, "drift markers must exist"
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue  # defended convention — exempt
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement, (
                    f"drift marker {dm!r} collides with {sp.name} "
                    "replacement — would false-fire Layer 3 (PN369 class)"
                )
            assert dm not in marker_line

    def test_markers_match_45005_merged_form(self, tmp_path, monkeypatch):
        """Markers must actually fire on the real merged form —
        the PN367-v1 regression was markers that could never match."""
        _install_fake(tmp_path, monkeypatch, PIN_UTILS)
        patcher = m._make_patcher()
        assert any(
            dm in MERGED_UTILS for dm in patcher.upstream_drift_markers
        )


# ── Pristine pin invariants (opportunistic) ──────────────────────────


class TestPn372InCurrentPinManifest:
    # Audit finding #14: the previous ``TestAnchorsAgainstPristinePin`` class
    # byte-checked the anchors against a macOS-only pristine pin tree
    # (absent on every CI host -> permanently green-by-skip). MIGRATED here to
    # read the COMMITTED per-pin manifest so it RUNS in CI, and STRENGTHENED to
    # tie the LIVE patcher anchors + replacements to the recorded pristine
    # bytes (``merge_status == not_merged`` == drift markers absent). The
    # fixture-drift trap never needed the pin tree and now runs unconditionally.
    def test_anchors_recorded_and_replacements_tied(self):
        for sub, old, new in (
            ("pn372_zero_seqlen_guard", m.PN372_GUARD_OLD, m.PN372_GUARD_NEW),
            ("pn372_seq_len_load_dedup", m.PN372_DEDUP_OLD, m.PN372_DEDUP_NEW),
        ):
            assert_anchor_recorded("PN372", sub, old)
            assert_replacement_recorded("PN372", sub, new)

    def test_fixture_anchor_regions_present(self):
        """The fake pin-form fixture must carry the EXACT anchor bytes so the
        apply-tests exercise real anchors (fixture-drift trap)."""
        assert m.PN372_GUARD_OLD in PIN_UTILS
        assert m.PN372_DEDUP_OLD in PIN_UTILS
