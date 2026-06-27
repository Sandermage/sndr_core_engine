# SPDX-License-Identifier: Apache-2.0
"""Regression tests for issue #33 — decouple the GDN core_attn_out prealloc
buffer size from the P72 profile-run cap.

Reported by jsboige (Ada SM89, 2x RTX 4090, TP=2 + EP=2, Qwen3.6-35B-A3B AWQ
turboquant_k8v4) on the OLD v7.72.5 tree (vllm nightly 01d4d1ad3):

    RuntimeError: setStorage: sizes [5536, 16, 128] ... requiring a storage
    size of 22675456 are out of bounds for storage of size 16777216
        # 16777216 = 4096 * 16 * 128 * 2 (buffer sized for the P72 cap 4096)
        # 22675456 = 5536 * 16 * 128 * 2 (a real combined forward of 5536)

Root cause (NOT pristine vLLM — pristine `forward_cuda` does a per-forward
`torch.zeros((num_tokens, ...))` that self-sizes): the Genesis P28 patch
replaces that with a layer-persistent pre-allocated buffer sized at a
resolved token budget. On v7.72.5, P28's budget hardcoded 4096 and never
read the live scheduler config, so at `--max-num-batched-tokens 8192` the
buffer stayed 4096 while a co-scheduled prefill+decode forward summed to
5536 tokens — `[:5536]` on a 4096-row buffer silently returned 4096 rows,
and Inductor's `as_strided` alias regeneration died with setStorage OOB.

The fix (already in the dev424 tree) decouples the two roles on TWO layers:

  1. Budget resolver (`prealloc_budget.resolve_token_budget`) — priority 3
     reads `vllm scheduler_config.max_num_batched_tokens`, so the P28 buffer
     is sized from --max-num-batched-tokens, NOT the P72 profile cap. The
     P72 cap (`GENESIS_PROFILE_RUN_CAP_M`) still bounds ONLY the
     `determine_available_memory()` profiling forward (dodging crash A) and
     no longer governs the GDN buffer.

  2. forward_cuda v2 capacity guard (2026-06-10) — the patched allocation
     only reuses the prealloc when `shape[0] >= num_tokens`; otherwise it
     falls through to a fresh `torch.zeros((num_tokens, ...))`. Even if the
     buffer were undersized for any reason, an over-capacity forward can
     never alias past the prealloc storage.

These tests would FAIL against the v7.72.5 v1 code (hardcoded-4096 budget,
no scheduler probe, no capacity guard) and PASS against the dev424 tree.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import re
from pathlib import Path

import torch


class TestIssue33BudgetDecoupledFromProfileCap:
    """The GDN prealloc budget is sized from scheduler_config
    (max_num_batched_tokens), independent of the P72 profile cap."""

    def test_budget_reads_scheduler_config_not_profile_cap(
        self, monkeypatch, reset_genesis_prealloc,
    ):
        """Priority 3: with no env override, the resolver reads
        scheduler_config.max_num_batched_tokens. This is THE decoupling —
        the buffer follows --max-num-batched-tokens (8192), not the
        GENESIS_PROFILE_RUN_CAP_M=4096 used by P72 for profiling."""
        from sndr.runtime import prealloc_budget as pb

        # No global override, no domain env → must fall to the live config.
        monkeypatch.delenv("GENESIS_PREALLOC_TOKEN_BUDGET", raising=False)
        monkeypatch.delenv("GENESIS_GDN_MAX_BATCHED_TOKENS", raising=False)
        # Simulate live vLLM scheduler config reporting batched=8192 while
        # the P72 profile cap is 4096. The resolver must NOT see 4096.
        monkeypatch.setattr(pb, "_probe_vllm_config", lambda: 8192)

        resolved = pb.resolve_token_budget(domain_env="GENESIS_GDN_MAX_BATCHED_TOKENS")
        assert resolved == 8192, (
            "GDN prealloc budget must follow scheduler_config "
            "max_num_batched_tokens (8192), NOT the P72 profile cap (4096). "
            f"got {resolved}"
        )

    def test_profile_cap_env_does_not_size_the_gdn_buffer(
        self, monkeypatch, reset_genesis_prealloc,
    ):
        """GENESIS_PROFILE_RUN_CAP_M (the P72 knob) must have ZERO effect on
        the GDN prealloc budget — they are different knobs for different
        roles. Setting it to 4096 while batched=8192 must still yield 8192."""
        from sndr.runtime import prealloc_budget as pb

        monkeypatch.delenv("GENESIS_PREALLOC_TOKEN_BUDGET", raising=False)
        monkeypatch.delenv("GENESIS_GDN_MAX_BATCHED_TOKENS", raising=False)
        # The P72 profile cap — must be ignored by the GDN budget resolver.
        monkeypatch.setenv("GENESIS_PROFILE_RUN_CAP_M", "4096")
        monkeypatch.setattr(pb, "_probe_vllm_config", lambda: 8192)

        resolved = pb.resolve_token_budget(domain_env="GENESIS_GDN_MAX_BATCHED_TOKENS")
        assert resolved == 8192, (
            "GENESIS_PROFILE_RUN_CAP_M must not couple to the GDN buffer "
            f"size. Expected 8192 (from scheduler_config), got {resolved}"
        )

    def test_hint_from_scheduler_config_wins(self, reset_genesis_prealloc):
        """The allocation site passes max_num_batched_tokens as `hint`;
        the hint is authoritative and overflow-band-safe."""
        from sndr.runtime import prealloc_budget as pb

        assert pb.resolve_token_budget(hint=8192) == 8192


class TestIssue33OverflowBandSurvives:
    """A single forward whose token count lands in (cap, max_num_batched_tokens]
    must not overflow the GDN buffer — it self-sizes / falls back."""

    def test_combined_forward_above_cap_does_not_overflow(
        self, monkeypatch, reset_genesis_prealloc,
    ):
        """The reporter's exact band: buffer sized for cap=4096, a real
        combined forward of 5536 tokens. acquire_slice must return a
        correctly-sized, zeroed tensor — never silently truncate to 4096."""
        from sndr.engines.vllm.kernels_legacy import gdn_core_attn_manager as m

        m._SHOULD_APPLY_CACHED = True  # force the prealloc path on (CPU test)
        # 35B GDN geometry per the report: 16 v_heads (TP=2), head_v_dim=128.
        slice_ = m.GdnCoreAttnManager.acquire_slice(
            num_tokens=5536, num_v_heads=16, head_v_dim=128,
            device="cpu", dtype=torch.float16,
            num_tokens_max=4096,  # buffer sized at the old cap
        )
        # Must be the REAL 5536 rows, not silently 4096.
        assert slice_.shape == (5536, 16, 128), (
            "overflow-band forward must get a full-size buffer, not a "
            f"truncated 4096-row view. got {tuple(slice_.shape)}"
        )
        assert slice_.sum().item() == 0.0  # zero-initialised (correctness)

    def test_in_band_forward_uses_prealloc(
        self, monkeypatch, reset_genesis_prealloc,
    ):
        """A forward within budget reuses the persistent prealloc (the perf
        path P28 exists for) — proves the fallback is only for overflow."""
        from sndr.engines.vllm.kernels_legacy import gdn_core_attn_manager as m

        m._SHOULD_APPLY_CACHED = True
        s1 = m.GdnCoreAttnManager.acquire_slice(
            num_tokens=2048, num_v_heads=16, head_v_dim=128,
            device="cpu", dtype=torch.float16, num_tokens_max=8192,
        )
        s2 = m.GdnCoreAttnManager.acquire_slice(
            num_tokens=2048, num_v_heads=16, head_v_dim=128,
            device="cpu", dtype=torch.float16, num_tokens_max=8192,
        )
        # Same persistent pool → pointer-stable in-band.
        assert s1.data_ptr() == s2.data_ptr()


class TestIssue33ForwardCudaCapacityGuard:
    """The applied forward_cuda text-patch carries the v2 capacity guard.

    This guard (`shape[0] >= num_tokens` else eager torch.zeros) is the
    in-graph belt that makes the setStorage/as_strided overflow impossible.
    Its ABSENCE is exactly the v7.72.5 bug, so we assert it textually in the
    patch source (the bytes that get written into the live container)."""

    def _patch_source(self) -> str:
        from sndr.engines.vllm.patches.attention.gdn import p28_gdn_core_attn as p28
        return Path(p28.__file__).read_text()

    def test_patch_has_capacity_guard(self):
        src = self._patch_source()
        # The decisive v2 guard: only reuse the prealloc when it is large
        # enough for the current forward.
        assert "self._genesis_gdn_core_attn_buf.shape[0] >= num_tokens" in src, (
            "P28 forward_cuda replacement is MISSING the v2 capacity guard "
            "(shape[0] >= num_tokens). Without it, an over-capacity forward "
            "silently truncates and Inductor as_strided overflows storage "
            "(the issue #33 / v7.72.5 setStorage crash)."
        )

    def test_patch_has_eager_fallback_torch_zeros(self):
        src = self._patch_source()
        # The over-capacity branch must allocate a fresh, full-size buffer
        # shaped from the REAL num_tokens (self-sizing, like pristine vLLM).
        m = re.search(
            r"else\s+torch\.zeros\(.*?num_tokens,\s*self\.num_v_heads\s*"
            r"//\s*self\.tp_size,\s*self\.head_v_dim",
            src,
            re.DOTALL,
        )
        assert m is not None, (
            "P28 forward_cuda replacement must fall back to a fresh "
            "torch.zeros((num_tokens, ...)) when over capacity."
        )
