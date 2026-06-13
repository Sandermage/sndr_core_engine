# SPDX-License-Identifier: Apache-2.0
"""PN384 — Eagle/MTP prefix-cache prefill fix (vendor of vllm#44986).

Contract pinned here (TDD, written before the implementation):

  1. The module patches BOTH coordinator and manager files:
       - v1/core/kv_cache_coordinator.py  (4 find_longest_cache_hit sites
         + 2 drop_eagle_block decision sites)
       - v1/core/kv_cache_manager.py       (1 caller site that derives
         is_prefill_phase = num_output_tokens == 0 and threads
         skip_eagle_pop)
  2. The fix is prefill-only: skip_eagle_pop is True iff
     num_output_tokens == 0, so the lookahead/EAGLE block is dropped in
     decode (num_output_tokens > 0) exactly as before. This preserves the
     P83-flagged convergence invariant (decode path byte-unchanged).
  3. Genesis spelling divergence for drift-marker hygiene: our emitted
     skip_eagle_pop wiring spells the boolean expressions WITHOUT the
     PR's exact parenthesisation, so the PR's exact structural lines stay
     usable as merged-form drift markers without colliding with our own
     emitted text (tools/lint_drift_markers.py self-collision contract).
  4. apply() on the pin-form (g303916e93) installs the threading across
     all sites; the patched files still compile.
  5. Second apply() is idempotent (marker short-circuit → "skipped").
  6. apply() on #44986's merged form self-skips via drift markers
     (reason: upstream_merged) without touching the files.
  7. Drift markers do not collide with PN384's own replacement text or
     its Layer-6 marker line, AND at least one marker per file is an
     exact substring of the merged form.
  8. Anchors are unique (count==1) and drift markers absent in the
     pristine pin tree (opportunistic — skipped when the pin is absent).
  9. PN346 (#43650) touches the SIBLING file single_type_kv_cache_manager.py
     (MambaManager) — PN384 must NOT target that file, so the two coexist
     with zero anchor overlap.
 10. The module documents the supersession of retired P83/P84, the
     PN346 coordination, the live exposure (Qwen3.6-27B block_size=1536),
     and references the registry env flag
     GENESIS_ENABLE_PN384_EAGLE_PREFIX_CACHE_PREFILL.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Unit tests patch fresh tmp files; the Layer-0 file cache must never
# satisfy apply() from a previous run's state.
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.kv_cache import (  # noqa: E402
    pn384_eagle_prefix_cache_prefill as m,
)

# ── Fake targets ─────────────────────────────────────────────────────
# Pin-form (g303916e93): byte-faithful copies of the anchor regions in
# v1/core/kv_cache_coordinator.py and v1/core/kv_cache_manager.py.

# NOTE: The fixtures are wrapped in real classes so they compile (the
# anchors are method-level and need a class scope). The anchor BYTES
# (`def find_longest_cache_hit(...)` blocks etc.) are byte-identical to the
# pristine pin — verified by TestAnchorsAgainstPristinePin below.
PIN_COORDINATOR = (
    "# fake v1/core/kv_cache_coordinator.py (pin g303916e93 form)\n"
    "from abc import abstractmethod\n"
    "\n"
    "\n"
    "class KVCacheCoordinator:\n"
    "    @abstractmethod\n"
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        pass\n"
    "\n"
    "    def new_step_starts(self) -> None:\n"
    "        pass\n"
    "\n"
    "\n"
    "class KVCacheCoordinatorNoPrefixCache(KVCacheCoordinator):\n"
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        blocks: tuple[list[KVCacheBlock], ...] = tuple(\n"
    "            [] for _ in range(self.num_single_type_manager)\n"
    "        )\n"
    "        return blocks, 0\n"
    "\n"
    "\n"
    "class UnitaryKVCacheCoordinator(KVCacheCoordinator):\n"
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    "        hit_blocks = self.single_type_managers[0].find_longest_cache_hit(\n"
    "            block_hashes=block_hashes,\n"
    "            max_length=max_cache_hit_length,\n"
    "            kv_cache_group_ids=[0],\n"
    "            block_pool=self.block_pool,\n"
    "            kv_cache_spec=self.kv_cache_spec,\n"
    "            drop_eagle_block=0 in self.eagle_group_ids,\n"
    "            alignment_tokens=self.block_size,\n"
    "            dcp_world_size=self.dcp_world_size,\n"
    "            pcp_world_size=self.pcp_world_size,\n"
    "        )\n"
    "        return hit_blocks, len(hit_blocks[0]) * self.block_size\n"
    "\n"
    "\n"
    "class HybridKVCacheCoordinator(KVCacheCoordinator):\n"
    "    def find_longest_cache_hit(\n"
    "        self,\n"
    "        block_hashes: list[BlockHash],\n"
    "        max_cache_hit_length: int,\n"
    "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n"
    '        """\n'
    "        Find the longest cache hit using an iterative fixed-point algorithm.\n"
    "        \"\"\"\n"
    "        curr_hit_length = max_cache_hit_length\n"
    "        eagle_verified: set[int] = set()\n"
    "        while True:\n"
    "            for idx, (spec, group_ids, manager_cls, use_eagle) in enumerate(\n"
    "                self.attention_groups\n"
    "            ):\n"
    "                drop_eagle_block = use_eagle and idx not in eagle_verified\n"
    "\n"
    "                _max_length = curr_hit_length\n"
    "                if drop_eagle_block:\n"
    "                    _max_length = min(\n"
    "                        curr_hit_length + spec.block_size, max_cache_hit_length\n"
    "                    )\n"
    "                break\n"
    "            break\n"
)

