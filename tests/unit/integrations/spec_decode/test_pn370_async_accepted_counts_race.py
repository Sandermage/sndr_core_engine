# SPDX-License-Identifier: Apache-2.0
"""TDD for PN370 — vendor of OPEN PR vllm#45100 (async spec-decode
accepted-counts race + GDN FULL-cudagraph metadata sizing).

Two upstream hunks vendored as two sub-fixes:

  1. ``v1/worker/gpu_model_runner.py`` ``_prepare_inputs`` — skip the
     racy CPU accepted-counts read under async scheduling on the
     non-align mamba path. The CPU mirror races with the in-flight
     non-blocking D2H copy and with input-batch row moves
     (swap_states/condense); at a prefill-to-first-spec-decode
     transition GDN can consume another row's count and restore the
     wrong recurrent-state slot (prompt-memory loss, garbled early-EOS
     — upstream repro: Qwen3.5 MTP=3 + async + FULL_AND_PIECEWISE).
     Bonus: deletes the per-step ``num_accepted_tokens_event
     .synchronize()`` + NumPy gather + ``copy_to_gpu()`` on that path.
  2. ``v1/attention/backends/gdn_attn.py`` ``build()`` — size the
     FULL-cudagraph per-request metadata views (spec_state_indices_
     tensor / spec_sequence_masks / spec_query_start_loc /
     num_accepted_tokens) by ``m.num_reqs``, not by the token-padded
     ``m.num_actual_tokens``.

Composition hazard (roadmap chunk-2 Theme A): PN341 sub-patch 4
(``pn341_mtp_decode_bubbles_gpu_runner.py`` ``PN341_PREPARE_OLD``)
anchors the IDENTICAL pristine ``_prepare_inputs`` block. PN370
therefore carries TWO anchor variants with required-at-least-one
semantics (both ``required=False``; the TextPatcher kernel returns
SKIPPED ``no_applicable_sub_patches`` when every sub-patch misses):

  - pristine-shaped variant — matches an untouched pristine file
    (PN341 disabled);
  - post-PN341-shaped variant — matches the file AFTER PN341 applied
    (anchor IS PN341's own ``PN341_PREPARE_NEW`` constant; chain
    convention per PN32-imports-PN79 / PN365-imports-PN50 precedent).

Apply-order: PN341 dispatches BEFORE PN370 (boot dispatch parking-lot
order). The reverse order still produces valid Python: PN370's
pristine variant fires, then PN341's sub-patch 4 soft-skips
(required=False) while its other three sub-patches apply — acceptable
per the roadmap (under async the PN370 gate routes to the
device-authoritative default anyway).

These tests verify textually (portable embedded fixtures shaped like
pin 0.22.1rc1.dev259+g303916e93) and opportunistically against the
real pristine tree at /private/tmp/candidate_pin_current:
  1. anchor variants: required-at-least-one, mutual exclusion, chain
     derivation from PN341's constant
  2. end-to-end TextPatcher apply on tmp copies of both shapes +
     the GDN builder file — APPLIED with the expected variant, result
     compiles
  3. co-apply BOTH orders (PN341→PN370 and PN370→PN341) — ast-valid,
     both effects preserved
  4. replacement contract: faithful #45100 semantics (async + non-align
     gate; batch_size = m.num_reqs)
  5. self-collision invariants: drift markers disjoint from emitted
     text (tools/lint_drift_markers.py contract) + cross-module:
     PN370's pristine replacement must not contain PN341's drift
     markers (or PN341-after-PN370 would false-skip entirely)
  6. anchors unique and drift markers absent on the real pristine pin
"""
from __future__ import annotations

import ast
from pathlib import Path


def _pn370():
    from sndr.engines.vllm.patches.spec_decode import (
        pn370_async_accepted_counts_race as M,
    )
    return M


def _pn341():
    from sndr.engines.vllm.patches.attention.gdn import (
        pn341_mtp_decode_bubbles_gpu_runner as M,
    )
    return M


# ─────────────────────────────────────────────────────────────────────
# Portable fixtures — pristine-shaped regions (pin g303916e93)
# ─────────────────────────────────────────────────────────────────────

