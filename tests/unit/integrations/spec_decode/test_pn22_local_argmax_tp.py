# SPDX-License-Identifier: Apache-2.0
"""CPU-only unit tests for PN22 — local argmax for TP draft (vllm#39419).

2026-06-10 extension: PN22 originally patched only qwen3.py +
qwen3_dflash.py, but the live 35B MTP drafter is Qwen3_5MTP in
qwen3_5_mtp.py (imports from qwen3_5.py, NOT qwen3.py) — the patch was a
verified dead binding for the 35B PROD stack. The extension adds a third
TextPatcher targeting qwen3_5_mtp.py with a get_top_tokens() per the
MERGED upstream implementation (LocalArgmaxMixin, merged 2026-06-10).

Covered behavior:

  * New anchor/replacement constants exist and the replacement preserves
    the anchored compute_logits() verbatim (append-only patch).
  * Replacement carries the Genesis marker comment, the
    logits_processor.get_top_tokens call, and the D2T parity guard from
    the merged LocalArgmaxMixin.
  * Patched fixture file remains valid Python (ast.parse).
  * TextPatcher round-trip on a fixture replicating the live
    qwen3_5_mtp.py shape: applies once, idempotent on re-apply.
  * Drift markers: a post-merge pin file (contains LocalArgmaxMixin)
    self-skips with reason upstream_merged.
  * Registry credit documents the qwen3_5_mtp.py extension.

No torch / CUDA dependency required.
"""
from __future__ import annotations

import ast

import pytest


def _import_patch():
    from sndr.engines.vllm.patches.spec_decode import (
        pn22_local_argmax_tp as p,
    )
    return p


# Replicates the live qwen3_5_mtp.py shape on pin
# 0.22.1rc1.dev259+g303916e93 (verified via docker exec 2026-06-10:
# anchor count=1, no get_top_tokens, no LocalArgmaxMixin).
_FIXTURE_TEMPLATE = '''\
import torch
from torch import nn


class Qwen3_5MTP(nn.Module):

    def forward(
        self,
        input_ids: torch.Tensor,
        positions: torch.Tensor,
        hidden_states: torch.Tensor,
    ):
        hidden_states = self.model(input_ids, positions, hidden_states)
        return hidden_states

    def compute_logits(
        self,
        hidden_states: torch.Tensor,
        spec_step_idx: int = 0,
    ) -> torch.Tensor | None:
        return self.logits_processor(self.lm_head, hidden_states)

    def load_weights(self, weights):
        return set()
'''


# ─── Constants shape ────────────────────────────────────────────────────


class TestConstants:
    def test_mtp_anchor_constant_exists(self):
        p = _import_patch()
        assert isinstance(p.PN22_QWEN3_5_MTP_ANCHOR, str)
        assert "def compute_logits(" in p.PN22_QWEN3_5_MTP_ANCHOR
        assert "spec_step_idx" in p.PN22_QWEN3_5_MTP_ANCHOR

    def test_replacement_preserves_anchor_verbatim(self):
        p = _import_patch()
        assert p.PN22_QWEN3_5_MTP_REPLACEMENT.startswith(
            p.PN22_QWEN3_5_MTP_ANCHOR
        )

    def test_replacement_adds_get_top_tokens(self):
        p = _import_patch()
        body = p.PN22_QWEN3_5_MTP_REPLACEMENT
        assert "def get_top_tokens(" in body
        assert "[Genesis PN22]" in body
        assert "self.logits_processor.get_top_tokens(" in body

    def test_replacement_has_d2t_parity_guard(self):
        # Merged LocalArgmaxMixin remaps via draft_id_to_target_id when
        # present; our backport must keep that parity.
        p = _import_patch()
        body = p.PN22_QWEN3_5_MTP_REPLACEMENT
        assert 'getattr(self, "draft_id_to_target_id", None)' in body
        assert "d2t[top]" in body

    def test_fixture_contains_anchor_exactly_once(self):
        p = _import_patch()
        assert _FIXTURE_TEMPLATE.count(p.PN22_QWEN3_5_MTP_ANCHOR) == 1

    def test_patched_fixture_is_valid_python(self):
        p = _import_patch()
        patched = _FIXTURE_TEMPLATE.replace(
            p.PN22_QWEN3_5_MTP_ANCHOR, p.PN22_QWEN3_5_MTP_REPLACEMENT
        )
        ast.parse(patched)  # raises SyntaxError on bad indentation


# ─── TextPatcher round-trip on fixture file ─────────────────────────────


class TestPatcherRoundTrip:
    def _build_patcher(self, target):
        p = _import_patch()
        return p.build_qwen3_5_mtp_patcher(str(target))

    def test_applies_once_then_idempotent(self, tmp_path):
        from sndr.kernel.text_patch import TextPatchResult

        target = tmp_path / "qwen3_5_mtp.py"
        target.write_text(_FIXTURE_TEMPLATE)

        r1, f1 = self._build_patcher(target).apply()
        assert r1 == TextPatchResult.APPLIED, f1
        content = target.read_text()
        assert content.count("def get_top_tokens(") == 1
        assert content.count("def compute_logits(") == 1
        ast.parse(content)

        # Second apply: marker present -> idempotent, no duplicate method.
        r2, _ = self._build_patcher(target).apply()
        assert r2 == TextPatchResult.IDEMPOTENT
        assert target.read_text().count("def get_top_tokens(") == 1

    def test_post_merge_pin_self_skips(self, tmp_path):
        from sndr.kernel.text_patch import TextPatchResult

        # Post-merge qwen3_5_mtp.py: LocalArgmaxMixin in the bases, no
        # literal get_top_tokens in the file. Patch must self-skip.
        merged = _FIXTURE_TEMPLATE.replace(
            "class Qwen3_5MTP(nn.Module):",
            "class Qwen3_5MTP(LocalArgmaxMixin, nn.Module):",
        )
        target = tmp_path / "qwen3_5_mtp.py"
        target.write_text(merged)

        r, f = self._build_patcher(target).apply()
        assert r == TextPatchResult.SKIPPED
        assert f is not None and f.reason == "upstream_merged"
        assert "def get_top_tokens(" not in target.read_text()


# ─── Registry sync ──────────────────────────────────────────────────────


class TestRegistrySync:
    def test_credit_documents_mtp_extension(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY

        credit = PATCH_REGISTRY["PN22"]["credit"]
        assert "qwen3_5_mtp" in credit
        assert "MERGED" in credit or "merged" in credit

    def test_existing_patchers_gain_mixin_drift_marker(self):
        # On a post-merge pin qwen3.py carries LocalArgmaxMixin with a
        # D2T-aware get_top_tokens; our plain method must not override it.
        import inspect

        src = inspect.getsource(_import_patch())
        assert src.count('"LocalArgmaxMixin"') >= 3
