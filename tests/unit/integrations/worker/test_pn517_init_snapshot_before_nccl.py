# SPDX-License-Identifier: Apache-2.0
"""TDD for PN517 — take the init MemorySnapshot before NCCL (vllm#45517).

Beyond anchor/idempotency/drift checks, this EXECUTES the patched code on
a synthetic `init_device` to prove the ON-vs-OFF runtime difference
(iron-rule #3): with `VLLM_INIT_SNAPSHOT_BEFORE_NCCL` set, the snapshot is
taken before NCCL and reused at init; unset, behavior is the unchanged
post-NCCL path.
"""
from __future__ import annotations

import py_compile

from sndr.kernel import TextPatch, TextPatcher, TextPatchResult
import sndr.engines.vllm.patches.worker.pn517_init_snapshot_before_nccl as M


# Synthetic init_device carrying the byte-exact anchor lines, wrapped in a
# `with` so the body is at the same 12-space indent as the real method.
PRISTINE = '''import contextlib


class Worker:
    def __init__(self):
        self.device = "cuda:0"
        self.model_config = _MC()
        self.nccl_inited = False

    def init_device(self):
        with contextlib.nullcontext():
            self.device = "cuda:0"
            current_platform.check_if_supports_dtype(self.model_config.dtype)

            # Initialize the distributed environment BEFORE taking
            # memory snapshot
            # This ensures NCCL buffers are allocated before we measure
            # available memory
            _init_nccl(self)

            # take current memory snapshot
            self.init_snapshot = init_snapshot = MemorySnapshot(device=self.device)
            return self.init_snapshot
'''


def _patcher(target: str) -> TextPatcher:
    return TextPatcher(
        patch_name="PN517-test",
        target_file=target,
        marker=M.GENESIS_PN517_MARKER,
        sub_patches=[
            TextPatch(
                name="pN517_pre_nccl_snapshot",
                anchor=M.PN517_PART1_ANCHOR,
                replacement=M.PN517_PART1_REPLACEMENT,
                required=True,
            ),
            TextPatch(
                name="pN517_reuse_snapshot_at_init",
                anchor=M.PN517_PART2_ANCHOR,
                replacement=M.PN517_PART2_REPLACEMENT,
                required=True,
            ),
        ],
        upstream_drift_markers=[],
    )


def _write(tmp_path, text):
    f = tmp_path / "gpu_worker.py"
    f.write_text(text)
    return str(f)


def _exec_namespace():
    """A namespace with the stubs the inserted code references."""
    snaps = []

    class FakeSnapshot:
        def __init__(self, device=None):
            self.device = device
            self.free_memory = 1000 + len(snaps)  # distinct per instance
            snaps.append(self)

    def MemorySnapshot(device=None):
        return FakeSnapshot(device)

    class _MC:
        dtype = "bfloat16"

    class _Platform:
        @staticmethod
        def check_if_supports_dtype(dtype):
            return None

    class _Logger:
        def info(self, *a, **k):
            return None

    def _init_nccl(self):
        self.nccl_inited = True

    import os as _os

    return {
        "MemorySnapshot": MemorySnapshot,
        "format_gib": lambda b: f"{b}B",
        "logger": _Logger(),
        "current_platform": _Platform(),
        "_MC": _MC,
        "_init_nccl": _init_nccl,
        "os": _os,
        "_snaps": snaps,
    }


class TestAnchors:
    def test_anchors_appear_once(self):
        assert PRISTINE.count(M.PN517_PART1_ANCHOR) == 1
        assert PRISTINE.count(M.PN517_PART2_ANCHOR) == 1


class TestApply:
    def test_applies_both_and_compiles(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        p = _patcher(target)
        result, failure = p.apply()
        assert result == TextPatchResult.APPLIED, failure
        assert len(p.applied_sub_patches) == 2
        py_compile.compile(target, doraise=True)

    def test_idempotent(self, tmp_path):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        r2, _ = _patcher(target).apply()
        assert r2 == TextPatchResult.IDEMPOTENT


class TestRuntimeBehavior:
    """Execute the patched code: prove ON-vs-OFF observable difference."""

    def _patched_worker(self, tmp_path, env):
        target = _write(tmp_path, PRISTINE)
        _patcher(target).apply()
        src = open(target).read()
        ns = _exec_namespace()
        ns["os"].environ.pop("VLLM_INIT_SNAPSHOT_BEFORE_NCCL", None)
        if env is not None:
            ns["os"].environ["VLLM_INIT_SNAPSHOT_BEFORE_NCCL"] = env
        exec(compile(src, target, "exec"), ns)
        w = ns["Worker"]()
        snap = w.init_device()
        return w, snap, ns

    def test_off_takes_post_nccl_snapshot(self, tmp_path):
        w, snap, ns = self._patched_worker(tmp_path, env=None)
        # pre-NCCL snapshot not taken; observability bytes None
        assert w._genesis_pn517_snapshot is None
        assert w._startup_free_bytes is None
        # exactly one snapshot, taken AFTER nccl init
        assert len(ns["_snaps"]) == 1
        assert w.nccl_inited is True
        assert w.init_snapshot is snap
        try:
            ns["os"].environ.pop("VLLM_INIT_SNAPSHOT_BEFORE_NCCL", None)
        except Exception:
            pass

    def test_on_reuses_pre_nccl_snapshot(self, tmp_path):
        w, snap, ns = self._patched_worker(tmp_path, env="1")
        try:
            # pre-NCCL snapshot taken + observability recorded
            assert w._genesis_pn517_snapshot is not None
            assert w._startup_free_bytes == w._genesis_pn517_snapshot.free_memory
            # only ONE snapshot total — init reused the pre-NCCL one
            assert len(ns["_snaps"]) == 1
            assert w.init_snapshot is w._genesis_pn517_snapshot
            assert w.init_snapshot is snap
        finally:
            ns["os"].environ.pop("VLLM_INIT_SNAPSHOT_BEFORE_NCCL", None)


class TestDriftSafety:
    def test_missing_anchor_skips(self, tmp_path):
        merged = PRISTINE.replace(
            M.PN517_PART2_ANCHOR,
            "            # take current memory snapshot\n"
            "            self.init_snapshot = init_snapshot = other()\n",
        )
        target = _write(tmp_path, merged)
        result, failure = _patcher(target).apply()
        assert result == TextPatchResult.SKIPPED
        assert failure.reason == "required_anchor_missing"
        assert M.GENESIS_PN517_MARKER not in open(target).read()


class TestDispatcherWiring:
    def test_registry_entry_well_formed(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY

        meta = PATCH_REGISTRY["PN517"]
        assert meta["family"] == "worker"
        assert meta["default_on"] is False
        assert meta["env_flag"] == "GENESIS_ENABLE_PN517_INIT_SNAPSHOT_BEFORE_NCCL"
        assert meta["upstream_pr"] == 45517

    def test_apply_skips_without_optin(self, monkeypatch):
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN517_INIT_SNAPSHOT_BEFORE_NCCL", raising=False
        )
        status, reason = M.apply()
        assert status == "skipped"
        assert isinstance(reason, str) and reason
