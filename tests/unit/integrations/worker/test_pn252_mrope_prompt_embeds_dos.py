# SPDX-License-Identifier: Apache-2.0
"""TDD for PN252 — M-RoPE prompt_embeds-only DoS fix (vllm#45252 /
GHSA-33cg-gxv8-3p8g).

The fixture below is the byte-exact `_init_mrope_positions` +
`_init_xdrope_positions` pair from the live pins (dev259 PROD + dev491
candidate — verified identical 2026-06-14). It guards two things:

  1. The patch removes the fatal `assert prompt_token_ids is not None`
     and rewrites the call site to derive a non-None token sequence, so a
     prompt_embeds-only request never crashes EngineCore.
  2. The sibling `_init_xdrope_positions` (which also asserts
     `prompt_token_ids is not None`) is LEFT UNTOUCHED — the anchor
     envelope (supports_mrope + cast(SupportsMRoPE)) disambiguates.

If a pin bump drifts the anchor, the patch SKIPs (required_anchor_missing)
rather than silently mangling unrelated code — asserted here so a drift
fails loudly in CI instead of letting the security fix go dark.
"""
from __future__ import annotations

import py_compile

import pytest

from sndr.kernel import TextPatch, TextPatcher, TextPatchResult
import sndr.engines.vllm.patches.worker.pn252_mrope_prompt_embeds_dos as M


# Byte-exact from dev259 / dev491 v1/worker/gpu_model_runner.py.
PRISTINE = '''from typing import cast


class GpuModelRunner:
    def _init_mrope_positions(self, req_state):
        model = self.get_model()
        assert supports_mrope(model), "M-RoPE support is not implemented."
        assert req_state.prompt_token_ids is not None, (
            "M-RoPE requires prompt_token_ids to be available."
        )
        mrope_model = cast(SupportsMRoPE, model)

        # `prompt_embeds` is a passthrough modality (no grid_thw), models'
        # M-RoPE code assumes per-feature grid info, so filter it out. The
        # prompt_embeds positions are treated as text positions for M-RoPE.
        mrope_features = [
            f for f in req_state.mm_features if f.modality != "prompt_embeds"
        ]
        req_state.mrope_positions, req_state.mrope_position_delta = (
            mrope_model.get_mrope_input_positions(
                req_state.prompt_token_ids,
                mrope_features,
            )
        )

    def _init_xdrope_positions(self, req_state):
        model = self.get_model()
        xdrope_model = cast(SupportsXDRoPE, model)
        assert req_state.prompt_token_ids is not None, (
            "XD-RoPE requires prompt_token_ids to be available."
        )
        assert supports_xdrope(model), "XD-RoPE support is not implemented."

        req_state.xdrope_positions = xdrope_model.get_xdrope_input_positions(
            req_state.prompt_token_ids,
            req_state.mm_features,
        )
'''


def _patcher(target: str) -> TextPatcher:
    return TextPatcher(
        patch_name="PN252-test",
        target_file=target,
        marker=M.GENESIS_PN252_MARKER,
        sub_patches=[
            TextPatch(
                name="pN252_drop_fatal_prompt_token_ids_assert",
                anchor=M.PN252_PART1_ANCHOR,
                replacement=M.PN252_PART1_REPLACEMENT,
                required=True,
            ),
            TextPatch(
                name="pN252_derive_non_none_token_sequence",
                anchor=M.PN252_PART2_ANCHOR,
                replacement=M.PN252_PART2_REPLACEMENT,
                required=True,
            ),
        ],
        upstream_drift_markers=[],
    )


def _write(tmp_path, text):
    f = tmp_path / "gpu_model_runner.py"
    f.write_text(text)
    return str(f)


class TestAnchorsMatchPristine:
    def test_both_anchors_appear_exactly_once(self):
        assert PRISTINE.count(M.PN252_PART1_ANCHOR) == 1
        assert PRISTINE.count(M.PN252_PART2_ANCHOR) == 1

    def test_part1_anchor_does_not_match_xdrope(self):
        # The xdrope assert is present but its envelope (cast BEFORE the
        # assert, XD-RoPE message) differs — PART1 anchor must not match it.
        assert "XD-RoPE requires prompt_token_ids" in PRISTINE
        # PART1 anchor is the M-RoPE-specific bundle only.
        assert "M-RoPE support is not implemented" in M.PN252_PART1_ANCHOR
        assert "XD-RoPE" not in M.PN252_PART1_ANCHOR


class TestApply:
    def test_applies_both_subpatches(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        p = _patcher(target)
        result, failure = p.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert sorted(p.applied_sub_patches) == [
            "pN252_derive_non_none_token_sequence",
            "pN252_drop_fatal_prompt_token_ids_assert",
        ]

    def test_result_is_valid_python(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        py_compile.compile(target, doraise=True)  # raises on syntax error

    def test_fatal_mrope_assert_removed(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        out = open(target).read()
        assert "M-RoPE requires prompt_token_ids to be available" not in out

    def test_xdrope_assert_left_untouched(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        out = open(target).read()
        # The sibling xdrope path keeps ITS assert — we only fixed M-RoPE.
        assert "XD-RoPE requires prompt_token_ids to be available" in out

    def test_prompt_embeds_ladder_present(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        out = open(target).read()
        assert "if req_state.prompt_token_ids is not None:" in out
        assert "list(range(req_state.prompt_embeds.shape[0]))" in out
        assert "raise ValueError(" in out

    def test_idempotent_on_reapply(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        result2, _ = _patcher(target).apply()
        assert result2 == TextPatchResult.IDEMPOTENT


class TestDriftSafety:
    def test_missing_anchor_skips_not_corrupts(self, tmp_path):
        # Simulate an upstream merge: the fatal assert is gone. PART1's
        # required anchor no longer matches -> whole patcher SKIPs.
        merged = PRISTINE.replace(
            M.PN252_PART1_ANCHOR,
            "        mrope_model = cast(SupportsMRoPE, model)\n",
        )
        target = _write(tmp_path, merged)
        result, failure = _patcher(target).apply()
        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "required_anchor_missing"
        # File unchanged (no marker prepended).
        assert M.GENESIS_PN252_MARKER not in open(target).read()


class TestDispatcherWiring:
    def test_registry_entry_well_formed(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY

        meta = PATCH_REGISTRY["PN252"]
        assert meta["family"] == "worker"
        assert meta["env_flag"] == "GENESIS_ENABLE_PN252_MROPE_PROMPT_EMBEDS_DOS"
        assert meta["upstream_pr"] == 45252
        assert meta["apply_module"].endswith("pn252_mrope_prompt_embeds_dos")

    def test_apply_skips_when_not_opted_in(self, monkeypatch):
        # Strict opt-in: without the ENABLE env flag and without a live vllm
        # tree, apply() returns ("skipped", reason) — never raises.
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN252_MROPE_PROMPT_EMBEDS_DOS", raising=False
        )
        monkeypatch.delenv("GENESIS_LEGACY_DEFAULT_ON", raising=False)
        status, reason = M.apply()
        assert status == "skipped"
        assert isinstance(reason, str) and reason
