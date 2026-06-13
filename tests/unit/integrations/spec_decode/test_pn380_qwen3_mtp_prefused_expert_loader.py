# SPDX-License-Identifier: Apache-2.0
"""TDD for PN380 — vendor of OPEN PR vllm#44943 (Qwen3.5/3.6 MTP
pre-fused expert loader) + Genesis-original draft-weight load-coverage
guard.

Upstream bug (#44943): ``Qwen3_5MultiTokenPredictor.load_weights`` only
recognizes ``experts.gate_up_proj`` / ``experts.down_proj`` as fused-
expert SOURCE names. Community AutoRound/GPTQ quants of Qwen3.5/3.6 MoE
(and manually-renamed checkpoints working around vllm#36954) store the
expert tensors under the fused-form names ``experts.w13_weight`` /
``experts.w2_weight`` directly. Unpatched failure modes:

  - MTP quantized: every expert tensor falls through to the
    ``params_dict``-miss fallback -> partial draft load -> spec-decode
    accept rate collapses (~65% -> ~42% in the upstream A/B).
  - MTP unquantized: ``TypeError: FusedMoE.weight_loader() missing 3
    required positional arguments`` -> engine crash at startup.

ADAPTATION (iron rule #10): the PR head builds
``fused_expert_params_mapping`` in a loop and appends an
``alt_ckpt_name`` variant per entry; our pin (g303916e93) carries the
older STATIC two-entry list, so PN380 appends two static pre-fused
entries instead. ``alt_ckpt_name`` is therefore a safe upstream drift
marker (never appears in our emitted text).

GENESIS EXTRAS (roadmap chunk-4 Theme 2 "loud startup" family):
  - draft-weight load-coverage guard (P29-style loud-failure
    conversion): counts checkpoint tensors that found no matching param
    AND expected params that received no checkpoint weight, emits ONE
    ``logger.error`` on any gap. The engine's strict coverage check
    (``DefaultModelLoader.track_weights_loading``) is disabled whenever
    ``model_config.quantization`` is set — exactly our FP8/INT4 PROD.

COMPOSITION: PN348 (vendor of vllm#44644) text-patches the SAME file
(``models/qwen3_5_mtp.py``) — its three anchors (embed_tokens
predicate / lm_head fallthrough / remap_weight_names skip) are all
OUTSIDE the ``Qwen3_5MultiTokenPredictor.load_weights`` body PN380
patches. Disjointness + both co-apply orders are asserted below.

These tests verify textually (portable embedded fixture, byte-verified
against pin 0.22.1rc1.dev259+g303916e93) and opportunistically against
the real pristine tree at /private/tmp/candidate_pin_current:
  1. anchors unique (count==1) on fixture + real pin; drift markers
     absent from pristine
  2. end-to-end TextPatcher apply on tmp copies — all 6 sub-patches,
     result compiles, idempotent on second apply
  3. co-apply with PN348 in BOTH orders on the real pin file
  4. replacement contract — faithful #44943 semantics + coverage guard
  5. functional coverage-guard behavior (exec harness, no torch)
  6. self-collision invariants (tools/lint_drift_markers.py contract)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PIN_TREE = Path("/private/tmp/candidate_pin_current/vllm")
PIN_MODEL = PIN_TREE / "model_executor" / "models" / "qwen3_5_mtp.py"

# Pin bump 2026-06-13: dev259 (CURRENT PROD) -> dev491 (CANDIDATE). PN380
# Sub-1 (mapping) is DUAL-ANCHOR — Variant A targets the dev259 static
# list, Variant B targets the dev491 loop build. These tests verify
# Variant B against the dev491 pristine tree when present.
PIN_TREE_DEV491 = Path("/tmp/candidate_pin_new/vllm")
PIN_MODEL_DEV491 = PIN_TREE_DEV491 / "model_executor" / "models" / "qwen3_5_mtp.py"


def _pn380():
    from sndr.engines.vllm.patches.spec_decode import (
        pn380_qwen3_mtp_prefused_expert_loader as M,
    )
    return M


def _pn348():
    from sndr.engines.vllm.patches.spec_decode import (
        pn348_qwen3_mtp_backbone_dedup as M,
    )
    return M


_ENV_FLAG = "GENESIS_ENABLE_PN380_MTP_PREFUSED_LOADER"


# ─────────────────────────────────────────────────────────────────────
# Portable fixture — pristine load_weights region (pin g303916e93,
# models/qwen3_5_mtp.py lines 209-335 verbatim). Byte-identity with the
# real pin is asserted in TestAnchorsAgainstPristinePin.
# ─────────────────────────────────────────────────────────────────────

LOAD_WEIGHTS_REGION = """\
        params_dict = dict(self.named_parameters())
        loaded_params: set[str] = set()
        is_fused_expert = False
        base_layer = (
            "base_layer." if any(".base_layer." in name for name in params_dict) else ""
        )
        fused_expert_params_mapping = [
            (f"experts.{base_layer}w13_weight", "experts.gate_up_proj", 0, "w1"),
            (f"experts.{base_layer}w2_weight", "experts.down_proj", 0, "w2"),
        ]
        num_experts = (
            self.config.num_experts if hasattr(self.config, "num_experts") else 0
        )
        for name, loaded_weight in weights:
            if "rotary_emb.inv_freq" in name:
                continue

            for param_name, weight_name, shard_id in stacked_params_mapping:
                if "experts.gate_up_proj" in name or "experts.down_proj" in name:
                    is_fused_expert = True
                    expert_params_mapping = fused_expert_params_mapping

                if weight_name not in name:
                    continue

                if "mlp.experts" in name:
                    continue

                name = name.replace(weight_name, param_name)
                # Skip loading extra bias for GPTQ models.
                if name.endswith(".bias") and name not in params_dict:
                    continue
                # Skip layers on other devices.
                if is_pp_missing_parameter(name, self):
                    continue
                if name not in params_dict:
                    continue
                param = params_dict[name]
                weight_loader = param.weight_loader
                weight_loader(param, loaded_weight, shard_id)
                break
            else:
                is_expert_weight = False
                for mapping in expert_params_mapping:
                    param_name, weight_name, expert_id, shard_id = mapping
                    if weight_name not in name:
                        continue
                    is_expert_weight = True
                    name_mapped = name.replace(weight_name, param_name)
                    # Skip layers on other devices.
                    if is_pp_missing_parameter(name_mapped, self):
                        continue
                    if is_fused_expert:
                        # qwen3.5 no need to transpose
                        # loaded_weight = loaded_weight.transpose(-1, -2)
                        if "experts.gate_up_proj" in name:
                            loaded_weight = loaded_weight.chunk(2, dim=-2)
                            success_w1 = self.load_fused_expert_weights(
                                name_mapped,
                                params_dict,
                                loaded_weight[0],
                                "w1",
                                num_experts,
                            )
                            success_w3 = self.load_fused_expert_weights(
                                name_mapped,
                                params_dict,
                                loaded_weight[1],
                                "w3",
                                num_experts,
                            )
                            success = success_w1 and success_w3
                        else:
                            # down_proj
                            success = self.load_fused_expert_weights(
                                name_mapped,
                                params_dict,
                                loaded_weight,
                                shard_id,
                                num_experts,
                            )
                        if success:
                            name = name_mapped
                            break
                    else:
                        # Skip loading extra bias for GPTQ models.
                        if (
                            name_mapped.endswith(".bias")
                            or name_mapped.endswith("_bias")
                        ) and name_mapped not in params_dict:
                            continue
                        param = params_dict[name_mapped]
                        weight_loader = param.weight_loader
                        success = weight_loader(
                            param,
                            loaded_weight,
                            name_mapped,
                            shard_id=shard_id,
                            expert_id=expert_id,
                            return_success=True,
                        )
                    if success:
                        name = name_mapped
                        break
                else:
                    if is_expert_weight:
                        # We've checked that this is an expert weight
                        # However it's not mapped locally to this rank
                        # So we simply skip it
                        continue
                    # Skip loading extra bias for GPTQ models.
                    if name.endswith(".bias") and name not in params_dict:
                        continue
                    if is_pp_missing_parameter(name, self):
                        continue
                    if name not in params_dict:
                        logger.warning_once(
                            f"Parameter {name} not found in params_dict, skip loading"
                        )
                        continue
                    param = params_dict[name]
                    weight_loader = getattr(
                        param, "weight_loader", default_weight_loader
                    )
                    weight_loader(param, loaded_weight)
            loaded_params.add(name)
        return loaded_params
