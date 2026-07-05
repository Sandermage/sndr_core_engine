# SPDX-License-Identifier: Apache-2.0
"""PN524 — skip uniform spec-decode padding for diffusion (vllm#47464).

Contract pinned here (TDD, written before the implementation).

Upstream bug (vllm#47464): diffusion lanes initialize the scheduler with
``num_spec_tokens = canvas_length`` while ``num_sampled_tokens_per_step =
0`` (scheduler __init__, model_config.is_diffusion). Diffusion "spec
tokens" are the fixed-size denoising canvas, NOT rejectable drafts. The
spec-decode padding block in ``Scheduler.schedule`` pads any 1-token
decode request in a running-decode batch to ``1 + num_spec_tokens`` to
preserve full cudagraph — for a diffusion lane that pads a resumed /
prefix-cache-hit request to 1 + canvas_length -> canvas overflow
RuntimeError -> engine death. REACHABLE on prod-diffusiongemma-tp2:
max_num_seqs=2, KV pool capped at 8192 blocks (131072 tokens =
max_model_len), prefix caching default-on -> a preemption/resume or
full-prompt prefix hit while another request decodes is organic under
aggregator dual-stream traffic.

PN524 vendors upstream's one-line guard VERBATIM
(``and self.num_sampled_tokens_per_step > 0``) — arch/model-neutral and
INERT for AR MTP lanes (AR schedulers set num_sampled_tokens_per_step
>= 1), preserving upstream's gates exactly.

Sub-contracts:
  1. One required sub-patch anchored on the unique padding condition
     block (scheduler.py 812-818 class; count==1 byte-verified in
     pristine dev748 2dfaae752 via gh api, guard-ABSENT confirmed).
  2. The patched condition, executed as real Python, ports the upstream
     test semantics: diffusion (num_sampled_tokens_per_step=0) never
     pads; AR (>0) pads exactly as before.
  3. Patched file still compiles.
  4. Idempotent second apply; drift-marker self-skip on the merged form
     (upstream comment "Not for diffusion where draft tokens can't be
     padded." — never emitted by us); gate-closed no-op.
  5. Same-file hygiene: p58/p34/p74/p79c/pn388 anchors are disjoint from
     the padding block (grep-verified; p58's num_sampled_tokens_per_step
     regions are elsewhere in the file).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.scheduler import (  # noqa: E402
    pn524_diffusion_spec_padding_skip as overlay,
)

# ── Fixture: pin-form anchor region (byte-faithful, dev748 2dfaae752) ─

PIN_SCHEDULER = (
    "# fake v1/core/sched/scheduler.py (pin 2dfaae752 form)\n"
    "class Scheduler:\n"
    "    def schedule(self, throttle_prefills: bool = False):\n"
    "        while True:\n"
    "            if True:\n"
    "                pass\n"
    "            else:\n"
    "                    # Number of tokens to be scheduled.\n"
    "                    # We use `request.num_tokens` instead of\n"
    "                    # `request.num_prompt_tokens` to consider the resumed\n"
    "                    # requests, which have output tokens.\n"
    "                    num_new_tokens = request.num_tokens - num_computed_tokens\n"
    "\n"
    "                    # Pad new decode requests to uniform spec decoding size to\n"
    "                    # preserve full cudagraph for this step.\n"
    "                    if (\n"
    "                        (self.num_spec_tokens > 0 and self.dynamic_sd_lookup is None)\n"
    "                        and num_new_tokens == 1\n"
    "                        and (scheduled_running_reqs and not prefill_scheduled)\n"
    "                    ):\n"
    "                        num_new_tokens = 1 + self.num_spec_tokens\n"
)

# #47464 merged form (exact hunk from `gh pr diff 47464`, 2026-07-05).
MERGED_SCHEDULER = PIN_SCHEDULER.replace(
    "                    # Pad new decode requests to uniform spec decoding size to\n"
    "                    # preserve full cudagraph for this step.\n"
    "                    if (\n"
    "                        (self.num_spec_tokens > 0 and self.dynamic_sd_lookup is None)\n",
    "                    # Pad new decode requests to uniform spec decoding size to\n"
    "                    # preserve full cudagraph for this step.\n"
    "                    # Not for diffusion where draft tokens can't be padded.\n"
    "                    if (\n"
    "                        (self.num_spec_tokens > 0 and self.dynamic_sd_lookup is None)\n"
    "                        and self.num_sampled_tokens_per_step > 0\n",
).replace("(pin 2dfaae752 form)", "(post-vllm#47464 merged form)")


def _install(tmp_path, monkeypatch, text):
    target = tmp_path / "scheduler.py"
    target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
    monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
    from sndr import dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


def _padding_condition_fires(patched: str, **ns) -> bool:
    """Extract the patched `if (...)` padding condition and evaluate it
    with the given scheduler/loop state — the upstream test semantics at
    the level executable without a vLLM install."""
    start = patched.index("                    if (\n")
    end = patched.index("                    ):\n", start)
    cond = patched[start + len("                    if (\n") : end]
    cond_expr = "(" + cond.replace("\n", " ") + ")"

    class _Self:
        pass

    self_obj = _Self()
    self_obj.num_spec_tokens = ns.pop("num_spec_tokens")
    self_obj.dynamic_sd_lookup = ns.pop("dynamic_sd_lookup", None)
    self_obj.num_sampled_tokens_per_step = ns.pop("num_sampled_tokens_per_step")
    return bool(
        eval(  # noqa: S307 - test-only evaluation of the patched condition
            cond_expr, {"self": self_obj}, ns
        )
    )


class TestPatcherShape:
    def test_single_required_subpatch(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_SCHEDULER)
        patcher = overlay._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert set(by_name) == {"pn524_diffusion_spec_padding_guard"}
        assert by_name["pn524_diffusion_spec_padding_guard"].required is True

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: None)
        assert overlay._make_patcher() is None


class TestApply:
    def test_apply_inserts_upstream_guard_verbatim(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_SCHEDULER)
        status, reason = overlay.apply()
        assert status == "applied", reason
        out = target.read_text(encoding="utf-8")
        # Upstream's one-line guard, verbatim, exactly once, in position.
        assert out.count(
            "                        and self.num_sampled_tokens_per_step > 0\n"
        ) == 1
        assert (
            out.index("self.num_spec_tokens > 0 and self.dynamic_sd_lookup is None")
            < out.index("and self.num_sampled_tokens_per_step > 0")
            < out.index("and num_new_tokens == 1")
        )
        compile(out, str(target), "exec")

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_SCHEDULER)
        first, first_reason = overlay.apply()
        assert first == "applied", first_reason
        second, second_reason = overlay.apply()
        assert second == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_merged_form(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, MERGED_SCHEDULER)
        status, reason = overlay.apply()
        assert status == "skipped"
        assert "upstream" in reason.lower()
        assert target.read_text(encoding="utf-8") == MERGED_SCHEDULER

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        target = tmp_path / "scheduler.py"
        target.write_text(PIN_SCHEDULER, encoding="utf-8")
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
        monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
        from sndr import dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "gate closed")
        )
        status, _reason = overlay.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_SCHEDULER


class TestPortedUpstreamSemantics:
    """Port of test_spec_decode_padding_skipped_for_diffusion at the
    executable-condition level: the guarded condition must not fire for
    a diffusion scheduler (num_sampled_tokens_per_step == 0) while
    keeping every AR behavior identical."""

    @pytest.fixture
    def patched(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_SCHEDULER)
        status, reason = overlay.apply()
        assert status == "applied", reason
        return target.read_text(encoding="utf-8")

    def test_diffusion_one_token_resume_not_padded(self, patched):
        # r2: 1-token prefix-cache-hit resume while r1 decodes — the
        # #47464 canvas-overflow shape. Diffusion: sampled-per-step == 0.
        assert not _padding_condition_fires(
            patched,
            num_spec_tokens=3,
            num_sampled_tokens_per_step=0,
            num_new_tokens=1,
            scheduled_running_reqs=["r1"],
            prefill_scheduled=False,
        )

    def test_ar_mtp_padding_preserved(self, patched):
        # AR MTP lane (K=5): sampled-per-step >= 1 — guard is inert,
        # padding fires exactly as pre-patch.
        assert _padding_condition_fires(
            patched,
            num_spec_tokens=5,
            num_sampled_tokens_per_step=1,
            num_new_tokens=1,
            scheduled_running_reqs=["r1"],
            prefill_scheduled=False,
        )

    @pytest.mark.parametrize(
        "kw",
        [
            # no spec tokens configured
            {"num_spec_tokens": 0, "num_sampled_tokens_per_step": 1},
            # prefill in batch -> already non-uniform, padding skipped
            {"num_spec_tokens": 5, "num_sampled_tokens_per_step": 1,
             "prefill_scheduled": True},
            # multi-token request (not a bare decode)
            {"num_spec_tokens": 5, "num_sampled_tokens_per_step": 1,
             "num_new_tokens": 7},
            # dynamic-SD lane owns its own widths
            {"num_spec_tokens": 5, "num_sampled_tokens_per_step": 1,
             "dynamic_sd_lookup": object()},
        ],
    )
    def test_upstream_skip_gates_preserved(self, patched, kw):
        base = {
            "num_new_tokens": 1,
            "scheduled_running_reqs": ["r1"],
            "prefill_scheduled": False,
        }
        base.update(kw)
        assert not _padding_condition_fires(patched, **base)


class TestDriftMarkers:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install(tmp_path, monkeypatch, PIN_SCHEDULER)
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
        assert any(dm in MERGED_SCHEDULER for dm in non_banner)


class TestWiring:
    def test_registry_entry(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY
        body = PATCH_REGISTRY["PN524"]
        assert body["family"] == "scheduler"
        assert body["env_flag"] == (
            "GENESIS_ENABLE_PN524_DIFFUSION_SPEC_PADDING_SKIP"
        )
        assert body["upstream_pr"] == 47464
        assert body["upstream_pr_relationship"] == "backport"
        assert body["apply_module"] == (
            "sndr.engines.vllm.patches.scheduler."
            "pn524_diffusion_spec_padding_skip"
        )

    def test_env_flag_attribute(self):
        from sndr.env import Flags
        assert (
            Flags.PN524_DIFFUSION_SPEC_PADDING_SKIP
            == "PN524_DIFFUSION_SPEC_PADDING_SKIP"
        )

    def test_enabled_on_diffusiongemma_lane(self):
        """The engine-death shape is organic on prod-diffusiongemma-tp2
        (max_num_seqs=2 + 8192-block KV cap + APC default-on) — the flag
        must ride the ModelDef so the guard is live on that lane."""
        repo_root = Path(__file__).resolve().parents[4]
        model_yaml = (
            repo_root
            / "sndr/model_configs/builtin/model/diffusiongemma-26b-a4b-fp8.yaml"
        )
        text = model_yaml.read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_PN524_DIFFUSION_SPEC_PADDING_SKIP: '1'" in text


# ── Pristine pin invariants: RETIRED (audit #14 full drain, 2026-07-06) ──
# The former ``TestPristinePinInvariants`` byte-checked the anchor against
# the macOS-only ``/private/tmp/candidate_pin_current`` path — empty on CI,
# absent on the Linux rig: executed on NO host, a permanent green-by-skip.
# PN524 is NOT recorded in the committed anchor_sot manifest (90/329 coverage
# gap, audit #6/#21), so the byte-check cannot be migrated onto it. Retired;
# the anchor + ported-upstream-semantics + drift-marker + wiring contracts
# stay covered in CI by the synthetic classes above.
