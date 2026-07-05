# SPDX-License-Identifier: Apache-2.0
"""PN526 — thread-safe StructuredOutputManager tokenizer (vllm#47509).

Contract pinned here (TDD, written before the implementation).

Upstream bug (vllm#47509): ``StructuredOutputManager.__init__`` (pristine
dev748 L79-81, byte-verified) stores the PROCESS-GLOBAL
``cached_tokenizer_from_config`` instance and hands it to concurrent
``self.executor`` threads (grammar compilation) plus the request-scoped
reasoner. HF fast tokenizers mutate shared Rust state inside ``encode``
(``set_truncation_and_padding``), so concurrent calls raise
``RuntimeError: Already borrowed``. Latent-but-real on our 35B PROD:
reasoning_parser qwen3 + GENESIS_ENABLE_P62_STRUCT_OUT_SPEC_TIMING=1 +
structured outputs live (never observed in incident memory -> P3,
opt-in flag).

Fix deps are IN-pin (vllm/tokenizers/hf.py: ThreadSafeHFTokenizerMixin
L19 + maybe_make_thread_pool L25; re-exported by vllm/tokenizers
__init__ — all byte-verified at 2dfaae752). PN526 vendors the PR's
__init__ hunk with upstream-identical semantics (copy.copy before the
in-place pool wrap; ``max_workers + 1`` pool size) as a single
function-local insertion, importing under Genesis aliases so upstream's
literal import line ``cached_tokenizer_from_config,
maybe_make_thread_pool`` stays a SELF_COLLISION-safe drift marker.

Sub-contracts:
  1. One required sub-patch anchored on the unique
     ``self.tokenizer = cached_tokenizer_from_config(`` span in
     __init__ (count==1 byte-verified in pristine dev748).
  2. The patched slice, executed as real Python, wraps a COPY: the
     shared cache entry is never mutated (upstream's
     test_manager_does_not_mutate_shared_cache semantics) and the pool
     is built with max_workers + 1 (grammar threads + reasoner).
  3. Idempotent second apply; drift-marker self-skip on the merged
     form; gate-closed no-op; patched file compiles.
  4. Same-file hygiene: P62 (grammar_bitmask/should_advance regions)
     AND PN58 Sub-D (module-level 'logger = init_logger' anchor before
     the class) are disjoint — PN58 was MISSED in the first triage pass
     (verdict correction from the cross-check); both pinned here.
  5. Opt-in: default_on=False. Expected retire outcome (a)
     byte-similar when #47509 merges.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.reasoning import (  # noqa: E402
    pn58_spec_reasoning_boundary as pn58,
)
from sndr.engines.vllm.patches.serving import (  # noqa: E402
    pn526_threadsafe_so_tokenizer as overlay,
)

# ── Fixture: pin-form anchor region (byte-faithful, dev748 2dfaae752) ─

PIN_STRUCT_OUT = (
    "# fake v1/structured_output/__init__.py (pin 2dfaae752 form)\n"
    "from vllm.tokenizers import cached_tokenizer_from_config\n"
    "\n"
    "logger = init_logger(__name__)\n"
    "\n"
    "\n"
    "class StructuredOutputManager:\n"
    "    def __init__(self, vllm_config):\n"
    "        self.vllm_config = vllm_config\n"
    "        if not self.vllm_config.model_config.skip_tokenizer_init:\n"
    "            max_workers = max(1, (multiprocessing.cpu_count() + 1) // 2)\n"
    "            self.executor = ThreadPoolExecutor(max_workers=max_workers)\n"
    "            self.tokenizer = cached_tokenizer_from_config(\n"
    "                model_config=self.vllm_config.model_config\n"
    "            )\n"
    "            reasoning_parser_plugin = (\n"
    "                self.vllm_config.structured_outputs_config.reasoning_parser_plugin\n"
    "            )\n"
)

# #47509 merged form (exact hunk from `gh pr diff 47509`, 2026-07-05,
# abbreviated to the load-bearing lines incl. the rewritten import).
MERGED_STRUCT_OUT = PIN_STRUCT_OUT.replace(
    "from vllm.tokenizers import cached_tokenizer_from_config\n",
    "from vllm.tokenizers import cached_tokenizer_from_config, maybe_make_thread_pool\n",
).replace(
    "            self.tokenizer = cached_tokenizer_from_config(\n"
    "                model_config=self.vllm_config.model_config\n"
    "            )\n",
    "            self.tokenizer = cached_tokenizer_from_config(\n"
    "                model_config=self.vllm_config.model_config\n"
    "            )\n"
    "            assert self.tokenizer is not None\n"
    "            self.tokenizer = copy.copy(self.tokenizer)\n"
    "            maybe_make_thread_pool(self.tokenizer, max_workers + 1)\n",
).replace("(pin 2dfaae752 form)", "(post-vllm#47509 merged form)")


def _install(tmp_path, monkeypatch, text):
    target = tmp_path / "__init__.py"
    target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
    monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
    from sndr import dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


class TestPatcherShape:
    def test_single_required_subpatch(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_STRUCT_OUT)
        patcher = overlay._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert set(by_name) == {"pn526_tokenizer_copy_thread_pool"}
        assert by_name["pn526_tokenizer_copy_thread_pool"].required is True

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: None)
        assert overlay._make_patcher() is None


class TestApply:
    def test_apply_inserts_copy_and_pool(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_STRUCT_OUT)
        status, reason = overlay.apply()
        assert status == "applied", reason
        out = target.read_text(encoding="utf-8")
        # Upstream-identical semantics: copy before in-place wrap,
        # pool sized max_workers + 1.
        assert ".copy(self.tokenizer)" in out
        assert "(self.tokenizer, max_workers + 1)" in out
        # Aliased imports: upstream's literal combined import line must
        # NOT appear (it is the drift marker).
        assert (
            "cached_tokenizer_from_config, maybe_make_thread_pool" not in out
        )
        compile(out, str(target), "exec")

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_STRUCT_OUT)
        first, first_reason = overlay.apply()
        assert first == "applied", first_reason
        second, second_reason = overlay.apply()
        assert second == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_merged_form(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, MERGED_STRUCT_OUT)
        status, reason = overlay.apply()
        assert status == "skipped"
        assert "upstream" in reason.lower()
        assert target.read_text(encoding="utf-8") == MERGED_STRUCT_OUT

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        target = tmp_path / "__init__.py"
        target.write_text(PIN_STRUCT_OUT, encoding="utf-8")
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
        monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
        from sndr import dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "gate closed")
        )
        status, _reason = overlay.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_STRUCT_OUT


class TestPortedUpstreamSemantics:
    """Executable port of the PR's cache-isolation contract
    (test_manager_does_not_mutate_shared_cache): the manager must wrap a
    COPY, never the shared process-global instance, and size the pool
    max_workers + 1. (The full transformers concurrency hammer runs in
    the blue/green container gate, not here.)"""

    def _run_patched_init_slice(self, patched: str):
        """Extract and exec the patched tokenizer-init slice with stubbed
        vllm modules; returns (shared, manager_tokenizer, pool_calls)."""
        import sys
        import types

        start = patched.index("            self.tokenizer = cached_tokenizer_from_config(")
        end = patched.index("            reasoning_parser_plugin", start)
        slice_src = "\n".join(
            ln[12:] for ln in patched[start:end].splitlines()
        ) + "\n"

        class _Tok:
            pass

        shared = _Tok()
        pool_calls = []

        fake_tokenizers = types.ModuleType("vllm.tokenizers")
        fake_tokenizers.cached_tokenizer_from_config = lambda **kw: shared
        fake_tokenizers.maybe_make_thread_pool = (
            lambda tok, copies=1: pool_calls.append((tok, copies))
        )
        fake_vllm = types.ModuleType("vllm")
        fake_vllm.tokenizers = fake_tokenizers

        class _Self:
            pass

        self_obj = _Self()
        self_obj.vllm_config = types.SimpleNamespace(
            model_config=types.SimpleNamespace(skip_tokenizer_init=False)
        )
        saved = {k: sys.modules.get(k) for k in ("vllm", "vllm.tokenizers")}
        sys.modules["vllm"] = fake_vllm
        sys.modules["vllm.tokenizers"] = fake_tokenizers
        try:
            exec(  # noqa: S102 - test-only execution of the patched slice
                compile(slice_src, "<pn526-patched-slice>", "exec"),
                {
                    "self": self_obj,
                    "cached_tokenizer_from_config": (
                        fake_tokenizers.cached_tokenizer_from_config
                    ),
                    "max_workers": 4,
                },
            )
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        return shared, self_obj.tokenizer, pool_calls

    @pytest.fixture
    def patched(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_STRUCT_OUT)
        status, reason = overlay.apply()
        assert status == "applied", reason
        return target.read_text(encoding="utf-8")

    def test_manager_wraps_a_copy_not_the_shared_cache(self, patched):
        shared, manager_tok, pool_calls = self._run_patched_init_slice(patched)
        assert manager_tok is not shared, (
            "the in-place class swap must land on a copy, never the "
            "process-global cache entry"
        )
        assert len(pool_calls) == 1
        wrapped, copies = pool_calls[0]
        assert wrapped is manager_tok
        # max_workers grammar threads + the request-scoped reasoner.
        assert copies == 4 + 1


class TestDriftMarkers:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install(tmp_path, monkeypatch, PIN_STRUCT_OUT)
        patcher = overlay._make_patcher()
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement, (
                    f"drift marker {dm!r} collides with {sp.name} replacement "
                    "— would false-fire (PN369 class)"
                )

    def test_markers_fire_on_merged_form(self):
        non_banner = [
            dm for dm in overlay._DRIFT_MARKERS if not dm.startswith("[Genesis")
        ]
        assert non_banner
        assert any(dm in MERGED_STRUCT_OUT for dm in non_banner)


class TestSameFileNeighborDisjointness:
    """Verdict correction pinned as a gate: PN526 must stay disjoint from
    BOTH same-file patches — P62 (grammar_bitmask / update-from-output
    regions) and PN58 Sub-D (module-level logger anchor before the
    class), the neighbor MISSED in the first triage pass."""

    def test_disjoint_from_pn58_sub_d(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_STRUCT_OUT)
        patcher = overlay._make_patcher()
        anchor = patcher.sub_patches[0].anchor
        assert anchor not in pn58.STRUCT_OUT_OLD
        assert pn58.STRUCT_OUT_OLD not in anchor
        # PN58 Sub-D anchors BEFORE the class; PN526 anchors inside
        # __init__ — both must coexist on one file.
        combined = PIN_STRUCT_OUT.replace(
            pn58.STRUCT_OUT_OLD, pn58.STRUCT_OUT_NEW, 1
        )
        assert combined != PIN_STRUCT_OUT, "PN58 fixture drifted"
        assert combined.count(anchor) == 1

    def test_disjoint_from_p62_regions(self):
        from sndr.engines.vllm.patches.serving import (
            p62_structured_output_spec_decode_timing as p62,
        )
        src = Path(p62.__file__).read_text(encoding="utf-8")
        assert "cached_tokenizer_from_config" not in src


class TestWiring:
    def test_registry_entry(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY
        body = PATCH_REGISTRY["PN526"]
        assert body["family"] == "serving"
        assert body["env_flag"] == (
            "GENESIS_ENABLE_PN526_THREADSAFE_SO_TOKENIZER"
        )
        # P3 latent race, never observed in incident memory -> opt-in.
        assert body["default_on"] is False
        assert body["upstream_pr"] == 47509
        assert body["upstream_pr_relationship"] == "backport"
        assert body["apply_module"] == (
            "sndr.engines.vllm.patches.serving."
            "pn526_threadsafe_so_tokenizer"
        )

    def test_env_flag_attribute(self):
        from sndr.env import Flags
        assert (
            Flags.PN526_THREADSAFE_SO_TOKENIZER
            == "PN526_THREADSAFE_SO_TOKENIZER"
        )


# TestPristinePinInvariants RETIRED (audit #14 full drain, 2026-07-06): it
# byte-checked the anchor against the macOS-only
# Linux rig — so it executed on NO host (permanent green-by-skip). PN526 is
# not recorded in the committed anchor_sot manifest (90/329 gap, audit
# #6/#21), so the byte-check cannot be migrated onto it. The anchor +
# ported-upstream-semantics + drift-marker + neighbor-disjointness + wiring
# contracts stay covered in CI by the synthetic classes above.
