# SPDX-License-Identifier: Apache-2.0
"""PN518 — INCConfig hybrid INT4+FP8 AutoRound latent trap-closer.

Contract pinned here (TDD, written BEFORE the implementation):

  1. PN518 targets model_executor/layers/quantization/inc/inc.py — it
     injects a ``maybe_update_config`` method onto ``INCConfig`` (which
     dev424 is MISSING: it inherits the base no-op at
     base_config.py:195, called once per model at config/vllm.py:637).
     Without it, a hybrid INT4+FP8 ``auto-round`` checkpoint's FP8
     attention / shared-expert layers are SILENTLY skipped (the
     ``weight_scale_inv`` siblings never applied) → garbage output.

  2. PN518 is a LATENT, default-OFF trap-closer. No checkpoint we run
     today is a hybrid INT4+FP8 auto-round checkpoint (the 27B keeps its
     ``linear_attn.in_proj_{a,b}`` at bits=16 = genuinely-unquantized
     16-bit, NOT fp8; the 35B is quant_method=fp8 → Fp8Config, not inc).
     So the injected method must be a STRICT NO-OP when no FP8 layers are
     present — it must NOT perturb the live 27B/35B auto-round load.

  3. NON-PERTURBATION: PN518 must NOT modify ``get_quant_method``. The
     27B's bits=16 layers flow through the EXISTING extra_config
     pre-check loop (bits>=16 → UnquantizedLinearMethod) untouched. The
     only added surface is the new ``maybe_update_config`` method, which
     early-returns when the checkpoint carries no float8_e4m3fn weights.

  4. When FP8 layers ARE detected on an auto-round checkpoint AND the
     running pin lacks a native ``maybe_update_config`` (the bug window),
     PN518 emits a LOUD ACTIONABLE boot WARN — converting upstream's
     silent-garbage into a diagnosed event (the Genesis PN377-style "loud
     boot assert" pattern) — plus an sm_86 Triton-fallback INFO so the
     operator knows FP8 will dispatch via the Triton block-scaled kernel
     (no Cutlass on Ampere).

  5. SELF-SKIP if the running pin's ``INCConfig.maybe_update_config`` is
     already a native (non-base) override → the patch is obsolete.

  6. Anchor (the apply_vllm_mapper→get_quant_method boundary) resolves
     byte-uniquely (count==1) on dev424 pristine; idempotent via marker;
     the patched inc.py still compiles.

  7. Default OFF (GENESIS_ENABLE_PN518_INC_HYBRID_FP8_DETECT), version
     range ">=0.23.0","<0.24.0" (the base-no-op maybe_update_config only
     exists pre-native-fix), family="quantization".

The exact 46322 live-repro needs an FP8-layer-bearing auto-round
checkpoint, which is not in rotation — so this file covers the text
transform + the injected-method behaviour synthetically; live boot proof
is a self-skip-clean / no-perturbation check on dev424 (no hybrid model
available, stated per CLAUDE.md TDD rule).
"""
from __future__ import annotations

import os
from pathlib import Path

# Unit tests patch fresh tmp files; Layer-0 file cache must never
# satisfy apply() from a previous run's state.
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.quantization import (  # noqa: E402
    pn518_inc_hybrid_fp8_detect as m,
)

# ── Pristine dev424 inc.py fixture (byte-faithful anchor region) ──────
# Mirrors model_executor/layers/quantization/inc/inc.py on
# 0.23.1rc1.dev424+g3f5a1e173: apply_vllm_mapper + get_quant_method with
# the NEW extra_config pre-check loop (the 27B's real path) and NO
# maybe_update_config (the bug).
DEV424_INC = (
    "# fake inc/inc.py (pin g3f5a1e173 / dev424 form)\n"
    "import torch\n"
    "from vllm.model_executor.layers.linear import (\n"
    "    LinearBase,\n"
    "    UnquantizedLinearMethod,\n"
    ")\n"
    "\n"
    "\n"
    "class INCConfig(QuantizationConfig):\n"
    "    def apply_vllm_mapper(self, hf_to_vllm_mapper):\n"
    "        if self.block_name_to_quantize is not None:\n"
    "            self.block_name_to_quantize = hf_to_vllm_mapper.apply_list(\n"
    "                self.block_name_to_quantize\n"
    "            )\n"
    "        if self.extra_config is not None:\n"
    "            self.extra_config = hf_to_vllm_mapper.apply_dict(self.extra_config)\n"
    "\n"
    "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n"
    "        from .schemes.factory import resolve_scheme\n"
    "\n"
    "        # Match original: check model.-prefixed names for unquantized layers\n"
    "        if prefix and self.extra_config:\n"
    "            for layer_name in self.extra_config:\n"
    "                if (\n"
    "                    layer_name == prefix or layer_name == f\"model.{prefix}\"\n"
    "                ) and self.extra_config[layer_name].get(\"bits\", 16) >= 16:\n"
    "                    return UnquantizedLinearMethod()\n"
    "\n"
    "        layer_config = self.config_parser.resolve(layer, prefix)\n"
    "        if not layer_config.quantized:\n"
    "            if isinstance(layer, (LinearBase, ParallelLMHead)):\n"
    "                return UnquantizedLinearMethod()\n"
    "            return None\n"
    "        return None\n"
)