\
"""


# ─────────────────────────────────────────────────────────────────────
# dev491 portable fixture — pristine load_weights region (CANDIDATE pin
# g1033ffac2, 0.22.1rc1.dev491, models/qwen3_5_mtp.py verbatim). Differs
# from the dev259 region ONLY in the mapping construction (loop build vs
# static list); the rest of the load_weights body is byte-identical.
# Byte-identity with the real dev491 pin is asserted in
# TestAnchorsAgainstDev491Pin.
# ─────────────────────────────────────────────────────────────────────

LOAD_WEIGHTS_REGION_DEV491 = """\
        params_dict = dict(self.named_parameters())
        loaded_params: set[str] = set()
        is_fused_expert = False
        fused_expert_params_mapping: list[tuple[str, str, int, str]] = []
        for param_name, ckpt_name, _, shard_id in fused_moe_make_expert_params_mapping(
            self,
            ckpt_gate_proj_name="gate_up_proj",
            ckpt_down_proj_name="down_proj",
            ckpt_up_proj_name="gate_up_proj",
            num_experts=1,
        ):
            if shard_id == "w3":
                continue
            parts = ckpt_name.split(".")
            fused_expert_params_mapping.append(
                (f"{param_name}weight", f"{parts[0]}.{parts[2]}", 0, shard_id)
            )
        num_experts = (
            self.config.num_experts if hasattr(self.config, "num_experts") else 0
        )
        for name, loaded_weight in weights:
            if "rotary_emb.inv_freq" in name:
                continue

            for param_name, weight_name, shard_id in stacked_params_mapping:
                if "experts.gate_up_proj" in name or "experts.down_proj" in name:
                    is_fused_expert = True
                    expert_params_mapping = fused_expert_params_mapping

                if weight_name not in name:
                    continue

                if "mlp.experts" in name:
                    continue

                name = name.replace(weight_name, param_name)
                # Skip loading extra bias for GPTQ models.
                if name.endswith(".bias") and name not in params_dict:
                    continue
                # Skip layers on other devices.
                if is_pp_missing_parameter(name, self):
                    continue
                if name not in params_dict:
                    continue
                param = params_dict[name]
                weight_loader = param.weight_loader
                weight_loader(param, loaded_weight, shard_id)
                break
            else:
                is_expert_weight = False
                for mapping in expert_params_mapping:
                    param_name, weight_name, expert_id, shard_id = mapping
                    if weight_name not in name:
                        continue
                    is_expert_weight = True
                    name_mapped = name.replace(weight_name, param_name)
                    # Skip layers on other devices.
                    if is_pp_missing_parameter(name_mapped, self):
                        continue
                    if is_fused_expert:
                        # qwen3.5 no need to transpose
                        # loaded_weight = loaded_weight.transpose(-1, -2)
                        if "experts.gate_up_proj" in name:
                            loaded_weight = loaded_weight.chunk(2, dim=-2)
                            success_w1 = self.load_fused_expert_weights(
                                name_mapped,
                                params_dict,
                                loaded_weight[0],
                                "w1",
                                num_experts,
                            )
                            success_w3 = self.load_fused_expert_weights(
                                name_mapped,
                                params_dict,
                                loaded_weight[1],
                                "w3",
                                num_experts,
                            )
                            success = success_w1 and success_w3
                        else:
                            # down_proj
                            success = self.load_fused_expert_weights(
                                name_mapped,
                                params_dict,
                                loaded_weight,
                                shard_id,
                                num_experts,
                            )
                        if success:
                            name = name_mapped
                            break
                    else:
                        # Skip loading extra bias for GPTQ models.
                        if (
                            name_mapped.endswith(".bias")
                            or name_mapped.endswith("_bias")
                        ) and name_mapped not in params_dict:
                            continue
                        param = params_dict[name_mapped]
                        weight_loader = param.weight_loader
                        success = weight_loader(
                            param,
                            loaded_weight,
                            name_mapped,
                            shard_id=shard_id,
                            expert_id=expert_id,
                            return_success=True,
                        )
                    if success:
                        name = name_mapped
                        break
                else:
                    if is_expert_weight:
                        # We've checked that this is an expert weight
                        # However it's not mapped locally to this rank
                        # So we simply skip it
                        continue
                    # Skip loading extra bias for GPTQ models.
                    if name.endswith(".bias") and name not in params_dict:
                        continue
                    if is_pp_missing_parameter(name, self):
                        continue
                    if name not in params_dict:
                        logger.warning_once(
                            f"Parameter {name} not found in params_dict, skip loading"
                        )
                        continue
                    param = params_dict[name]
                    weight_loader = getattr(
                        param, "weight_loader", default_weight_loader
                    )
                    weight_loader(param, loaded_weight)
            loaded_params.add(name)
        return loaded_params
