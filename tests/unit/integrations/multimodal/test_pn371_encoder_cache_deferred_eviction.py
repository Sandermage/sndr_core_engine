# SPDX-License-Identifier: Apache-2.0
"""PN371 — deferred ref-pinned encoder-cache eviction (vendor of vllm#45199).

Upstream context: vllm PR #45199 ("[BugFix] Defer encoder cache eviction
while entries are referenced by in-flight requests", fixes #38551). The
scheduler frees encoder outputs based on speculatively-advanced progress
that can be rolled back under async scheduling + spec decode; entries can
also be shared across requests via identical mm_hash. Evicting an entry
still referenced by an in-flight request crashes the whole engine with
"Encoder cache miss" in ``_gather_mm_embeddings`` — our exact Gemma-4
vision + MTP K=3 + async-scheduling triple. #45199 was CLOSED upstream on
2026-06-11 without comments (issue #38551 still OPEN; sibling PR #39544
still open) — PN371 vendors the closed PR's approach and self-skips on
its merged form if upstream ever lands it.

Contract pinned here (TDD, written before the implementation):
  1. Three builders: encoder-cache class patcher (3 subs, all required),
     modular-runner patcher (1 sub), legacy-runner patcher (7 subs; the
     Genesis EXTEND drafter-assert demotion is required=False).
  2. apply() on pin-form (g303916e93) targets installs: ref-counted
     EncoderCache class, modular-runner eager_eviction wiring, and the
     5 legacy-runner tracker points + drafter-path assert demotion.
  3. Vendored class behavior matches #45199's own test suite (deferral,
     shared-hash, re-add revival, eager mode, update_request carry-over,
     shared external dict).
  4. Second apply() is idempotent (marker short-circuit).
  5. apply() on #45199's merged form self-skips via drift markers
     (reason: upstream_merged) and leaves all three files untouched.
  6. Drift markers do not collide with PN371's own replacement texts or
     its Layer-6 marker line (tools/lint_drift_markers.py contract).
  7. Anchors unique (count==1) and drift markers absent in the pristine
     pin tree (opportunistic — skipped when the tree is not present).
  8. apply() honors the dispatcher gate (default_on=False, env
     GENESIS_ENABLE_PN371_ENCODER_CACHE_EVICTION).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from sndr.engines.vllm.patches.multimodal import (
    pn371_encoder_cache_deferred_eviction as m,
)

# ── Fake targets (pin g303916e93 form) ───────────────────────────────
# Anchor regions are byte-exact copies from the pristine pin tree,
# embedded in minimal-but-compilable scaffolding.

PIN_ENCODER_CACHE = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    "# SPDX-FileCopyrightText: Copyright contributors to the vLLM project\n"
    "import torch\n"
    "\n"
    "from vllm.multimodal.inputs import MultiModalFeatureSpec\n"
    "\n"
    "\n"
    "class EncoderCache:\n"
    "    def __init__(self):\n"
    "        # req_id -> MM features\n"
    "        self.mm_features: dict[str, list[MultiModalFeatureSpec]] = {}\n"
    "        # MM hash -> encoder outputs\n"
    "        self.encoder_outputs: dict[str, torch.Tensor] = {}\n"
    "\n"
    "    def add_request(\n"
    "        self, req_id: str, mm_features: list[MultiModalFeatureSpec]\n"
    "    ) -> None:\n"
    "        self.mm_features[req_id] = mm_features\n"
    "\n"
    "    def remove_request(self, req_id: str) -> None:\n"
    "        self.mm_features.pop(req_id, None)\n"
    "\n"
    "    def reset_mm_cache(self) -> None:\n"
    "        \"\"\"\n"
    "        Clear the multi-modal cache that was used during profiling,\n"
    "        but no longer needed during inference.\n"
    "        \"\"\"\n"
    "        # TODO: Implement MM budget for encoder dummy run\n"
    "        pass\n"
    "\n"
    "    def reset_encoder_cache(self) -> None:\n"
    "        \"\"\"Clear the GPU-side encoder cache storing vision embeddings.\n"
    "\n"
    "        This should be called when model weights are updated to ensure\n"
    "        stale embeddings computed with old weights are not reused.\n"
    "        \"\"\"\n"
    "        self.encoder_outputs.clear()\n"
    "\n"
    "    def free_encoder_cache(self, mm_hash: str) -> None:\n"
    "        self.encoder_outputs.pop(mm_hash, None)\n"
)

PIN_MODULAR_RUNNER = (
    "# fake gpu/model_runner.py (pin g303916e93 form)\n"
    "class GPUModelRunner:\n"
    "    def __init__(self, vllm_config, device):\n"
    "        self.encoder_cache = None\n"
    "        if self.supports_mm_inputs and self.is_first_pp_rank:\n"
    "            self.encoder_cache = EncoderCache()\n"
)

PIN_LEGACY_RUNNER = (
    "# fake gpu_model_runner.py (pin g303916e93 form)\n"
    "class GPUModelRunner:\n"
    "    def __init__(self, vllm_config, device):\n"
    "        # mm_hash ->  encoder_output\n"
    "        self.encoder_cache: dict[str, torch.Tensor] = {}\n"
    "        self.late_interaction_runner = LateInteractionRunner()\n"
    "\n"
    "    def reset_encoder_cache(self) -> None:\n"
    "        self.encoder_cache.clear()\n"
    "        self.late_interaction_runner.clear()\n"
    "\n"
    "    def _update_states(self, scheduler_output):\n"
    "        for req_id in scheduler_output.finished_req_ids:\n"
    "            self.requests.pop(req_id, None)\n"
    "            self.num_prompt_logprobs.pop(req_id, None)\n"
    "        self.late_interaction_runner.on_requests_finished(\n"
    "            scheduler_output.finished_req_ids\n"
    "        )\n"
    "\n"
    "        # Free the cached encoder outputs.\n"
    "        for mm_hash in scheduler_output.free_encoder_mm_hashes:\n"
    "            self.encoder_cache.pop(mm_hash, None)\n"
    "\n"
    "        for new_req_data in scheduler_output.scheduled_new_reqs:\n"
    "            req_id = new_req_data.req_id\n"
    "            req_state = CachedRequestState(req_id=req_id)\n"
    "            self.requests[req_id] = req_state\n"
    "            self.late_interaction_runner.register_request(req_id, pooling_params)\n"
    "\n"
    "    def _update_streaming_request(self, req_id, new_req_data):\n"
    "        self.input_batch.remove_request(req_id)\n"
    "        req_state = self.requests[req_id]\n"
    "\n"
    "        req_state.prompt_token_ids = new_req_data.prompt_token_ids\n"
    "        req_state.mm_features = new_req_data.mm_features\n"
    "        req_state.prompt_embeds = new_req_data.prompt_embeds\n"
    "        return req_state\n"
    "\n"
    "    def _gather_mm_embeddings(self, scheduler_output, shift_computed_tokens=0):\n"
    "        for req_id in self.input_batch.req_ids:\n"
    "            for i in range(lo, hi):\n"
    "                mm_feature = mm_features[i]\n"
    "                mm_hash = mm_feature.identifier\n"
    "                encoder_output = self.encoder_cache.get(mm_hash, None)\n"
    "                assert encoder_output is not None, f\"Encoder cache miss for {mm_hash}.\"\n"
    "                mm_embeds_req.append(encoder_output)\n"
)

# ── #45199 merged form (what the files would look like if upstream
# ever lands the closed PR) — PN371 must self-skip on these. ─────────

MERGED_ENCODER_CACHE = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    "import torch\n"
    "\n"
    "from vllm.multimodal.inputs import MultiModalFeatureSpec\n"
    "\n"
    "\n"
    "class EncoderCache:\n"
    "    def __init__(\n"
    "        self,\n"
    "        eager_eviction: bool = False,\n"
    "        encoder_outputs: dict[str, torch.Tensor] | None = None,\n"
    "    ):\n"
    "        self.mm_features: dict[str, list[MultiModalFeatureSpec]] = {}\n"
    "        self.encoder_outputs: dict[str, torch.Tensor] = (\n"
    "            encoder_outputs if encoder_outputs is not None else {}\n"
    "        )\n"
    "        self.eager_eviction = eager_eviction\n"
    "        self._mm_hash_refs: dict[str, set[str]] = {}\n"
    "        self._pending_free: set[str] = set()\n"
)

MERGED_MODULAR_RUNNER = (
    "# fake gpu/model_runner.py (post-vllm#45199 merged form)\n"
    "class GPUModelRunner:\n"
    "    def __init__(self, vllm_config, device):\n"
    "        self.encoder_cache = None\n"
    "        if self.supports_mm_inputs and self.is_first_pp_rank:\n"
    "            self.encoder_cache = EncoderCache(\n"
    "                eager_eviction=self.model_config.is_encoder_decoder\n"
    "            )\n"
)

MERGED_LEGACY_RUNNER = (
    "# fake gpu_model_runner.py (post-vllm#45199 merged form)\n"
    "class GPUModelRunner:\n"
    "    def _update_states(self, scheduler_output):\n"
    "        for req_id in scheduler_output.finished_req_ids:\n"
    "            self.requests.pop(req_id, None)\n"
    "            self.num_prompt_logprobs.pop(req_id, None)\n"
    "            self.encoder_cache_tracker.remove_request(req_id)\n"
    "\n"
    "        # Free the cached encoder outputs. Eviction is deferred for entries\n"
    "        # still referenced by an in-flight request; see EncoderCache.\n"
    "        for mm_hash in scheduler_output.free_encoder_mm_hashes:\n"
    "            self.encoder_cache_tracker.free_encoder_cache(mm_hash)\n"
)


# ── Helpers ──────────────────────────────────────────────────────────


def _install_fakes(
    tmp_path,
    monkeypatch,
    encoder_cache_text=PIN_ENCODER_CACHE,
    modular_text=PIN_MODULAR_RUNNER,
    legacy_text=PIN_LEGACY_RUNNER,
):
    """Write fake targets and redirect resolve_vllm_file + dispatcher."""
    targets = {
        "encoder_cache.py": tmp_path / "encoder_cache.py",
        "model_runner.py": tmp_path / "model_runner.py",
        "gpu_model_runner.py": tmp_path / "gpu_model_runner.py",
    }
    targets["encoder_cache.py"].write_text(encoder_cache_text, encoding="utf-8")
    targets["model_runner.py"].write_text(modular_text, encoding="utf-8")
    targets["gpu_model_runner.py"].write_text(legacy_text, encoding="utf-8")

    def _resolve(relpath: str):
        return str(tmp_path / Path(relpath).name)

    monkeypatch.setattr(m, "resolve_vllm_file", _resolve)

    # PN371's registry entry is owned by the registry agent — force the
    # dispatcher gate open for apply-semantics tests.
    from sndr import dispatcher

    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    monkeypatch.setattr(dispatcher, "log_decision", lambda *a, **k: None)
    return targets


def _load_patched_encoder_cache_class(tmp_path, monkeypatch):
    """apply() the patch, then exec the patched encoder_cache.py with
    torch / vllm.multimodal.inputs stubbed (torch-less host)."""
    targets = _install_fakes(tmp_path, monkeypatch)
    status, reason = m.apply()
    assert status == "applied", reason

    torch_stub = types.ModuleType("torch")
    torch_stub.Tensor = type("Tensor", (), {})
    vllm_stub = types.ModuleType("vllm")
    mm_pkg = types.ModuleType("vllm.multimodal")
    mm_inputs = types.ModuleType("vllm.multimodal.inputs")
    mm_inputs.MultiModalFeatureSpec = type("MultiModalFeatureSpec", (), {})
    monkeypatch.setitem(sys.modules, "torch", torch_stub)
    monkeypatch.setitem(sys.modules, "vllm", vllm_stub)
    monkeypatch.setitem(sys.modules, "vllm.multimodal", mm_pkg)
    monkeypatch.setitem(sys.modules, "vllm.multimodal.inputs", mm_inputs)

    src = targets["encoder_cache.py"].read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(src, "encoder_cache_patched.py", "exec"), ns)
    return ns["EncoderCache"]


class _Feat:
    """Minimal stand-in for MultiModalFeatureSpec (only .identifier used)."""

    def __init__(self, identifier: str):
        self.identifier = identifier


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_three_builders_exist(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch)
        assert m._make_encoder_cache_patcher() is not None
        assert m._make_modular_runner_patcher() is not None
        assert m._make_legacy_runner_patcher() is not None

    def test_encoder_cache_patcher_subs_all_required(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch)
        patcher = m._make_encoder_cache_patcher()
        assert len(patcher.sub_patches) == 3
        assert all(sp.required for sp in patcher.sub_patches)

    def test_legacy_patcher_has_seven_subs_extend_optional(
        self, tmp_path, monkeypatch
    ):
        _install_fakes(tmp_path, monkeypatch)
        patcher = m._make_legacy_runner_patcher()
        assert len(patcher.sub_patches) == 7
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        # The Genesis EXTEND (drafter assert demotion) must never abort
        # the core tracker wiring if its anchor drifts.
        assert by_name["pn371_drafter_cache_miss_demotion"].required is False
        core = [
            sp for sp in patcher.sub_patches
            if sp.name != "pn371_drafter_cache_miss_demotion"
        ]
        assert all(sp.required for sp in core)

    def test_patchers_none_when_targets_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        assert m._make_encoder_cache_patcher() is None
        assert m._make_modular_runner_patcher() is None
        assert m._make_legacy_runner_patcher() is None

    def test_drift_markers_match_45199_merged_form(self, tmp_path, monkeypatch):
        """Self-skip probe contract: markers must be exact substrings of
        the #45199 merged-form fixtures (eager_eviction signature et al)."""
        _install_fakes(tmp_path, monkeypatch)
        ec = m._make_encoder_cache_patcher()
        modular = m._make_modular_runner_patcher()
        legacy = m._make_legacy_runner_patcher()
        assert any(
            dm in MERGED_ENCODER_CACHE for dm in ec.upstream_drift_markers
        )
        assert any(
            dm in MERGED_MODULAR_RUNNER for dm in modular.upstream_drift_markers
        )
        assert any(
            dm in MERGED_LEGACY_RUNNER for dm in legacy.upstream_drift_markers
        )

    def test_module_tracks_pr_45199_and_closure(self):
        doc = m.__doc__ or ""
        assert "45199" in doc
        assert "45199" in m.GENESIS_PN371_MARKER
        # The PR was CLOSED unmerged on 2026-06-11 — the module must
        # record that so the next sweep re-checks upstream state.
        assert "38551" in doc