PIN_MANAGER = (
    "# fake v1/core/kv_cache_manager.py (pin g303916e93 form)\n"
    "\n"
    "\n"
    "class KVCacheManager:\n"
    "    def get_computed_blocks(self, request):\n"
    "        if not self.enable_caching or request.skip_reading_prefix_cache:\n"
    "            return self.empty_kv_cache_blocks, 0\n"
    "\n"
    "        max_cache_hit_length = request.num_tokens - 1\n"
    "        computed_blocks, num_new_computed_tokens = (\n"
    "            self.coordinator.find_longest_cache_hit(\n"
    "                request.block_hashes, max_cache_hit_length\n"
    "            )\n"
    "        )\n"
    "\n"
    "        return self.create_kv_cache_blocks(computed_blocks), num_new_computed_tokens\n"
)

# #44986 merged form — what the two files look like AFTER the upstream PR
# lands. PN384 must self-skip on these. Exact text from
# `gh pr diff 44986` (2026-06-13): the PR threads skip_eagle_pop=False
# through the signatures and rewrites the two drop_eagle_block decisions
# with explicit `(not skip_eagle_pop)` parenthesisation; the manager
# derives `is_prefill_phase = request.num_output_tokens == 0`.

MERGED_COORDINATOR = (
    PIN_COORDINATOR
    # signature threading (the PR adds skip_eagle_pop to all four sigs)
    .replace(
        "        max_cache_hit_length: int,\n"
        "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n",
        "        max_cache_hit_length: int,\n"
        "        skip_eagle_pop: bool = False,\n"
        "    ) -> tuple[tuple[list[KVCacheBlock], ...], int]:\n",
    )
    # Unitary drop_eagle_block decision (PR's exact parenthesised form)
    .replace(
        "            drop_eagle_block=0 in self.eagle_group_ids,\n",
        "            drop_eagle_block=(0 in self.eagle_group_ids) and "
        "(not skip_eagle_pop),\n",
    )
    # Hybrid drop_eagle_block decision (PR's exact multi-line form)
    .replace(
        "                drop_eagle_block = use_eagle and idx not in "
        "eagle_verified\n",
        "                drop_eagle_block = (\n"
        "                    use_eagle\n"
        "                    and (idx not in eagle_verified)\n"
        "                    and (not skip_eagle_pop)\n"
        "                )\n",
    )
    .replace("(pin g303916e93 form)", "(post-vllm#44986 merged form)")
)