\
"""


def _fake_pristine_model() -> str:
    """Minimal ast-valid qwen3_5_mtp.py carrying the verbatim
    load_weights region (every PN380 anchor) under a synthetic method
    header. PN348's anchors live OUTSIDE this region by design — the
    co-apply tests therefore run on the real pin file."""
    return (
        "# fake qwen3_5_mtp.py - load_weights region (pin g303916e93)\n"
        "class Qwen3_5MultiTokenPredictor:\n"
        "    def load_fused_expert_weights(\n"
        "        self, name, params_dict, loaded_weight, shard_id, num_experts\n"
        "    ):\n"
        "        return True\n"
        "\n"
        "    def load_weights(self, weights):\n"
        "        stacked_params_mapping = [\n"
        '            ("gate_up_proj", "gate_proj", 0),\n'
        "        ]\n"
        "        expert_params_mapping = []\n"
        "        num_experts_cfg = 0\n"
        + LOAD_WEIGHTS_REGION
    )


def _fake_pristine_model_dev491() -> str:
    """Minimal ast-valid qwen3_5_mtp.py carrying the verbatim dev491
    load_weights region (mapping Variant B + the five shared anchors).
    ``fused_moe_make_expert_params_mapping`` is stubbed at module scope so
    the synthetic class is importable/ast-valid; the patcher only does
    text replacement so the stub body is irrelevant to the anchor match."""
    return (
        "# fake qwen3_5_mtp.py - load_weights region (pin g1033ffac2 dev491)\n"
        "def fused_moe_make_expert_params_mapping(*a, **k):\n"
        "    return []\n"
        "\n"
        "class Qwen3_5MultiTokenPredictor:\n"
        "    def load_fused_expert_weights(\n"
        "        self, name, params_dict, loaded_weight, shard_id, num_experts\n"
        "    ):\n"
        "        return True\n"
        "\n"
        "    def load_weights(self, weights):\n"
        "        stacked_params_mapping = [\n"
        '            ("gate_up_proj", "gate_proj", 0),\n'
        "        ]\n"
        "        expert_params_mapping = []\n"
        "        num_experts_cfg = 0\n"
        + LOAD_WEIGHTS_REGION_DEV491
    )


def _all_old_new():
    """The dev259 anchor set: mapping Variant A + the five shared anchors.
    Used by the portable fixture (dev259 static-list shape)."""
    M = _pn380()
    return [
        (M.PN380_MAPPING_OLD, M.PN380_MAPPING_NEW),
        (M.PN380_DETECT_OLD, M.PN380_DETECT_NEW),
        (M.PN380_FUSED_GUARD_OLD, M.PN380_FUSED_GUARD_NEW),
        (M.PN380_COVERAGE_INIT_OLD, M.PN380_COVERAGE_INIT_NEW),
        (M.PN380_COVERAGE_SKIP_OLD, M.PN380_COVERAGE_SKIP_NEW),
        (M.PN380_COVERAGE_REPORT_OLD, M.PN380_COVERAGE_REPORT_NEW),
    ]


def _dev491_old_new():
    """The dev491 anchor set: mapping Variant B + the five shared anchors.
    The five non-mapping anchors are byte-identical to the dev259 set."""
    M = _pn380()
    return [
        (M.PN380_MAPPING_DEV491_OLD, M.PN380_MAPPING_DEV491_NEW),
        (M.PN380_DETECT_OLD, M.PN380_DETECT_NEW),
        (M.PN380_FUSED_GUARD_OLD, M.PN380_FUSED_GUARD_NEW),
        (M.PN380_COVERAGE_INIT_OLD, M.PN380_COVERAGE_INIT_NEW),
        (M.PN380_COVERAGE_SKIP_OLD, M.PN380_COVERAGE_SKIP_NEW),
        (M.PN380_COVERAGE_REPORT_OLD, M.PN380_COVERAGE_REPORT_NEW),
    ]


def _patcher_on(tmp_path: Path, content: str, monkeypatch):
    M = _pn380()
    target = tmp_path / "qwen3_5_mtp.py"
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
    patcher = M._make_mtp_loader_patcher()
    assert patcher is not None
    return patcher, target


def _pn348_patcher(target: Path):
    """PN348's three sub-patches rebuilt from its module constants
    (PN348.apply() builds its patcher inline — no _make seam)."""
    pn348 = _pn348()
    from sndr.kernel import TextPatch, TextPatcher

    return TextPatcher(
        patch_name="pn348-co-apply-probe",
        target_file=str(target),
        marker=pn348.GENESIS_PN348_MARKER,
        sub_patches=[
            TextPatch(
                name="pn348_embed_predicate",
                anchor=pn348.PN348_EMBED_OLD,
                replacement=pn348.PN348_EMBED_NEW,
                required=True,
            ),
            TextPatch(
                name="pn348_lm_head_fallthrough",
                anchor=pn348.PN348_LMHEAD_OLD,
                replacement=pn348.PN348_LMHEAD_NEW,
                required=True,
            ),
            TextPatch(
                name="pn348_loader_skip",
                anchor=pn348.PN348_LOADER_OLD,
                replacement=pn348.PN348_LOADER_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN348",
            "share_backbone_input_output",
        ],
    )


# ─────────────────────────────────────────────────────────────────────
# 1. Anchors — unique on fixture, disjoint from PN348
# ─────────────────────────────────────────────────────────────────────


class TestAnchors:
    def test_seven_sub_patches_two_mapping_variants_optional(self):
        """Dual-anchor (pin bump dev259->dev491): the mapping sub-patch
        ships TWO mutually-exclusive variants (required=False) plus five
        shared anchors (required=True). The two mapping variants are the
        ONLY optional subs — exactly one matches per pin."""
        M = _pn380()
        subs = M.build_sub_patches()
        assert len(subs) == 7
        by_name = {sp.name: sp for sp in subs}
        # The two mapping variants are required=False (required-at-least-one).
        assert set(M._MAPPING_VARIANT_NAMES) == {
            "pn380_prefused_mapping",
            "pn380_prefused_mapping_dev491",
        }
        for vname in M._MAPPING_VARIANT_NAMES:
            assert vname in by_name
            assert by_name[vname].required is False, vname
        # Every OTHER sub-patch stays required=True.
        for sp in subs:
            if sp.name in M._MAPPING_VARIANT_NAMES:
                continue
            assert sp.required is True, sp.name

    def test_each_anchor_unique_in_fixture(self):
        fake = _fake_pristine_model()
        for old, _new in _all_old_new():
            assert fake.count(old) == 1, old[:60]
        # Variant B's dev491 loop anchor must be ABSENT from the dev259
        # static-list fixture (mutually exclusive shapes).
        M = _pn380()
        assert M.PN380_MAPPING_DEV491_OLD not in fake

    def test_each_anchor_unique_in_dev491_fixture(self):
        """Mapping Variant B + the five shared anchors are count==1 in the
        dev491 portable fixture; Variant A's static-list anchor is absent."""
        M = _pn380()
        fake491 = _fake_pristine_model_dev491()
        for old, _new in _dev491_old_new():
            assert fake491.count(old) == 1, old[:60]
        assert M.PN380_MAPPING_OLD not in fake491

    def test_replacements_do_not_resurrect_any_anchor(self):
        """Sequential-apply safety: no replacement may contain ANY
        anchor (across BOTH pin variants), or a sibling sub-patch
        double-applies. The dev491 mapping replacement re-emits its own
        loop anchor verbatim (it keeps the loop + appends an alias block),
        so it is exempt only from RE-MATCHING ITSELF — but the patcher
        replaces each anchor exactly once and the replacement carries the
        marker, so idempotency is preserved (asserted separately)."""
        pairs = _all_old_new() + [
            (
                _pn380().PN380_MAPPING_DEV491_OLD,
                _pn380().PN380_MAPPING_DEV491_NEW,
            )
        ]
        for old, new in pairs:
            for old2, _new2 in pairs:
                if old2 is old:
                    continue  # a variant's NEW re-emits its OWN anchor
                assert old2 not in new

    def test_anchors_disjoint_from_pn348(self):
        """PN348 patches the same file — its anchors must not appear in
        PN380's replacements (and vice versa), or co-apply breaks.
        Covers BOTH pin mapping variants."""
        pn348 = _pn348()
        pn348_anchors = (
            pn348.PN348_EMBED_OLD,
            pn348.PN348_LMHEAD_OLD,
            pn348.PN348_LOADER_OLD,
        )
        M = _pn380()
        pn380_new = [new for _old, new in _all_old_new()]
        pn380_new.append(M.PN380_MAPPING_DEV491_NEW)
        for new in pn380_new:
            for a348 in pn348_anchors:
                assert a348 not in new
        pn380_anchors = [old for old, _new in _all_old_new()]
        pn380_anchors.append(M.PN380_MAPPING_DEV491_OLD)
        for new348 in (
            pn348.PN348_EMBED_NEW,
            pn348.PN348_LMHEAD_NEW,
            pn348.PN348_LOADER_NEW,
        ):
            for a380 in pn380_anchors:
                assert a380 not in new348

    def test_drift_markers_absent_from_fixture(self):
        M = _pn380()
        fake = _fake_pristine_model()
        for dm in M._DRIFT_MARKERS:
            assert dm not in fake