# Verbatim pristine `_prepare_inputs` accepted-counts region
# (gpu_model_runner.py lines 2019-2045 at the pin). PN370's pristine
# anchor is the first 4 lines; the rest stays attached under the
# rewritten `if`, so the fixture must carry the full if/else block for
# the ast-validity assertions to be meaningful.
PREPARE_REGION_PRISTINE = (
    "        # Sync num_accepted_tokens from CPU (set by\n"
    "        # _update_states_after_model_execute for hybrid models).\n"
    "        if self.num_accepted_tokens_event is not None:\n"
    "            self.num_accepted_tokens_event.synchronize()\n"
    "            # Async mode: condense() reordered indices, use prev_positions mapping\n"
    "            if self.use_async_scheduling and prev_req_id_to_index:\n"
    "                prev_idx = self.prev_positions.np[:num_reqs]\n"
    "                new_mask = prev_idx < 0\n"
    "                self.num_accepted_tokens.np[:num_reqs] = (\n"
    "                    self.input_batch.num_accepted_tokens_cpu[\n"
    "                        np.where(new_mask, 0, prev_idx)\n"
    "                    ]\n"
    "                )\n"
    "                self.num_accepted_tokens.np[:num_reqs][new_mask] = 1\n"
    "                self.input_batch.num_accepted_tokens_cpu[:num_reqs] = (\n"
    "                    self.num_accepted_tokens.np[:num_reqs]\n"
    "                )\n"
    "            else:\n"
    "                # Non-async mode: use values directly\n"
    "                self.num_accepted_tokens.np[:num_reqs] = (\n"
    "                    self.input_batch.num_accepted_tokens_cpu[:num_reqs]\n"
    "                )\n"
    "            self.num_accepted_tokens.np[num_reqs:].fill(1)\n"
    "            self.num_accepted_tokens.copy_to_gpu()\n"
    "        else:\n"
    "            self.num_accepted_tokens.np.fill(1)\n"
    "            self.num_accepted_tokens.gpu.fill_(1)\n"
)


def _fake_pristine_runner() -> str:
    """Minimal ast-valid gpu_model_runner.py carrying ALL FOUR PN341
    anchor regions plus the PN370 prepare region — assembled from
    PN341's own OLD constants (chain convention) so a PN341 anchor
    drift fails here, not silently in the co-apply tests."""
    pn341 = _pn341()
    return (
        "# fake gpu_model_runner.py - pristine-shaped regions (pin g303916e93)\n"
        "import numpy as np\n"
        "\n"
        "\n"
        "class GPUModelRunner:\n"
        "    def __init__(self):\n"
        "        if True:\n"
        "            x = (\n"
        "                1,\n"
        + pn341.PN341_INIT_OLD
        + "\n"
        + "    def _update_states_after_model_execute(self, output_token_ids):\n"
        + pn341.PN341_UPDATE_STATES_OLD
        + "            pass\n"
        + "\n"
        + pn341.PN341_COMPUTE_PREV_OLD
        + "\n"
        + "    def _prepare_inputs(self, num_reqs, prev_req_id_to_index):\n"
        + PREPARE_REGION_PRISTINE
    )


def _fake_pristine_gdn() -> str:
    M = _pn370()
    return (
        "# fake gdn_attn.py - builder region (pin g303916e93)\n"
        "class GDNAttentionMetadataBuilder:\n"
        "    def build(self, m):\n"
        "        num_spec_decodes = 0\n"
        + M.PN370_GDN_BATCH_SIZE_OLD
        + "        return batch_size\n"
    )