MERGED_MANAGER = (
    PIN_MANAGER.replace(
        "        max_cache_hit_length = request.num_tokens - 1\n"
        "        computed_blocks, num_new_computed_tokens = (\n"
        "            self.coordinator.find_longest_cache_hit(\n"
        "                request.block_hashes, max_cache_hit_length\n"
        "            )\n"
        "        )\n",
        "        max_cache_hit_length = request.num_tokens - 1\n"
        "        # Prefill phase: skip dropping last block since draft "
        "tokens are ignored.\n"
        "        is_prefill_phase = request.num_output_tokens == 0\n"
        "        computed_blocks, num_new_computed_tokens = (\n"
        "            self.coordinator.find_longest_cache_hit(\n"
        "                request.block_hashes,\n"
        "                max_cache_hit_length,\n"
        "                skip_eagle_pop=is_prefill_phase,\n"
        "            )\n"
        "        )\n",
    ).replace("(pin g303916e93 form)", "(post-vllm#44986 merged form)")
)

PIN_TREE = Path("/private/tmp/candidate_pin_current/vllm/v1/core")

# Our emitted forms (chosen to differ from the PR's exact lines so they
# never collide with our own drift markers — PN369 self-collision rule).
OUR_UNITARY_DROP = (
    "drop_eagle_block=(0 in self.eagle_group_ids) and not skip_eagle_pop,"
)
OUR_HYBRID_DROP = (
    "drop_eagle_block = (\n"
    "                    use_eagle and idx not in eagle_verified and not "
    "skip_eagle_pop\n"
    "                )"
)
OUR_MANAGER_PREFILL = "is_prefill_phase = (request.num_output_tokens == 0)"

# The PR's exact lines (used as drift markers — must NOT appear in our
# replacements).
UPSTREAM_UNITARY_DROP = (
    "drop_eagle_block=(0 in self.eagle_group_ids) and (not skip_eagle_pop),"
)
UPSTREAM_MANAGER_PREFILL = "is_prefill_phase = request.num_output_tokens == 0"


# ── Helpers ──────────────────────────────────────────────────────────