# ── Vendored class behavior (parity with #45199's own test suite) ────


class TestVendoredClassBehavior:
    @pytest.fixture
    def cache_cls(self, tmp_path, monkeypatch):
        return _load_patched_encoder_cache_class(tmp_path, monkeypatch)

    def test_free_unreferenced_entry_is_eager(self, cache_cls):
        cache = cache_cls()
        cache.encoder_outputs["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        assert "hash_a" not in cache.encoder_outputs

    def test_free_referenced_entry_deferred_until_request_removed(
        self, cache_cls
    ):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_a")])
        cache.encoder_outputs["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        assert "hash_a" in cache.encoder_outputs
        cache.remove_request("req_a")
        assert "hash_a" not in cache.encoder_outputs

    def test_shared_hash_survives_first_request_completion(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_shared")])
        cache.add_request("req_b", [_Feat("hash_shared")])
        cache.encoder_outputs["hash_shared"] = object()
        cache.free_encoder_cache("hash_shared")
        cache.remove_request("req_a")
        assert "hash_shared" in cache.encoder_outputs
        cache.remove_request("req_b")
        assert "hash_shared" not in cache.encoder_outputs

    def test_readd_cancels_pending_eviction(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_a")])
        cache.encoder_outputs["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        cache.add_request("req_b", [_Feat("hash_a")])
        cache.remove_request("req_a")
        assert "hash_a" in cache.encoder_outputs
        cache.free_encoder_cache("hash_a")
        assert "hash_a" in cache.encoder_outputs
        cache.remove_request("req_b")
        assert "hash_a" not in cache.encoder_outputs

    def test_remove_without_pending_free_keeps_entry(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_a")])
        cache.encoder_outputs["hash_a"] = object()
        cache.remove_request("req_a")
        assert "hash_a" in cache.encoder_outputs
        cache.free_encoder_cache("hash_a")
        assert "hash_a" not in cache.encoder_outputs

    def test_eager_eviction_mode_for_encoder_decoder(self, cache_cls):
        cache = cache_cls(eager_eviction=True)
        cache.add_request("req_a", [_Feat("hash_a")])
        cache.encoder_outputs["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        assert "hash_a" not in cache.encoder_outputs

    def test_update_request_keeps_refs_for_overlapping_hashes(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_a"), _Feat("hash_b")])
        cache.encoder_outputs["hash_a"] = object()
        cache.encoder_outputs["hash_b"] = object()
        cache.free_encoder_cache("hash_b")
        cache.update_request("req_a", [_Feat("hash_a"), _Feat("hash_c")])
        assert "hash_b" not in cache.encoder_outputs
        cache.free_encoder_cache("hash_a")
        assert "hash_a" in cache.encoder_outputs
        cache.remove_request("req_a")
        assert "hash_a" not in cache.encoder_outputs

    def test_duplicate_features_in_one_request(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_a"), _Feat("hash_a")])
        cache.encoder_outputs["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        assert "hash_a" in cache.encoder_outputs
        cache.remove_request("req_a")
        assert "hash_a" not in cache.encoder_outputs

    def test_none_and_empty_mm_features_are_noops(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_text", [])
        cache.add_request("req_none", None)
        cache.remove_request("req_text")
        cache.remove_request("req_none")
        cache.remove_request("req_never_added")

    def test_reset_encoder_cache_clears_outputs_and_pending(self, cache_cls):
        cache = cache_cls()
        cache.add_request("req_a", [_Feat("hash_a")])
        cache.encoder_outputs["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        cache.reset_encoder_cache()
        assert not cache.encoder_outputs
        cache.remove_request("req_a")
        assert not cache.encoder_outputs

    def test_shared_external_dict_observes_evictions(self, cache_cls):
        external: dict = {}
        cache = cache_cls(encoder_outputs=external)
        cache.add_request("req_a", [_Feat("hash_a")])
        external["hash_a"] = object()
        cache.free_encoder_cache("hash_a")
        assert "hash_a" in external
        cache.remove_request("req_a")
        assert "hash_a" not in external


# ── Apply semantics ──────────────────────────────────────────────────


class TestApply:
    def test_apply_pin_form_installs_all_wiring(self, tmp_path, monkeypatch):
        targets = _install_fakes(tmp_path, monkeypatch)
        status, reason = m.apply()
        assert status == "applied", reason

        ec_out = targets["encoder_cache.py"].read_text(encoding="utf-8")
        modular_out = targets["model_runner.py"].read_text(encoding="utf-8")
        legacy_out = targets["gpu_model_runner.py"].read_text(encoding="utf-8")

        # Class gained deferral machinery.
        assert "eager_eviction" in ec_out
        assert "_pending_free" in ec_out
        assert "def update_request(" in ec_out
        # Modular runner passes eager_eviction for encoder-decoder models.
        assert "is_encoder_decoder" in modular_out
        # Legacy runner: tracker created sharing the dict, all 5 points
        # routed through it, raw pop gone.
        assert "_g_pn371_ec_tracker" in legacy_out
        assert "encoder_outputs=self.encoder_cache" in legacy_out
        assert "self._g_pn371_ec_tracker.free_encoder_cache(mm_hash)" in legacy_out
        assert "self.encoder_cache.pop(mm_hash, None)" not in legacy_out
        assert "self._g_pn371_ec_tracker.remove_request(req_id)" in legacy_out
        assert "self._g_pn371_ec_tracker.add_request(" in legacy_out
        assert "self._g_pn371_ec_tracker.update_request(" in legacy_out
        # EXTEND: drafter-path demotion present, verifier assert retained.
        assert "shift_computed_tokens != 0" in legacy_out
        assert (
            'assert encoder_output is not None, f"Encoder cache miss for {mm_hash}."'
            in legacy_out
        )
        # All three files still compile after the splice.
        compile(ec_out, "encoder_cache.py", "exec")
        compile(modular_out, "model_runner.py", "exec")
        compile(legacy_out, "gpu_model_runner.py", "exec")

    def test_second_apply_is_idempotent(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch)
        first_status, _ = m.apply()
        assert first_status == "applied"
        second_status, second_reason = m.apply()
        assert second_status == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_45199_merged_form(self, tmp_path, monkeypatch):
        targets = _install_fakes(
            tmp_path,
            monkeypatch,
            encoder_cache_text=MERGED_ENCODER_CACHE,
            modular_text=MERGED_MODULAR_RUNNER,
            legacy_text=MERGED_LEGACY_RUNNER,
        )
        status, reason = m.apply()
        assert status == "skipped"
        assert "upstream_merged" in reason
        # Self-skip must not modify the merged files.
        assert (
            targets["encoder_cache.py"].read_text(encoding="utf-8")
            == MERGED_ENCODER_CACHE
        )
        assert (
            targets["model_runner.py"].read_text(encoding="utf-8")
            == MERGED_MODULAR_RUNNER
        )
        assert (
            targets["gpu_model_runner.py"].read_text(encoding="utf-8")
            == MERGED_LEGACY_RUNNER
        )

    def test_runner_wiring_withheld_when_class_patch_skips(
        self, tmp_path, monkeypatch
    ):
        """If the EncoderCache class patch cannot land (anchor drift),
        the runner wiring must NOT land either — the pristine class
        would TypeError on the tracker kwargs at runner init."""
        targets = _install_fakes(
            tmp_path,
            monkeypatch,
            encoder_cache_text="# drifted encoder_cache.py — no anchors\n",
        )
        status, reason = m.apply()
        assert status == "skipped"
        legacy_out = targets["gpu_model_runner.py"].read_text(encoding="utf-8")
        assert "_g_pn371_ec_tracker" not in legacy_out

    def test_apply_respects_dispatcher_gate(self, tmp_path, monkeypatch):
        targets = _install_fakes(tmp_path, monkeypatch)
        from sndr import dispatcher

        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        status, reason = m.apply()
        assert status == "skipped"
        assert "opt-in" in reason
        # Nothing written.
        assert (
            targets["encoder_cache.py"].read_text(encoding="utf-8")
            == PIN_ENCODER_CACHE
        )


# ── Lint contract (tools/lint_drift_markers.py) ──────────────────────


class TestDriftMarkerSelfCollision:
    def test_markers_not_substring_of_own_replacements(
        self, tmp_path, monkeypatch
    ):
        _install_fakes(tmp_path, monkeypatch)
        patchers = [
            m._make_encoder_cache_patcher(),
            m._make_modular_runner_patcher(),
            m._make_legacy_runner_patcher(),
        ]
        for patcher in patchers:
            marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
            for dm in patcher.upstream_drift_markers:
                for sp in patcher.sub_patches:
                    assert dm not in sp.replacement, (
                        f"drift marker {dm!r} collides with {sp.name} "
                        f"replacement — would false-fire Layer 3"
                    )
                assert dm not in marker_line


# ── Pristine pin invariants: RETIRED (audit #14 full drain, 2026-07-06) ──
# The former ``TestAnchorsAgainstPristinePin`` byte-checked anchors against
# absent on the Linux rig (pristine at ``/tmp/pristine_dev748_2dfaae752``):
# executed on NO host, a permanent green-by-skip. PN371 is NOT recorded in
# the committed anchor_sot manifest (90/329 coverage gap, audit #6/#21), so
# the byte-check cannot be migrated onto the manifest. Retired; anchor +
# idempotency + self-collision + fixture-driven apply contracts stay covered
# in CI by the synthetic TestPatcherShape / TestVendoredClassBehavior /
# TestApply / TestDriftMarkerSelfCollision classes above.