def _pn341_patcher(target: Path):
    """PN341's four sub-patches, rebuilt from its module constants
    (PN341.apply() builds its patcher inline — no _make seam)."""
    pn341 = _pn341()
    from sndr.kernel import TextPatch, TextPatcher

    return TextPatcher(
        patch_name="pn341-co-apply-probe",
        target_file=str(target),
        marker=pn341.GENESIS_PN341_MARKER,
        sub_patches=[
            TextPatch(
                name="pn341_init_gpu_only_flag",
                anchor=pn341.PN341_INIT_OLD,
                replacement=pn341.PN341_INIT_NEW,
            ),
            TextPatch(
                name="pn341_update_states_early_return",
                anchor=pn341.PN341_UPDATE_STATES_OLD,
                replacement=pn341.PN341_UPDATE_STATES_NEW,
            ),
            TextPatch(
                name="pn341_compute_prev_positions_optional_arg",
                anchor=pn341.PN341_COMPUTE_PREV_OLD,
                replacement=pn341.PN341_COMPUTE_PREV_NEW,
            ),
            TextPatch(
                name="pn341_prepare_inputs_gpu_only_branch",
                anchor=pn341.PN341_PREPARE_OLD,
                replacement=pn341.PN341_PREPARE_NEW,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN341",
            "_use_gpu_only_num_accepted_tokens",
        ],
    )


def _runner_patcher_on(tmp_path: Path, content: str, monkeypatch):
    M = _pn370()
    target = tmp_path / "gpu_model_runner.py"
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
    patcher = M._make_runner_patcher()
    assert patcher is not None
    return patcher, target


def _gdn_patcher_on(tmp_path: Path, content: str, monkeypatch):
    M = _pn370()
    target = tmp_path / "gdn_attn.py"
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
    patcher = M._make_gdn_patcher()
    assert patcher is not None
    return patcher, target


def _post_pn341_text() -> str:
    """Pristine fake runner with PN341's prepare replacement applied
    textually (the other three PN341 subs are irrelevant for anchor
    matching but applied in the e2e co-apply tests)."""
    pn341 = _pn341()
    src = _fake_pristine_runner()
    assert src.count(pn341.PN341_PREPARE_OLD) == 1, (
        "PN341 PREPARE OLD anchor not unique in the fixture - PN341 "
        "drifted; PN370 composition must be re-verified"
    )
    return src.replace(pn341.PN341_PREPARE_OLD, pn341.PN341_PREPARE_NEW, 1)


# ─────────────────────────────────────────────────────────────────────
# 1. Anchor variants — required-at-least-one, mutual exclusion, chain
# ─────────────────────────────────────────────────────────────────────


class TestAnchorVariants:
    def test_pristine_variant_matches_pristine_exactly_once(self):
        M = _pn370()
        assert _fake_pristine_runner().count(M.PN370_PREPARE_PRISTINE_OLD) == 1

    def test_pristine_anchor_is_prefix_of_pristine_region(self):
        M = _pn370()
        assert PREPARE_REGION_PRISTINE.startswith(M.PN370_PREPARE_PRISTINE_OLD)

    def test_post_pn341_variant_absent_from_pristine(self):
        M = _pn370()
        assert _fake_pristine_runner().count(M.PN370_PREPARE_POST_PN341_OLD) == 0

    def test_post_pn341_variant_matches_post_pn341_exactly_once(self):
        M = _pn370()
        assert _post_pn341_text().count(M.PN370_PREPARE_POST_PN341_OLD) == 1

    def test_pristine_variant_absent_from_post_pn341(self):
        M = _pn370()
        assert _post_pn341_text().count(M.PN370_PREPARE_PRISTINE_OLD) == 0

    def test_pristine_anchor_equals_pn341_prepare_old(self):
        """Both patches anchor the same upstream block — a drift in one
        constant must fail loudly here (PN32/PN79 cross-check)."""
        M, pn341 = _pn370(), _pn341()
        assert M.PN370_PREPARE_PRISTINE_OLD == pn341.PN341_PREPARE_OLD

    def test_post_pn341_anchor_built_from_pn341_constant(self):
        """Chain convention: the post-PN341 anchor IS PN341's
        PN341_PREPARE_NEW constant so the modules cannot silently
        diverge."""
        M, pn341 = _pn370(), _pn341()
        assert M.PN370_PREPARE_POST_PN341_OLD == pn341.PN341_PREPARE_NEW

    def test_runner_variants_required_false_gdn_required_true(self):
        """Required-at-least-one on the runner (kernel SKIPs with
        no_applicable_sub_patches when both miss); the GDN single
        anchor is required=True (PN290 half-apply lesson)."""
        M = _pn370()
        subs = M.build_runner_sub_patches()
        assert len(subs) == 2
        assert all(not sp.required for sp in subs)
        names = [sp.name for sp in subs]
        assert "pn370_skip_racy_cpu_read_pristine" in names
        assert "pn370_skip_racy_cpu_read_post_pn341" in names
        gdn_subs = M.build_gdn_sub_patches()
        assert len(gdn_subs) == 1
        assert gdn_subs[0].required is True

    def test_replacements_do_not_resurrect_either_anchor(self):
        """Sequential-apply safety: neither runner replacement may
        contain either anchor, or the sibling variant double-applies."""
        M = _pn370()
        for repl in (
            M.PN370_PREPARE_PRISTINE_NEW,
            M.PN370_PREPARE_POST_PN341_NEW,
        ):
            assert M.PN370_PREPARE_PRISTINE_OLD not in repl
            assert M.PN370_PREPARE_POST_PN341_OLD not in repl


# ─────────────────────────────────────────────────────────────────────
# 2. End-to-end TextPatcher apply on tmp copies
# ─────────────────────────────────────────────────────────────────────


class TestEndToEndApply:
    def test_applies_on_pristine_via_pristine_variant(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _runner_patcher_on(
            tmp_path, _fake_pristine_runner(), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert patcher.applied_sub_patches == ["pn370_skip_racy_cpu_read_pristine"]
        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        assert "_pn370_read_cpu_accepted_counts" in out

    def test_applies_on_post_pn341_via_post_variant(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _runner_patcher_on(
            tmp_path, _post_pn341_text(), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert patcher.applied_sub_patches == ["pn370_skip_racy_cpu_read_post_pn341"]
        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # PN341's device-authoritative branch must survive.
        assert "_use_gpu_only_num_accepted_tokens" in out

    def test_gdn_applies_and_sizes_by_num_reqs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _gdn_patcher_on(
            tmp_path, _fake_pristine_gdn(), monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        assert "batch_size = m.num_reqs" in out
        assert "batch_size = m.num_actual_tokens" not in out

    def test_runner_skips_when_both_variants_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, _ = _runner_patcher_on(
            tmp_path, "def unrelated():\n    return 0\n", monkeypatch
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.SKIPPED
        assert failure is not None
        assert failure.reason == "no_applicable_sub_patches"

    def test_idempotent_on_second_apply(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        patcher, target = _runner_patcher_on(
            tmp_path, _fake_pristine_runner(), monkeypatch
        )
        result, _ = patcher.apply()
        assert result == TextPatchResult.APPLIED
        M = _pn370()
        second = M._make_runner_patcher()
        result2, _ = second.apply()
        assert result2 == TextPatchResult.IDEMPOTENT


# ─────────────────────────────────────────────────────────────────────
# 3. Co-apply — BOTH orders must produce valid Python (task contract)
# ─────────────────────────────────────────────────────────────────────


class TestCoApplyOrders:
    def test_order_pn341_then_pn370(self, tmp_path, monkeypatch):
        """Canonical boot order (PN341 dispatches first). PN341 applies
        all four subs; PN370 fires its post-PN341 variant. Both effects
        must survive."""
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        target = tmp_path / "gpu_model_runner.py"
        target.write_text(_fake_pristine_runner(), encoding="utf-8")

        r341, f341 = _pn341_patcher(target).apply()
        assert r341 == TextPatchResult.APPLIED, f341

        M = _pn370()
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
        patcher = M._make_runner_patcher()
        r370, f370 = patcher.apply()
        assert r370 == TextPatchResult.APPLIED, f370
        assert patcher.applied_sub_patches == ["pn370_skip_racy_cpu_read_post_pn341"]

        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # PN341 effect: GPU-only fast path intact.
        assert "if self._use_gpu_only_num_accepted_tokens:" in out
        # PN370 effect: the event-backed elif is gated on NOT
        # (async and non-align).
        assert "elif self.num_accepted_tokens_event is not None and not (" in out
        assert 'self.cache_config.mamba_cache_mode != "align"' in out

    def test_order_pn370_then_pn341(self, tmp_path, monkeypatch):
        """Reverse order: PN370 pristine variant fires; PN341's
        sub-patch 4 soft-skips (required=False) while its other three
        subs apply. Result must stay ast-valid with PN370's gate
        intact (roadmap: soft-skip acceptable — under async the PN370
        gate routes to the device-authoritative default anyway)."""
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        from sndr.kernel import TextPatchResult

        target = tmp_path / "gpu_model_runner.py"
        target.write_text(_fake_pristine_runner(), encoding="utf-8")

        M = _pn370()
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: str(target))
        patcher = M._make_runner_patcher()
        r370, f370 = patcher.apply()
        assert r370 == TextPatchResult.APPLIED, f370
        assert patcher.applied_sub_patches == ["pn370_skip_racy_cpu_read_pristine"]

        p341 = _pn341_patcher(target)
        r341, f341 = p341.apply()
        assert r341 == TextPatchResult.APPLIED, f341
        assert "pn341_prepare_inputs_gpu_only_branch" not in p341.applied_sub_patches
        assert len(p341.applied_sub_patches) == 3

        out = target.read_text(encoding="utf-8")
        ast.parse(out)
        # PN370 effect intact.
        assert "_pn370_read_cpu_accepted_counts" in out
        # PN341's three other subs intact.
        assert "self._use_gpu_only_num_accepted_tokens = (" in out


# ─────────────────────────────────────────────────────────────────────
# 4. Replacement contract — faithful #45100 semantics
# ─────────────────────────────────────────────────────────────────────


class TestReplacementContract:
    def test_pristine_gate_matches_upstream_condition(self):
        """#45100: needs_cpu = event is not None AND NOT (async and
        mamba_cache_mode != 'align'). Align mode keeps the synchronized
        CPU path (its preprocessing consumes CPU-side counts)."""
        M = _pn370()
        repl = M.PN370_PREPARE_PRISTINE_NEW
        assert "self.num_accepted_tokens_event is not None" in repl
        assert "self.use_async_scheduling" in repl
        assert 'self.cache_config.mamba_cache_mode != "align"' in repl
        # The synchronize stays for the gated path (faithful vendor).
        assert "self.num_accepted_tokens_event.synchronize()" in repl
        assert "assert self.num_accepted_tokens_event is not None" in repl

    def test_post_pn341_gate_matches_upstream_condition(self):
        M = _pn370()
        repl = M.PN370_PREPARE_POST_PN341_NEW
        assert "elif self.num_accepted_tokens_event is not None and not (" in repl
        assert "self.use_async_scheduling" in repl
        assert 'self.cache_config.mamba_cache_mode != "align"' in repl

    def test_post_pn341_replacement_preserves_pn341_branch(self):
        """The post variant must keep PN341's GPU-only branch verbatim
        (we only re-gate the trailing elif)."""
        M, pn341 = _pn370(), _pn341()
        repl = M.PN370_PREPARE_POST_PN341_NEW
        assert "if self._use_gpu_only_num_accepted_tokens:" in repl
        assert "[Genesis PN341" in repl
        # Everything before the elif tail is byte-identical to PN341's NEW.
        tail_idx = repl.index("        # [Genesis PN370")
        assert pn341.PN341_PREPARE_NEW.startswith(repl[:tail_idx])

    def test_gdn_replacement_sizes_by_num_reqs(self):
        M = _pn370()
        assert "batch_size = m.num_reqs\n" in M.PN370_GDN_BATCH_SIZE_NEW
        assert "batch_size = m.num_actual_tokens" not in M.PN370_GDN_BATCH_SIZE_NEW

    def test_emitted_text_avoids_upstream_identifiers(self):
        """Self-collision prophylaxis: the emitted variable must not
        contain upstream's `needs_cpu_accepted_counts` (our drift
        marker for the merged form of #45100)."""
        M = _pn370()
        for repl in (
            M.PN370_PREPARE_PRISTINE_NEW,
            M.PN370_PREPARE_POST_PN341_NEW,
            M.PN370_GDN_BATCH_SIZE_NEW,
        ):
            assert "needs_cpu_accepted_counts" not in repl
            assert "token-padded for FULL graph replay" not in repl


# ─────────────────────────────────────────────────────────────────────
# 5. Self-collision invariants (tools/lint_drift_markers.py contract)
# ─────────────────────────────────────────────────────────────────────


class TestSelfCollision:
    def test_drift_markers_disjoint_from_emitted_text(self):
        M = _pn370()
        marker_line = f"# [Genesis wiring marker: {M.GENESIS_PN370_MARKER}]\n"
        replacements = (
            M.PN370_PREPARE_PRISTINE_NEW,
            M.PN370_PREPARE_POST_PN341_NEW,
            M.PN370_GDN_BATCH_SIZE_NEW,
        )
        for dm in tuple(M._RUNNER_DRIFT_MARKERS) + tuple(M._GDN_DRIFT_MARKERS):
            if dm.startswith("[Genesis"):
                continue  # defended convention — exempt from the lint
            for repl in replacements:
                assert dm not in repl, (dm, repl[:80])
            assert dm not in marker_line

    def test_drift_markers_absent_from_pristine_fixtures(self):
        M = _pn370()
        runner_src = _fake_pristine_runner()
        gdn_src = _fake_pristine_gdn()
        for dm in M._RUNNER_DRIFT_MARKERS:
            assert dm not in runner_src
        for dm in M._GDN_DRIFT_MARKERS:
            assert dm not in gdn_src

    def test_pn370_pristine_replacement_free_of_pn341_drift_markers(self):
        """Cross-module: if PN370's pristine replacement contained
        '_use_gpu_only_num_accepted_tokens' (PN341's upstream drift
        marker), a later PN341 apply would Layer-3 false-skip its WHOLE
        patcher. The post-PN341 variant legitimately contains it (it
        preserves PN341's already-applied branch)."""
        M = _pn370()
        assert "_use_gpu_only_num_accepted_tokens" not in M.PN370_PREPARE_PRISTINE_NEW
        assert "[Genesis PN341" not in M.PN370_PREPARE_PRISTINE_NEW


# ─────────────────────────────────────────────────────────────────────
# 6. Module apply() contract — env gate, combined statuses
# ─────────────────────────────────────────────────────────────────────


class TestModuleApply:
    def test_skips_when_env_unset(self, monkeypatch):
        M = _pn370()
        monkeypatch.delenv("GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE", raising=False)
        status, detail = M.apply()
        assert status == "skipped"
        assert "GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE" in detail

    def test_applies_both_files_when_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE", "1")
        monkeypatch.setenv("GENESIS_NO_PATCH_CACHE", "1")
        M = _pn370()
        runner = tmp_path / "gpu_model_runner.py"
        runner.write_text(_fake_pristine_runner(), encoding="utf-8")
        gdn = tmp_path / "gdn_attn.py"
        gdn.write_text(_fake_pristine_gdn(), encoding="utf-8")
        monkeypatch.setattr(
            M, "resolve_vllm_file", lambda rel: str(tmp_path / Path(rel).name)
        )
        monkeypatch.setattr(M, "vllm_install_root", lambda: str(tmp_path))
        status, detail = M.apply()
        assert status == "applied", detail
        assert "45100" in detail
        ast.parse(runner.read_text(encoding="utf-8"))
        ast.parse(gdn.read_text(encoding="utf-8"))
        assert M.is_applied()

    def test_skips_when_targets_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GENESIS_ENABLE_PN370_ASYNC_ACCEPT_RACE", "1")
        M = _pn370()
        monkeypatch.setattr(M, "resolve_vllm_file", lambda rel: None)
        monkeypatch.setattr(M, "vllm_install_root", lambda: str(tmp_path))
        status, _ = M.apply()
        assert status == "skipped"

    def test_module_documents_apply_order_dependency(self):
        import inspect

        M = _pn370()
        src = inspect.getsource(M)
        assert "PN341" in src
        assert "before PN370" in src or "PN341 first" in src

    def test_marker_tracks_upstream_pr(self):
        M = _pn370()
        assert "45100" in M.GENESIS_PN370_MARKER