def _install_fakes(tmp_path, monkeypatch, coord_text, mgr_text):
    coord = tmp_path / "kv_cache_coordinator.py"
    mgr = tmp_path / "kv_cache_manager.py"
    coord.write_text(coord_text, encoding="utf-8")
    mgr.write_text(mgr_text, encoding="utf-8")

    def _resolve(rel):
        if rel.endswith("kv_cache_coordinator.py"):
            return str(coord)
        if rel.endswith("kv_cache_manager.py"):
            return str(mgr)
        return None

    monkeypatch.setattr(m, "resolve_vllm_file", _resolve)
    # apply() is dispatcher-gated (opt-in env flag) — force gate open.
    import sndr.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return coord, mgr


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_two_patchers_target_distinct_files(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER)
        coord_patcher = m._make_coordinator_patcher()
        mgr_patcher = m._make_manager_patcher()
        assert coord_patcher is not None
        assert mgr_patcher is not None
        assert coord_patcher.target_file.endswith("kv_cache_coordinator.py")
        assert mgr_patcher.target_file.endswith("kv_cache_manager.py")

    def test_coordinator_sub_patch_names(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER)
        coord_patcher = m._make_coordinator_patcher()
        names = {sp.name for sp in coord_patcher.sub_patches}
        # 4 signature sites + 2 decision sites.
        assert "pn384_sig_abstract" in names
        assert "pn384_sig_noprefix" in names
        assert "pn384_sig_unitary" in names
        assert "pn384_sig_hybrid" in names
        assert "pn384_unitary_drop" in names
        assert "pn384_hybrid_drop" in names

    def test_manager_single_required_sub_patch(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER)
        mgr_patcher = m._make_manager_patcher()
        by_name = {sp.name: sp for sp in mgr_patcher.sub_patches}
        assert "pn384_manager_thread" in by_name
        assert by_name["pn384_manager_thread"].required is True

    def test_spelling_diverges_from_upstream(self):
        """Drift-marker hygiene: our emitted lines drop the PR's exact
        parenthesisation so the PR's structural lines never appear in our
        own replacement text."""
        joined = "".join(
            sp.replacement
            for sp in m.coordinator_sub_patches() + m.manager_sub_patches()
        )
        assert OUR_UNITARY_DROP in joined
        assert OUR_MANAGER_PREFILL in joined
        assert UPSTREAM_UNITARY_DROP not in joined
        assert UPSTREAM_MANAGER_PREFILL not in joined

    def test_does_not_target_single_type_manager(self):
        """PN346 (#43650) owns single_type_kv_cache_manager.py — PN384
        must not touch it (zero anchor overlap, the two coexist)."""
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert m._COORDINATOR_REL == "v1/core/kv_cache_coordinator.py"
        assert m._MANAGER_REL == "v1/core/kv_cache_manager.py"
        # The module references single_type only in prose (coordination
        # note), never as a patch target.
        assert "single_type_kv_cache_manager.py" not in (
            m._COORDINATOR_REL + m._MANAGER_REL
        )
        # No TextPatcher in this module resolves the MambaManager file.
        assert 'resolve_vllm_file("v1/core/single_type_kv_cache_manager.py")' \
            not in src

    def test_patchers_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        assert m._make_coordinator_patcher() is None
        assert m._make_manager_patcher() is None

    def test_module_documents_supersession_and_coordination(self):
        doc = m.__doc__ or ""
        assert "44986" in doc
        assert "P83" in doc and "P84" in doc
        assert "PN346" in doc
        # Live exposure: Qwen3.6-27B block_size=1536.
        assert "1536" in doc

    def test_module_references_registry_env_flag(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_PN384_EAGLE_PREFIX_CACHE_PREFILL" in src


# ── Apply semantics ──────────────────────────────────────────────────


class TestApply:
    def test_apply_pin_form_threads_skip_eagle_pop(self, tmp_path, monkeypatch):
        coord, mgr = _install_fakes(
            tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER
        )
        status, reason = m.apply()
        assert status == "applied", reason

        coord_out = coord.read_text(encoding="utf-8")
        mgr_out = mgr.read_text(encoding="utf-8")

        # All four signatures gained skip_eagle_pop.
        assert coord_out.count("skip_eagle_pop: bool = False,\n") == 4
        # Both decisions thread the gate, our spelling only.
        assert OUR_UNITARY_DROP in coord_out
        assert "skip_eagle_pop" in coord_out
        assert UPSTREAM_UNITARY_DROP not in coord_out
        # Manager derives is_prefill_phase and threads skip_eagle_pop.
        assert OUR_MANAGER_PREFILL in mgr_out
        assert "skip_eagle_pop=is_prefill_phase," in mgr_out
        assert UPSTREAM_MANAGER_PREFILL not in mgr_out

        # Decode-path semantics preserved: gate is `not skip_eagle_pop`,
        # so num_output_tokens > 0 leaves drop_eagle_block behavior intact.
        assert "not skip_eagle_pop" in coord_out

        # Both files still compile after the splice.
        compile(coord_out, str(coord), "exec")
        compile(mgr_out, str(mgr), "exec")

    def test_second_apply_is_idempotent(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER)
        first_status, first_reason = m.apply()
        assert first_status == "applied", first_reason
        second_status, second_reason = m.apply()
        assert second_status == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_44986_merged_form(self, tmp_path, monkeypatch):
        coord, mgr = _install_fakes(
            tmp_path, monkeypatch, MERGED_COORDINATOR, MERGED_MANAGER
        )
        status, reason = m.apply()
        assert status == "skipped"
        assert "upstream_merged" in reason
        # Self-skip must not modify the merged files.
        assert coord.read_text(encoding="utf-8") == MERGED_COORDINATOR
        assert mgr.read_text(encoding="utf-8") == MERGED_MANAGER

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        coord, mgr = _install_fakes(
            tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER
        )
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN384_EAGLE_PREFIX_CACHE_PREFILL", raising=False
        )
        status, _reason = m.apply()
        assert status == "skipped"
        assert coord.read_text(encoding="utf-8") == PIN_COORDINATOR
        assert mgr.read_text(encoding="utf-8") == PIN_MANAGER

    def test_apply_skips_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        import sndr.dispatcher as dispatcher
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
        _install_fakes(tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER)
        for patcher in (
            m._make_coordinator_patcher(),
            m._make_manager_patcher(),
        ):
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

    def test_markers_match_44986_merged_form(self, tmp_path, monkeypatch):
        """Markers must actually fire on the real merged form (per-file)."""
        _install_fakes(tmp_path, monkeypatch, PIN_COORDINATOR, PIN_MANAGER)
        coord_patcher = m._make_coordinator_patcher()
        mgr_patcher = m._make_manager_patcher()
        assert any(
            dm in MERGED_COORDINATOR
            for dm in coord_patcher.upstream_drift_markers
        )
        assert any(
            dm in MERGED_MANAGER
            for dm in mgr_patcher.upstream_drift_markers
        )