# ─────────────────────────────────────────────────────────────────────
# 2. End-to-end TextPatcher apply
# ─────────────────────────────────────────────────────────────────────


class TestEndToEndApply:
    def test_applies_six_subs_variant_a_and_compiles(self, tmp_path, monkeypatch):
        """dev259 static-list fixture: exactly Variant A (static mapping)
        fires plus the five shared subs = 6 sub-patches; Variant B
        soft-skips."""
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _patcher_on(
            tmp_path, _fake_pristine_model(), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert len(patcher.applied_sub_patches) == 6
        # exactly Variant A fired; Variant B soft-skipped
        assert "pn380_prefused_mapping" in patcher.applied_sub_patches
        assert "pn380_prefused_mapping_dev491" not in patcher.applied_sub_patches
        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # vendor effect: pre-fused source names mapped + detected + guarded
        assert '"experts.w13_weight", 0, "w1"' in out
        assert 'or "experts.w2_weight" in name' in out
        assert "if name_mapped not in params_dict:" in out
        # Genesis extra: coverage guard present
        assert "_pn380_skipped_ckpt" in out
        assert "load-coverage gap" in out

    def test_applies_six_subs_variant_b_dev491_and_compiles(
        self, tmp_path, monkeypatch
    ):
        """dev491 loop-build fixture: exactly Variant B (loop mapping)
        fires plus the five shared subs = 6 sub-patches; Variant A
        soft-skips. The pre-fused SOURCE aliases route experts.w13_weight
        / experts.w2_weight onto the loop's target params."""
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _patcher_on(
            tmp_path, _fake_pristine_model_dev491(), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert len(patcher.applied_sub_patches) == 6
        # exactly Variant B fired; Variant A soft-skipped
        assert "pn380_prefused_mapping_dev491" in patcher.applied_sub_patches
        assert "pn380_prefused_mapping" not in patcher.applied_sub_patches
        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # vendor effect: the dev491 alias block + detection + guard
        assert "_pn380_prefused_aliases" in out
        assert '"experts.w13_weight", _pn380_eid, _pn380_sid' in out
        assert '"experts.w2_weight", _pn380_eid, _pn380_sid' in out
        assert 'or "experts.w2_weight" in name' in out
        assert "if name_mapped not in params_dict:" in out
        # Genesis extra: coverage guard present
        assert "_pn380_skipped_ckpt" in out
        assert "load-coverage gap" in out

    def test_idempotent_on_second_apply(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, _target = _patcher_on(
            tmp_path, _fake_pristine_model(), monkeypatch
        )
        result, _ = patcher.apply()
        assert result == TextPatchResult.APPLIED
        M = _pn380()
        second = M._make_mtp_loader_patcher()
        result2, _ = second.apply()
        assert result2 == TextPatchResult.IDEMPOTENT

    def test_skips_when_anchors_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, _ = _patcher_on(
            tmp_path, "def unrelated():\n    return 0\n", monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "required_anchor_missing"


# ─────────────────────────────────────────────────────────────────────
# 3. Replacement contract — faithful #44943 + coverage guard
# ─────────────────────────────────────────────────────────────────────


class TestReplacementContract:
    def test_mapping_adds_prefused_entries_with_base_layer(self):
        """Both pre-fused entries must keep the base_layer-aware TARGET
        param name (LoRA-wrapped models) while the SOURCE name is the
        bare fused checkpoint name."""
        M = _pn380()
        new = M.PN380_MAPPING_NEW
        assert (
            '(f"experts.{base_layer}w13_weight", "experts.w13_weight", 0, "w1")'
            in new
        )
        assert (
            '(f"experts.{base_layer}w2_weight", "experts.w2_weight", 0, "w2")'
            in new
        )
        # original split-form entries preserved
        assert '"experts.gate_up_proj", 0, "w1"' in new
        assert '"experts.down_proj", 0, "w2"' in new

    def test_detection_covers_all_four_source_names(self):
        M = _pn380()
        new = M.PN380_DETECT_NEW
        for frag in (
            '"experts.gate_up_proj" in name',
            '"experts.down_proj" in name',
            '"experts.w13_weight" in name',
            '"experts.w2_weight" in name',
        ):
            assert frag in new

    def test_fused_guard_resets_is_expert_weight(self):
        """#44943 params_dict guard: (quantized MTP + pre-fused ckpt)
        has w13_qweight registered, not w13_weight — skip the fused
        path AND reset is_expert_weight so the outer fallback emits the
        standard params_dict-miss warning."""
        M = _pn380()
        new = M.PN380_FUSED_GUARD_NEW
        guard_idx = new.index("if name_mapped not in params_dict:")
        reset_idx = new.index("is_expert_weight = False")
        chunk_idx = new.index('"experts.w13_weight" in name')
        assert guard_idx < reset_idx < chunk_idx
        assert "continue" in new

    def test_coverage_init_defines_state(self):
        M = _pn380()
        assert "_pn380_skipped_ckpt: list[str] = []" in M.PN380_COVERAGE_INIT_NEW

    def test_coverage_skip_records_before_warning(self):
        M = _pn380()
        new = M.PN380_COVERAGE_SKIP_NEW
        append_idx = new.index("_pn380_skipped_ckpt.append(name)")
        warn_idx = new.index("logger.warning_once(")
        assert append_idx < warn_idx
        # the upstream warning itself is preserved verbatim
        assert "not found in params_dict, skip loading" in new

    def test_coverage_report_is_single_loud_error(self):
        M = _pn380()
        new = M.PN380_COVERAGE_REPORT_NEW
        assert "logger.error(" in new
        assert "_pn380_skipped_ckpt" in new
        assert "_pn380_not_loaded" in new
        assert "vllm#44943" in new
        # quant-method-owned params are exempt (mirror upstream
        # track_weights_loading; avoids scale false positives)
        assert "quant_method" in new

    def test_marker_tracks_upstream_pr(self):
        M = _pn380()
        assert "44943" in M.GENESIS_PN380_MARKER


# ─────────────────────────────────────────────────────────────────────
# 4. Functional coverage-guard behavior (exec harness — no torch)
# ─────────────────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self):
        self.errors: list[tuple] = []

    def error(self, msg, *args):
        self.errors.append((msg, args))


class _FakeModule:
    def __init__(self, params, quant_method=None):
        self._params = params
        if quant_method is not None:
            self.quant_method = quant_method

    def named_parameters(self):
        return [(p, None) for p in self._params]


class _FakeSelf:
    def __init__(self, modules):
        self._modules = modules

    def named_modules(self):
        return list(self._modules)


def _run_coverage_report(params_dict, loaded_params, fake_self, skipped):
    """Exec the report replacement inside a synthetic method so the
    emitted code is tested as CODE, not as a string."""
    M = _pn380()
    src = (
        "class _C:\n"
        "    def run(self, params_dict, loaded_params, logger,"
        " _pn380_skipped_ckpt):\n"
        "        for name in []:\n"
        + M.PN380_COVERAGE_REPORT_NEW
    )
    ns: dict = {}
    exec(compile(src, "<pn380-coverage-harness>", "exec"), ns)
    rec = _Recorder()
    out = ns["_C"]().run.__func__(
        fake_self, params_dict, set(loaded_params), rec, list(skipped)
    )
    return rec, out


class TestCoverageGuardBehavior:
    def test_silent_on_full_coverage(self):
        rec, out = _run_coverage_report(
            params_dict={"norm.weight": None},
            loaded_params={"norm.weight"},
            fake_self=_FakeSelf([("norm", _FakeModule(["weight"]))]),
            skipped=[],
        )
        assert rec.errors == []
        assert out == {"norm.weight"}

    def test_errors_on_skipped_checkpoint_tensors(self):
        """The #44943 quantized-MTP mode: ckpt tensors hit the
        params_dict-miss fallback -> exactly one loud error."""
        rec, _ = _run_coverage_report(
            params_dict={"norm.weight": None},
            loaded_params={"norm.weight"},
            fake_self=_FakeSelf([("norm", _FakeModule(["weight"]))]),
            skipped=["layers.0.mlp.experts.w13_weight"],
        )
        assert len(rec.errors) == 1
        msg, args = rec.errors[0]
        assert "load-coverage gap" in msg
        assert 1 in args  # skipped count formatted in

    def test_errors_on_param_without_checkpoint_weight(self):
        rec, _ = _run_coverage_report(
            params_dict={"norm.weight": None, "fc.weight": None},
            loaded_params={"fc.weight"},
            fake_self=_FakeSelf(
                [("norm", _FakeModule(["weight"])), ("fc", _FakeModule(["weight"]))]
            ),
            skipped=[],
        )
        assert len(rec.errors) == 1

    def test_quant_method_owned_params_exempt(self):
        """Params under a module with quant_method may be materialized
        post-load (process_weights_after_loading / meta-device online
        quant) — they must NOT count as coverage gaps."""
        rec, _ = _run_coverage_report(
            params_dict={"experts.w13_qweight": None},
            loaded_params=set(),
            fake_self=_FakeSelf(
                [("experts", _FakeModule(["w13_qweight"], quant_method=object()))]
            ),
            skipped=[],
        )
        assert rec.errors == []


# ─────────────────────────────────────────────────────────────────────
# 5. Self-collision invariants (tools/lint_drift_markers.py contract)
# ─────────────────────────────────────────────────────────────────────


class TestSelfCollision:
    def test_drift_markers_disjoint_from_emitted_text(self):
        M = _pn380()
        marker_line = f"# [Genesis wiring marker: {M.GENESIS_PN380_MARKER}]\n"
        # Cover BOTH pin mapping variants (dev259 + dev491).
        emitted = [new for _old, new in _all_old_new()]
        emitted.append(M.PN380_MAPPING_DEV491_NEW)
        for dm in M._DRIFT_MARKERS:
            if dm.startswith("[Genesis"):
                continue  # defended convention — exempt from the lint
            for new in emitted:
                assert dm not in new, (dm, new[:80])
            assert dm not in marker_line

    def test_replacements_free_of_pn348_drift_markers(self):
        """Cross-module: if a PN380 replacement contained
        'share_backbone_input_output' (PN348's upstream drift marker),
        a later PN348 apply would Layer-3 false-skip entirely. Covers
        BOTH pin mapping variants."""
        M = _pn380()
        emitted = [new for _old, new in _all_old_new()]
        emitted.append(M.PN380_MAPPING_DEV491_NEW)
        for new in emitted:
            assert "share_backbone_input_output" not in new
            assert "[Genesis PN348" not in new

    def test_pn348_replacements_free_of_pn380_drift_markers(self):
        pn348 = _pn348()
        for new in (
            pn348.PN348_EMBED_NEW,
            pn348.PN348_LMHEAD_NEW,
            pn348.PN348_LOADER_NEW,
        ):
            assert "alt_ckpt_name" not in new


# ─────────────────────────────────────────────────────────────────────
# 6. Module apply() contract — env gate, statuses
# ─────────────────────────────────────────────────────────────────────


class TestModuleApply:
    def test_skips_when_env_unset(self, monkeypatch):
        M = _pn380()
        monkeypatch.delenv(_ENV_FLAG, raising=False)
        status, detail = M.apply()
        assert status == "skipped"
        assert _ENV_FLAG in detail

    def test_applies_when_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_ENV_FLAG, "1")
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        M = _pn380()
        target = tmp_path / "qwen3_5_mtp.py"
        target.write_text(_fake_pristine_model(), encoding="utf-8")
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
        status, detail = M.apply()
        assert status == "applied", detail
        assert "44943" in detail
        ast.parse(target.read_text(encoding="utf-8"))
        assert M.is_applied()

    def test_skips_when_target_missing(self, monkeypatch):
        monkeypatch.setenv(_ENV_FLAG, "1")
        M = _pn380()
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: None)
        status, _ = M.apply()
        assert status == "skipped"


# ─────────────────────────────────────────────────────────────────────
# 7. Against the real pristine pin (opportunistic) + PN348 co-apply
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not PIN_MODEL.is_file(),
    reason="pristine pin tree not present on this machine",
)
class TestAnchorsAgainstPristinePin:
    def test_fixture_region_matches_pin(self):
        """The embedded portable region must stay byte-identical to the
        pin so the portable tests keep testifying about the real file."""
        src = PIN_MODEL.read_text(encoding="utf-8")
        assert src.count(LOAD_WEIGHTS_REGION) == 1

    def test_each_anchor_unique_on_pin(self):
        src = PIN_MODEL.read_text(encoding="utf-8")
        for old, new in _all_old_new():
            assert src.count(old) == 1, old[:60]
            assert new not in src
        # The dev491 loop-build mapping anchor must be ABSENT on dev259
        # (mutually exclusive shapes — the dev491 variant soft-skips here).
        M = _pn380()
        assert M.PN380_MAPPING_DEV491_OLD not in src

    def test_drift_markers_absent_on_pin(self):
        M = _pn380()
        src = PIN_MODEL.read_text(encoding="utf-8")
        for dm in M._DRIFT_MARKERS:
            assert dm not in src

    def test_full_file_apply_and_compile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _patcher_on(
            tmp_path, PIN_MODEL.read_text(encoding="utf-8"), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert len(patcher.applied_sub_patches) == 6
        ast.parse(target.read_text(encoding="utf-8"))

    @pytest.mark.parametrize("order", ["pn348_first", "pn380_first"])
    def test_co_apply_with_pn348_both_orders(self, tmp_path, monkeypatch, order):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        M = _pn380()
        target = tmp_path / "qwen3_5_mtp.py"
        target.write_text(PIN_MODEL.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))

        def apply_380():
            p = M._make_mtp_loader_patcher()
            r, f = p.apply()
            assert r == TextPatchResult.APPLIED, (order, f)
            assert len(p.applied_sub_patches) == 6

        def apply_348():
            r, f = _pn348_patcher(target).apply()
            assert r == TextPatchResult.APPLIED, (order, f)

        if order == "pn348_first":
            apply_348()
            apply_380()
        else:
            apply_380()
            apply_348()

        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # both effects survive
        assert '"experts.w13_weight", 0, "w1"' in out
        assert "share_backbone_input_output" in out
        assert "[Genesis PN380" in out
        assert "[Genesis PN348" in out


# ─────────────────────────────────────────────────────────────────────
# 8. dev491 mapping Variant B — functional alias-block behavior + real
#    dev491 pin anchors + PN348 co-apply (pin bump 2026-06-13).
# ─────────────────────────────────────────────────────────────────────


def _run_dev491_alias_block(loop_mapping):
    """Exec the dev491 alias block (the lines PN380 appends after the
    upstream loop) as CODE, seeded with a given loop-built mapping, and
    return the resulting fused_expert_params_mapping. This proves the
    emitted text routes pre-fused SOURCE names onto the loop's TARGET
    params without torch / a live model."""
    M = _pn380()
    # The Variant B replacement keeps the upstream loop then appends the
    # alias block. We exec ONLY the appended alias lines against a
    # pre-seeded mapping, so slice the replacement after the loop body.
    alias_start = M.PN380_MAPPING_DEV491_NEW.index(
        "        # [Genesis PN380 vendor of vllm#44943] pre-fused checkpoints"
    )
    alias_end = M.PN380_MAPPING_DEV491_NEW.index("        num_experts = (")
    alias_block = M.PN380_MAPPING_DEV491_NEW[alias_start:alias_end]
    # The block is emitted at method-body depth (8-space indent). Dedent
    # to 4 spaces so it sits directly inside the synthetic top-level
    # ``def run`` harness.
    dedented = "".join(
        (line[4:] if line.startswith("    ") else line) + "\n"
        for line in alias_block.splitlines()
    )
    src = (
        "def run(fused_expert_params_mapping):\n"
        + dedented
        + "    return fused_expert_params_mapping\n"
    )
    ns: dict = {}
    exec(compile(src, "<pn380-dev491-alias-harness>", "exec"), ns)
    return ns["run"](list(loop_mapping))


class TestDev491AliasBlockBehavior:
    def test_alias_block_adds_prefused_sources_same_target(self):
        """The dev491 loop yields (target, source) pairs with sources
        'experts.gate_up_proj' / 'experts.down_proj'. The alias block adds
        ONE pre-fused-source entry per loop entry, preserving the loop's
        target param name (incl. the routed_experts/base_layer prefix)."""
        loop = [
            ("experts.routed_experts.w13_weight", "experts.gate_up_proj", 0, "w1"),
            ("experts.routed_experts.w2_weight", "experts.down_proj", 0, "w2"),
        ]
        out = _run_dev491_alias_block(loop)
        # originals preserved
        assert loop[0] in out and loop[1] in out
        # pre-fused source aliases onto the SAME target
        assert (
            "experts.routed_experts.w13_weight",
            "experts.w13_weight",
            0,
            "w1",
        ) in out
        assert (
            "experts.routed_experts.w2_weight",
            "experts.w2_weight",
            0,
            "w2",
        ) in out

    def test_alias_block_preserves_base_layer_target(self):
        """LoRA-wrapped models: the loop emits a base_layer-prefixed
        target — the alias must keep it byte-exact."""
        loop = [
            (
                "experts.routed_experts.base_layer.w13_weight",
                "experts.gate_up_proj",
                0,
                "w1",
            ),
            (
                "experts.routed_experts.base_layer.w2_weight",
                "experts.down_proj",
                0,
                "w2",
            ),
        ]
        out = _run_dev491_alias_block(loop)
        assert (
            "experts.routed_experts.base_layer.w13_weight",
            "experts.w13_weight",
            0,
            "w1",
        ) in out


@pytest.mark.skipif(
    not PIN_MODEL_DEV491.is_file(),
    reason="dev491 candidate pin tree not present on this machine",
)
class TestAnchorsAgainstDev491Pin:
    def test_fixture_region_matches_dev491_pin(self):
        """The embedded dev491 portable region must stay byte-identical to
        the dev491 pin so the portable tests keep testifying about the
        real candidate file."""
        src = PIN_MODEL_DEV491.read_text(encoding="utf-8")
        assert src.count(LOAD_WEIGHTS_REGION_DEV491) == 1

    def test_variant_b_anchor_unique_on_dev491_pin(self):
        """Mapping Variant B + the five shared anchors are count==1 on the
        dev491 pin; mapping Variant A (dev259 static list) is ABSENT."""
        M = _pn380()
        src = PIN_MODEL_DEV491.read_text(encoding="utf-8")
        for old, new in _dev491_old_new():
            assert src.count(old) == 1, old[:60]
            assert new not in src
        assert M.PN380_MAPPING_OLD not in src

    def test_drift_markers_absent_on_dev491_pin(self):
        M = _pn380()
        src = PIN_MODEL_DEV491.read_text(encoding="utf-8")
        for dm in M._DRIFT_MARKERS:
            assert dm not in src

    def test_full_file_apply_variant_b_and_compile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _patcher_on(
            tmp_path, PIN_MODEL_DEV491.read_text(encoding="utf-8"), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert len(patcher.applied_sub_patches) == 6
        assert "pn380_prefused_mapping_dev491" in patcher.applied_sub_patches
        assert "pn380_prefused_mapping" not in patcher.applied_sub_patches
        ast.parse(target.read_text(encoding="utf-8"))

    def test_apply_reports_dev491_variant_note(self, tmp_path, monkeypatch):
        """apply() (the module entry-point) reports the dev491 variant and
        applies cleanly on the real candidate pin."""
        monkeypatch.setenv(_ENV_FLAG, "1")
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        M = _pn380()
        target = tmp_path / "qwen3_5_mtp.py"
        target.write_text(
            PIN_MODEL_DEV491.read_text(encoding="utf-8"), encoding="utf-8"
        )
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
        status, detail = M.apply()
        assert status == "applied", detail
        assert "dev491 loop-build anchor variant" in detail
        ast.parse(target.read_text(encoding="utf-8"))

    @pytest.mark.parametrize("order", ["pn348_first", "pn380_first"])
    def test_co_apply_with_pn348_both_orders_dev491(
        self, tmp_path, monkeypatch, order
    ):
        """PN348 patches the same file with anchors that did NOT drift on
        dev491 — co-apply must still succeed in both orders, mapping
        Variant B fires, both markers survive."""
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        M = _pn380()
        target = tmp_path / "qwen3_5_mtp.py"
        target.write_text(
            PIN_MODEL_DEV491.read_text(encoding="utf-8"), encoding="utf-8"
        )
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))

        def apply_380():
            p = M._make_mtp_loader_patcher()
            r, f = p.apply()
            assert r == TextPatchResult.APPLIED, (order, f)
            assert len(p.applied_sub_patches) == 6
            assert "pn380_prefused_mapping_dev491" in p.applied_sub_patches

        def apply_348():
            r, f = _pn348_patcher(target).apply()
            assert r == TextPatchResult.APPLIED, (order, f)

        if order == "pn348_first":
            apply_348()
            apply_380()
        else:
            apply_380()
            apply_348()

        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # both effects survive on dev491
        assert "_pn380_prefused_aliases" in out
        assert "share_backbone_input_output" in out
        assert "[Genesis PN380" in out
        assert "[Genesis PN348" in out