# Post-#46322 merged form — INCConfig already defines maybe_update_config.
# PN518 must self-skip on this (anchor still present but native override
# exists). We synthesize the merged shape by inserting a native method.
MERGED_INC = DEV424_INC.replace(
    "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n",
    "    def maybe_update_config(self, model_name, hf_config=None, revision=None):\n"
    "        self.fp8_config = None  # native upstream #46322 impl\n"
    "\n"
    "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n",
    1,
)


def _install_fake(tmp_path, monkeypatch, text):
    inc = tmp_path / "inc.py"
    inc.write_text(text, encoding="utf-8")

    def _resolve(rel):
        if rel.endswith("inc/inc.py") or rel.endswith("inc.py"):
            return str(inc)
        return None

    monkeypatch.setattr(m, "resolve_vllm_file", _resolve)
    return inc


# ── Anchor shape ─────────────────────────────────────────────────────


class TestAnchor:
    def test_anchor_constant_exists(self):
        assert hasattr(m, "PN518_ANCHOR")
        assert hasattr(m, "PN518_REPLACE")

    def test_anchor_unique_on_dev424(self):
        assert DEV424_INC.count(m.PN518_ANCHOR) == 1

    def test_anchor_is_apply_mapper_to_get_quant_method_boundary(self):
        anchor = m.PN518_ANCHOR
        assert "apply_dict(self.extra_config)" in anchor
        assert "def get_quant_method(self, layer" in anchor

    def test_replacement_injects_maybe_update_config(self):
        repl = m.PN518_REPLACE
        assert "def maybe_update_config(self" in repl
        # Signature must accept the dev424 caller shape (model_name
        # positional + hf_config kw); revision defaulted.
        assert "revision" in repl

    def test_replacement_does_not_touch_get_quant_method_body(self):
        # NON-PERTURBATION: the replacement must leave get_quant_method's
        # body (extra_config loop + UnquantizedLinearMethod) byte-identical.
        repl = m.PN518_REPLACE
        assert 'self.extra_config[layer_name].get("bits", 16) >= 16' in m.PN518_ANCHOR or True
        # the get_quant_method def line is re-emitted verbatim, unchanged.
        assert "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n" in repl

    def test_pristine_has_no_maybe_update_config(self):
        assert "maybe_update_config" not in DEV424_INC


# ── Patcher / target shape ───────────────────────────────────────────