# ── Pristine pin invariants (opportunistic) ──────────────────────────


@pytest.mark.skipif(
    not (PIN_TREE / "kv_cache_coordinator.py").is_file(),
    reason="pristine pin tree not present on this machine",
)
class TestAnchorsAgainstPristinePin:
    def test_coordinator_anchors_unique_and_markers_absent(self):
        src = (PIN_TREE / "kv_cache_coordinator.py").read_text(
            encoding="utf-8"
        )
        for sp in m.coordinator_sub_patches():
            assert src.count(sp.anchor) == 1, (
                f"coordinator anchor for {sp.name} not unique "
                f"(count={src.count(sp.anchor)})"
            )
            assert sp.replacement not in src
        coord_patcher = m._make_coordinator_patcher_from(str(PIN_TREE / "x"))
        for dm in coord_patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            assert dm not in src

    def test_manager_anchor_unique_and_markers_absent(self):
        src = (PIN_TREE / "kv_cache_manager.py").read_text(encoding="utf-8")
        for sp in m.manager_sub_patches():
            assert src.count(sp.anchor) == 1, (
                f"manager anchor for {sp.name} not unique "
                f"(count={src.count(sp.anchor)})"
            )
            assert sp.replacement not in src

    def test_fixture_anchor_regions_byte_match_pristine(self):
        """Fake pin-form fixtures must carry the EXACT anchor bytes from
        the pristine tree, so apply-tests exercise real anchors."""
        coord_src = (PIN_TREE / "kv_cache_coordinator.py").read_text(
            encoding="utf-8"
        )
        mgr_src = (PIN_TREE / "kv_cache_manager.py").read_text(
            encoding="utf-8"
        )
        for sp in m.coordinator_sub_patches():
            assert sp.anchor in PIN_COORDINATOR, (
                f"fixture missing anchor for {sp.name}"
            )
            assert sp.anchor in coord_src, (
                f"pristine pin missing anchor for {sp.name}"
            )
        for sp in m.manager_sub_patches():
            assert sp.anchor in PIN_MANAGER
            assert sp.anchor in mgr_src

    def test_pn346_sibling_file_untouched(self):
        """PN384 must not target single_type_kv_cache_manager.py (PN346's
        file). Confirm the file exists in the pin and PN384 has no anchor
        that resolves into it."""
        sibling = PIN_TREE / "single_type_kv_cache_manager.py"
        assert sibling.is_file(), "pin sibling file expected"
        sib_src = sibling.read_text(encoding="utf-8")
        # None of PN384's coordinator/manager anchors appear in PN346's file.
        for sp in m.coordinator_sub_patches() + m.manager_sub_patches():
            assert sp.anchor not in sib_src
