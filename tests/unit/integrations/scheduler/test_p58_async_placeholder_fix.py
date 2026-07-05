# SPDX-License-Identifier: Apache-2.0
"""TDD for Patch 58 — async-scheduler -1 placeholder leakage fix.

Backport of vllm-project/vllm#40768.

These tests verify three properties of the patch:
  1. Anchor design: each of the 3 target files has the OLD anchor present
     and is correctly transformed to the NEW shape.
  2. Idempotency: re-applying the patcher leaves the file unchanged.
  3. Upstream-drift safety: when the upstream marker
     `num_pending_async_spec_placeholders` is already in the file, the
     whole P58 group skips cleanly (no double-write, no anchor mismatch).

We DO NOT exercise the actual scheduler logic here (that requires a full
vLLM stack). The behavioral validation happens via integration test on
the running vllm-server container after the patch is applied — see the
v7_12_session/ probe scripts.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Snapshots of the OLD (pre-fix) anchor blocks as they appear in vLLM
# fe9c3d6c5. If upstream drifts, these tests fail loudly — that's the
# signal to re-anchor P58 against the new upstream layout.

REQUEST_PY_OLD_FIELD = (
    "        self.spec_token_ids: list[int] = []\n"
    "        self.num_computed_tokens = 0"
)

REQUEST_PY_OLD_NUM_TOKENS = (
    "    def num_tokens_with_spec(self) -> int:\n"
    "        return len(self._all_token_ids) + len(self.spec_token_ids)"
)

ASYNC_SCHED_PY_OLD = (
    "            request.num_output_placeholders += 1 + cur_num_spec_tokens\n"
    "            # Add placeholders for the new draft/spec tokens.\n"
    "            # We will update the actual spec token ids in the worker process.\n"
    "            request.spec_token_ids = self._spec_token_placeholders"
)

# dev491 layout: the `num_output_placeholders` increment was reshaped to a
# parenthesised multi-line expression adding the new
# `num_sampled_tokens_per_step` term. The dev259 single-line anchor no longer
# matches this; the P58 dual-anchor adds a dev491-shaped Variant B for it.
ASYNC_SCHED_PY_OLD_DEV491 = (
    "            request.num_output_placeholders += (\n"
    "                self.num_sampled_tokens_per_step + cur_num_spec_tokens\n"
    "            )\n"
    "            # Add placeholders for the new draft/spec tokens.\n"
    "            # We will update the actual spec token ids in the worker process.\n"
    "            request.spec_token_ids = self._spec_token_placeholders"
)

SCHED_PY_OLD_SPEC_BLOCK = (
    "            # Speculative decode related.\n"
    "            if request.spec_token_ids:\n"
    "                num_scheduled_spec_tokens = (\n"
    "                    num_new_tokens\n"
    "                    + request.num_computed_tokens\n"
    "                    - request.num_tokens\n"
    "                    - request.num_output_placeholders\n"
    "                )\n"
)

SCHED_PY_OLD_PREEMPT = (
    "        if request.spec_token_ids:\n"
    "            request.spec_token_ids = []\n"
    "        request.num_preemptions += 1"
)

SCHED_PY_OLD_DRAFT = (
    "            if request.is_prefill_chunk:\n"
    "                # Ignore draft tokens for prefill chunks.\n"
    "                if request.spec_token_ids:\n"
    "                    request.spec_token_ids = []\n"
    "                continue"
)


@pytest.fixture
def fake_request_py(tmp_path):
    """Synthetic request.py mimicking the buggy structure."""
    p = tmp_path / "request.py"
    p.write_text(
        "class Request:\n"
        "    def __init__(self, ...):\n"
        "        self.num_output_placeholders = 0\n"
        "        self.discard_latest_async_tokens = False\n"
        "\n"
        + REQUEST_PY_OLD_FIELD + "\n"
        + "        self.cache_salt = None\n"
        "\n"
        "    @property\n"
        + REQUEST_PY_OLD_NUM_TOKENS + "\n"
    )
    return str(p)


@pytest.fixture
def fake_async_sched_py(tmp_path):
    """Synthetic async_scheduler.py mimicking the buggy dev259 structure."""
    p = tmp_path / "async_scheduler.py"
    p.write_text(
        "class AsyncScheduler(Scheduler):\n"
        "    def _update_after_schedule(self, scheduler_output):\n"
        "        spec_decode_tokens = scheduler_output.scheduled_spec_decode_tokens\n"
        "        for req_id in scheduler_output.num_scheduled_tokens:\n"
        "            request = self.requests[req_id]\n"
        "            cur_num_spec_tokens = len(spec_decode_tokens.get(req_id, ()))\n"
        + ASYNC_SCHED_PY_OLD + "\n"
    )
    return str(p)


@pytest.fixture
def fake_async_sched_py_dev491(tmp_path):
    """Synthetic async_scheduler.py mimicking the dev491 structure.

    dev491 reshaped the `num_output_placeholders` increment into a
    parenthesised multi-line expression (adds the new
    `num_sampled_tokens_per_step` term). The dev259 single-line anchor
    cannot match this; only the P58 dev491 Variant B anchor can.
    """
    # Distinct filename so a test using BOTH fixtures does not have the
    # dev491 write clobber the dev259 file under a shared tmp_path.
    p = tmp_path / "async_scheduler_dev491.py"
    p.write_text(
        "class AsyncScheduler(Scheduler):\n"
        "    def _update_after_schedule(self, scheduler_output):\n"
        "        spec_decode_tokens = scheduler_output.scheduled_spec_decode_tokens\n"
        "        for req_id in scheduler_output.num_scheduled_tokens:\n"
        "            request = self.requests[req_id]\n"
        "            cur_num_spec_tokens = len(spec_decode_tokens.get(req_id, ()))\n"
        + ASYNC_SCHED_PY_OLD_DEV491 + "\n"
    )
    return str(p)


@pytest.fixture
def fake_scheduler_py(tmp_path):
    """Synthetic scheduler.py with all four anchor blocks."""
    p = tmp_path / "scheduler.py"
    p.write_text(
        "class Scheduler:\n"
        "    def schedule(self):\n"
        "        scheduled_spec_decode_tokens = {}\n"
        "        for request in []:\n"
        + SCHED_PY_OLD_SPEC_BLOCK
        + "                if num_scheduled_spec_tokens > 0:\n"
        "                    spec_token_ids = request.spec_token_ids\n"
        "                    if len(spec_token_ids) > num_scheduled_spec_tokens:\n"
        "                        spec_token_ids = spec_token_ids[:num_scheduled_spec_tokens]\n"
        "                    scheduled_spec_decode_tokens[request.request_id] = spec_token_ids\n"
        "\n"
        "                # New spec tokens will be set in `update_draft_token_ids` before the\n"
        "                # next step when applicable.\n"
        "                request.spec_token_ids = []\n"
        "\n"
        "            self._update_after_schedule(scheduler_output)\n"
        "        return scheduler_output\n"
        "\n"
        "    def _build_kv_connector_meta(self, connector, scheduler_output):\n"
        "        return None\n"
        "\n"
        "    def _preempt_request(self, request, timestamp):\n"
        "        request.status = 'preempted'\n"
        "        request.num_computed_tokens = 0\n"
        + SCHED_PY_OLD_PREEMPT + "\n"
        "\n"
        "    def update_draft_token_ids(self, draft_token_ids):\n"
        "        for req_id, spec_token_ids in []:\n"
        "            request = self.requests.get(req_id)\n"
        + SCHED_PY_OLD_DRAFT + "\n"
        "\n"
        "            # Add newly generated spec token ids to the request.\n"
        "            if self.structured_output_manager.should_advance(request):\n"
        "                metadata = request.structured_output_request\n"
        "                spec_token_ids = metadata.grammar.validate_tokens(spec_token_ids)  # type: ignore[union-attr]\n"
        "            request.spec_token_ids = spec_token_ids\n"
    )
    return str(p)


class TestP58RequestPyPatch:
    def test_anchors_present_in_synthetic_file(self, fake_request_py):
        content = Path(fake_request_py).read_text()
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            REQUEST_FIELD_OLD,
            REQUEST_NUM_TOKENS_OLD,
        )
        assert REQUEST_FIELD_OLD in content
        assert REQUEST_NUM_TOKENS_OLD in content

    def test_apply_succeeds_and_adds_counter_field(self, fake_request_py):
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            REQUEST_FIELD_NEW,
            REQUEST_FIELD_OLD,
            REQUEST_NUM_TOKENS_NEW,
            REQUEST_NUM_TOKENS_OLD,
        )
        from sndr.kernel.text_patch import (
            TextPatch,
            TextPatcher,
            TextPatchResult,
        )

        patcher = TextPatcher(
            patch_name="P58 request.py test",
            target_file=fake_request_py,
            marker="P58_TEST_REQUEST",
            sub_patches=[
                TextPatch(
                    name="field", anchor=REQUEST_FIELD_OLD,
                    replacement=REQUEST_FIELD_NEW, required=True,
                ),
                TextPatch(
                    name="num_tokens", anchor=REQUEST_NUM_TOKENS_OLD,
                    replacement=REQUEST_NUM_TOKENS_NEW, required=True,
                ),
            ],
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        modified = Path(fake_request_py).read_text()
        assert "num_pending_async_spec_placeholders = 0" in modified
        assert "num_pending_async_spec_placeholders" in modified


class TestP58AsyncSchedulerPyPatch:
    def test_anchor_present(self, fake_async_sched_py):
        content = Path(fake_async_sched_py).read_text()
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            ASYNC_SCHED_OLD,
        )
        assert ASYNC_SCHED_OLD in content
        # Critical: confirm the buggy line is exactly what we expect.
        assert "request.spec_token_ids = self._spec_token_placeholders" in content

    def test_apply_replaces_list_assignment_with_counter(self, fake_async_sched_py):
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            ASYNC_SCHED_NEW,
            ASYNC_SCHED_OLD,
        )
        from sndr.kernel.text_patch import (
            TextPatch,
            TextPatcher,
            TextPatchResult,
        )
        patcher = TextPatcher(
            patch_name="P58 async_sched test",
            target_file=fake_async_sched_py,
            marker="P58_TEST_ASYNC_SCHED",
            sub_patches=[
                TextPatch(
                    name="assign", anchor=ASYNC_SCHED_OLD,
                    replacement=ASYNC_SCHED_NEW, required=True,
                ),
            ],
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        modified = Path(fake_async_sched_py).read_text()
        assert "request.spec_token_ids = self._spec_token_placeholders" not in modified
        assert "request.num_pending_async_spec_placeholders = self.num_spec_tokens" in modified

    def test_dev491_anchor_present_only_in_dev491_layout(
        self, fake_async_sched_py, fake_async_sched_py_dev491
    ):
        """Dual-anchor mutual exclusivity: each pin's layout contains exactly
        ONE of the two variant anchors, never both."""
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            ASYNC_SCHED_OLD,
            ASYNC_SCHED_OLD_DEV491,
        )
        dev259 = Path(fake_async_sched_py).read_text()
        dev491 = Path(fake_async_sched_py_dev491).read_text()
        # dev259 layout: only Variant A matches.
        assert ASYNC_SCHED_OLD in dev259
        assert ASYNC_SCHED_OLD_DEV491 not in dev259
        # dev491 layout: only Variant B matches.
        assert ASYNC_SCHED_OLD_DEV491 in dev491
        assert ASYNC_SCHED_OLD not in dev491

    def test_dual_anchor_applies_dev491_variant_on_dev491_layout(
        self, fake_async_sched_py_dev491
    ):
        """On the dev491 layout the dev259 Variant A soft-skips (required=False)
        and the dev491 Variant B fires, producing the same counter-based fix.
        This is the re-anchor case for the dev259→dev491 pin bump."""
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            ASYNC_SCHED_NEW,
            ASYNC_SCHED_NEW_DEV491,
            ASYNC_SCHED_OLD,
            ASYNC_SCHED_OLD_DEV491,
        )
        from sndr.kernel.text_patch import (
            TextPatch,
            TextPatcher,
            TextPatchResult,
        )
        patcher = TextPatcher(
            patch_name="P58 async_sched dev491 test",
            target_file=fake_async_sched_py_dev491,
            marker="P58_TEST_ASYNC_SCHED_DEV491",
            sub_patches=[
                # Variant A — dev259 (will soft-skip on this layout).
                TextPatch(
                    name="p58_async_sched_assignment", anchor=ASYNC_SCHED_OLD,
                    replacement=ASYNC_SCHED_NEW, required=False,
                ),
                # Variant B — dev491 (the one that must fire here).
                TextPatch(
                    name="p58_async_sched_assignment_dev491",
                    anchor=ASYNC_SCHED_OLD_DEV491,
                    replacement=ASYNC_SCHED_NEW_DEV491, required=False,
                ),
            ],
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        # Exactly the dev491 variant fired; Variant A soft-skipped.
        assert patcher.applied_sub_patches == ["p58_async_sched_assignment_dev491"]
        modified = Path(fake_async_sched_py_dev491).read_text()
        # The -1 leak assignment is gone and the counter fix is present.
        assert "request.spec_token_ids = self._spec_token_placeholders" not in modified
        assert "request.num_pending_async_spec_placeholders = self.num_spec_tokens" in modified
        # The dev491 increment shape was preserved verbatim.
        assert (
            "request.num_output_placeholders += (\n"
            "                self.num_sampled_tokens_per_step + cur_num_spec_tokens\n"
            "            )"
        ) in modified

    # test_dual_anchor_real_pristine_trees RETIRED (audit #14 full drain,
    # 2026-07-06): it byte-checked the dev259/dev491 variant anchors against
    # macOS-only stale-pin paths, empty on CI and absent on the Linux rig, so
    # it executed on NO host (permanent green-by-skip). P58 is not recorded in
    # the committed anchor_sot manifest (90/329 gap, audit #6/#21), so the
    # dual-variant byte-check cannot be migrated onto it. The variant
    # mutual-exclusion + apply + idempotency + drift contracts stay covered in
    # CI by the synthetic fake-tree tests in this class.


class TestP58SchedulerPyPatch:
    def test_all_four_anchors_present(self, fake_scheduler_py):
        content = Path(fake_scheduler_py).read_text()
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            SCHED_DRAFT_SITE_A_OLD,
            SCHED_NEW_METHOD_OLD,
            SCHED_PREEMPT_OLD,
            SCHED_SPEC_BLOCK_OLD,
        )
        assert SCHED_SPEC_BLOCK_OLD in content
        assert SCHED_NEW_METHOD_OLD in content
        assert SCHED_PREEMPT_OLD in content
        # P58 split the single DRAFT anchor into Site A and Site B in the
        # 2026-04-28 refactor (P62 layout compat). Site A is the
        # `if is_prefill_chunk:` block — that's the legacy DRAFT_OLD.
        assert SCHED_DRAFT_SITE_A_OLD in content

    def test_apply_inserts_new_method_and_gates(self, fake_scheduler_py):
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            SCHED_DRAFT_SITE_A_NEW,
            SCHED_DRAFT_SITE_A_OLD,
            SCHED_NEW_METHOD_NEW,
            SCHED_NEW_METHOD_OLD,
            SCHED_PREEMPT_NEW,
            SCHED_PREEMPT_OLD,
            SCHED_SPEC_BLOCK_NEW,
            SCHED_SPEC_BLOCK_OLD,
        )
        from sndr.kernel.text_patch import (
            TextPatch,
            TextPatcher,
            TextPatchResult,
        )
        patcher = TextPatcher(
            patch_name="P58 scheduler test",
            target_file=fake_scheduler_py,
            marker="P58_TEST_SCHED",
            sub_patches=[
                TextPatch(name="spec", anchor=SCHED_SPEC_BLOCK_OLD,
                          replacement=SCHED_SPEC_BLOCK_NEW, required=True),
                TextPatch(name="method", anchor=SCHED_NEW_METHOD_OLD,
                          replacement=SCHED_NEW_METHOD_NEW, required=True),
                TextPatch(name="preempt", anchor=SCHED_PREEMPT_OLD,
                          replacement=SCHED_PREEMPT_NEW, required=True),
                TextPatch(name="draft_a", anchor=SCHED_DRAFT_SITE_A_OLD,
                          replacement=SCHED_DRAFT_SITE_A_NEW, required=True),
            ],
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.APPLIED, failure
        modified = Path(fake_scheduler_py).read_text()
        # New method inserted
        assert "_consume_spec_decode_tokens_for_step" in modified
        # Gating clause present
        assert "request.request_id in self.prev_step_scheduled_req_ids" in modified
        # Preempt clears counter
        assert modified.count("request.num_pending_async_spec_placeholders = 0") >= 3


class TestP58Idempotency:
    def test_second_apply_is_noop(self, fake_request_py):
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            REQUEST_FIELD_NEW,
            REQUEST_FIELD_OLD,
            REQUEST_NUM_TOKENS_NEW,
            REQUEST_NUM_TOKENS_OLD,
        )
        from sndr.kernel.text_patch import (
            TextPatch,
            TextPatcher,
            TextPatchResult,
        )
        patcher = TextPatcher(
            patch_name="P58 idempotency test",
            target_file=fake_request_py,
            marker="P58_IDEMPOTENT",
            sub_patches=[
                TextPatch(name="f", anchor=REQUEST_FIELD_OLD,
                          replacement=REQUEST_FIELD_NEW, required=True),
                TextPatch(name="n", anchor=REQUEST_NUM_TOKENS_OLD,
                          replacement=REQUEST_NUM_TOKENS_NEW, required=True),
            ],
        )
        r1, _ = patcher.apply()
        r2, _ = patcher.apply()
        assert r1 == TextPatchResult.APPLIED
        assert r2 == TextPatchResult.IDEMPOTENT


class TestP58UpstreamDriftDetection:
    def test_upstream_marker_skips_patch_cleanly(self, tmp_path):
        """If `num_pending_async_spec_placeholders` is already in the file,
        we treat it as upstream-merged and skip without touching."""
        from sndr.kernel.text_patch import (
            TextPatch,
            TextPatcher,
            TextPatchResult,
        )

        post_fix_file = tmp_path / "request_post_fix.py"
        post_fix_file.write_text(
            "class Request:\n"
            "    def __init__(self):\n"
            "        self.spec_token_ids = []\n"
            "        # Already-fixed:\n"
            "        self.num_pending_async_spec_placeholders = 0\n"
        )

        patcher = TextPatcher(
            patch_name="P58 drift test",
            target_file=str(post_fix_file),
            marker="P58_DRIFT_TEST",
            sub_patches=[
                TextPatch(name="f", anchor="placeholder",
                          replacement="x", required=True),
            ],
            upstream_drift_markers=["num_pending_async_spec_placeholders"],
        )
        result, failure = patcher.apply()
        assert result == TextPatchResult.SKIPPED
        assert failure.reason == "upstream_merged"


class TestP58ApplyIsOptInOnly:
    def test_apply_skips_without_env_flag(self, monkeypatch):
        """Without GENESIS_ENABLE_P58_ASYNC_PLACEHOLDER_FIX=1, apply() returns
        skipped status — never modifies anything."""
        monkeypatch.delenv("GENESIS_ENABLE_P58_ASYNC_PLACEHOLDER_FIX", raising=False)
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            apply,
        )
        status, reason = apply()
        assert status == "skipped"
        assert "opt-in" in reason

    def test_env_flag_recognized_when_set(self, monkeypatch):
        monkeypatch.setenv("GENESIS_ENABLE_P58_ASYNC_PLACEHOLDER_FIX", "1")
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            _is_enabled,
        )
        assert _is_enabled() is True

    def test_env_flag_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("GENESIS_ENABLE_P58_ASYNC_PLACEHOLDER_FIX", raising=False)
        from sndr.engines.vllm.patches.scheduler.p58_async_scheduler_placeholder_fix import (
            _is_enabled,
        )
        assert _is_enabled() is False