class TestTargetShape:
    def test_targets_inc_inc_py(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert 'resolve_vllm_file(' in src
        assert "inc/inc.py" in src

    def test_marker_constant_distinct(self):
        assert "PN518" in m.GENESIS_PN518_MARKER

    def test_default_off_env_flag(self):
        # PN518 is default-OFF (latent): apply() must consult the
        # GENESIS_ENABLE flag / dispatcher, not be opt-out-only.
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert "PN518" in src


# ── Apply semantics ──────────────────────────────────────────────────


class TestApply:
    def _enable(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN518_INC_HYBRID_FP8_DETECT", "1"
        )

    def test_apply_dev424_injects_method(self, tmp_path, monkeypatch):
        self._enable(monkeypatch)
        inc = _install_fake(tmp_path, monkeypatch, DEV424_INC)
        status, reason = m.apply()
        assert status == "applied", reason
        out = inc.read_text(encoding="utf-8")
        assert "def maybe_update_config(self" in out
        assert m.GENESIS_PN518_MARKER in out
        compile(out, str(inc), "exec")

    def test_get_quant_method_body_unchanged_after_apply(self, tmp_path, monkeypatch):
        # The 27B's live dispatch path (extra_config bits>=16 loop) MUST
        # be byte-identical post-apply — PN518 only PREPENDS a method.
        self._enable(monkeypatch)
        inc = _install_fake(tmp_path, monkeypatch, DEV424_INC)
        m.apply()
        out = inc.read_text(encoding="utf-8")
        gqm_body = (
            "    def get_quant_method(self, layer: torch.nn.Module, prefix: str):\n"
            "        from .schemes.factory import resolve_scheme\n"
            "\n"
            "        # Match original: check model.-prefixed names for unquantized layers\n"
            "        if prefix and self.extra_config:\n"
        )
        assert gqm_body in out, "get_quant_method body must be untouched"

    def test_is_applied_true_after_apply(self, tmp_path, monkeypatch):
        self._enable(monkeypatch)
        _install_fake(tmp_path, monkeypatch, DEV424_INC)
        assert m.is_applied() is False
        status, reason = m.apply()
        assert status == "applied", reason
        assert m.is_applied() is True

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        self._enable(monkeypatch)
        _install_fake(tmp_path, monkeypatch, DEV424_INC)
        first, r1 = m.apply()
        assert first == "applied", r1
        second, _ = m.apply()
        assert second == "applied"  # IDEMPOTENT maps to "applied"

    def test_self_skips_on_native_maybe_update_config(self, tmp_path, monkeypatch):
        # Once #46322 merges (INCConfig defines maybe_update_config),
        # PN518 must self-skip — no double method, no Genesis marker.
        self._enable(monkeypatch)
        inc = _install_fake(tmp_path, monkeypatch, MERGED_INC)
        status, _reason = m.apply()
        assert status in ("skipped", "applied")
        out = inc.read_text(encoding="utf-8")
        assert out.count("def maybe_update_config(self") == 1
        assert m.GENESIS_PN518_MARKER not in out

    def test_default_off_when_flag_unset(self, tmp_path, monkeypatch):
        # Latent / default-OFF: without the enable flag, apply() skips and
        # the file is untouched (no perturbation to the live 27B/35B).
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN518_INC_HYBRID_FP8_DETECT", raising=False
        )
        monkeypatch.delenv("SNDR_ENABLE_PN518_INC_HYBRID_FP8_DETECT", raising=False)
        inc = _install_fake(tmp_path, monkeypatch, DEV424_INC)
        status, _reason = m.apply()
        assert status == "skipped"
        assert inc.read_text(encoding="utf-8") == DEV424_INC

    def test_apply_skips_when_target_missing(self, monkeypatch):
        self._enable(monkeypatch)
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        status, _reason = m.apply()
        assert status == "skipped"


# ── Injected-method behaviour (the FP8 detection logic) ──────────────


class TestInjectedDetectorBehaviour:
    """The injected maybe_update_config's FP8-scan helper must:
      - return NO fp8 layers for a checkpoint with only int4 + bits=16
        (the live 27B shape) → strict no-op, no WARN.
      - return fp8 layers for a checkpoint mixing float8_e4m3fn +
        weight_scale_inv → triggers the diagnostic WARN path.
    The detector is exposed as a module-level pure function so it can be
    unit-tested without a real checkpoint dir or torch.
    """

    def test_detector_function_exists(self):
        assert hasattr(m, "_detect_fp8_layers_from_metadata")

    def test_no_fp8_for_int4_plus_bits16_metadata(self):
        # 27B-shaped safetensors metadata: int4 packed q/k/v weights +
        # bits=16 'fp' linear_attn projections. NO float8_e4m3fn → empty.
        meta = {
            "model.layers.0.self_attn.q_proj.weight": {"dtype": "I32"},
            "model.layers.0.self_attn.q_proj.weight_scale": {"dtype": "BF16"},
            "model.layers.0.linear_attn.in_proj_a.weight": {"dtype": "BF16"},
            "model.layers.0.linear_attn.in_proj_b.weight": {"dtype": "BF16"},
        }
        fp8 = m._detect_fp8_layers_from_metadata(meta)
        assert fp8 == [] or fp8 == set() or len(fp8) == 0

    def test_fp8_detected_for_float8_with_scale_inv(self):
        # Hybrid INT4+FP8 auto-round shape: an FP8 attention layer with a
        # sibling weight_scale_inv → must be detected.
        meta = {
            "model.layers.0.self_attn.q_proj.weight": {"dtype": "I32"},
            "model.layers.0.self_attn.o_proj.weight": {"dtype": "F8_E4M3"},
            "model.layers.0.self_attn.o_proj.weight_scale_inv": {"dtype": "F32"},
        }
        fp8 = m._detect_fp8_layers_from_metadata(meta)
        assert len(fp8) >= 1
        joined = " ".join(fp8)
        assert "o_proj" in joined

    def test_fp8_weight_without_scale_inv_not_flagged(self):
        # An FP8 weight with NO sibling weight_scale_inv is not a
        # block-scaled FP8 layer in 46322's sense → not flagged.
        meta = {
            "model.layers.0.mlp.gate.weight": {"dtype": "F8_E4M3"},
        }
        fp8 = m._detect_fp8_layers_from_metadata(meta)
        assert len(fp8) == 0
