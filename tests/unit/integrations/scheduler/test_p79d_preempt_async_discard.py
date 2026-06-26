# SPDX-License-Identifier: Apache-2.0
"""TDD for Patch 79d v2 — preemption async-discard CREDIT grant.

2026-06-11 rewrite of the STALE v1 backport of vllm#38624 (surfaced by
the #45146 study, pr-sweep-50 roadmap chunk 2, W2-IMMEDIATE):

  - v1 backported the dead boolean ``discard_latest_async_tokens``
    (0 hits in pin 0.22.1rc1.dev259 — upstream migrated to the integer
    ``async_tokens_to_discard``) and zeroed ``num_output_placeholders``
    WITHOUT granting discard credit. When the in-flight async frame
    returned, the placeholder count went negative and tripped
    ``assert request.num_output_placeholders >= 0``
    (async_scheduler.py:60, byte-verified on the pristine pin).
  - v2 grants token-denominated discard credit BEFORE zeroing, on every
    preemption path, and fixes three secondary holes (see the patch
    module docstring).

These tests verify:
  1. Anchor contract: all four anchors are present exactly once in the
     PRISTINE pin tree (skips when the pristine tree is absent).
  2. Replacement hygiene: no dead-boolean residue, English-only,
     credit granted strictly BEFORE zeroing.
  3. Credit math (the heart of the rewrite) — executed END-TO-END on
     synthetic-but-compilable fakes that carry the byte-exact anchors:
     grant, reset-path wipe neutralization, rejected-draft drain,
     token-denominated frame drain, post-resume normal operation, and
     the v1 assert-crash reproduction.
  4. Idempotency + multi-file atomicity + drift-marker self-collision.

We DO NOT exercise a full vLLM stack here; behavioral validation on a
live container happens via the canonical bench/probe flow.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sndr.kernel import TextPatchResult
from sndr.kernel.multi_file import MultiFilePatchTransaction

from sndr.engines.vllm.patches.scheduler.p79d_preempt_async_discard import (
    GENESIS_P79D_MARKER,
    P79D_DRAIN_ANCHOR,
    P79D_DRAIN_REPLACEMENT,
    P79D_PREEMPT_ANCHOR,
    P79D_PREEMPT_REPLACEMENT,
    P79D_RESET_CREDIT_ANCHOR,
    P79D_RESET_CREDIT_REPLACEMENT,
    P79D_SPEC_REJECT_ANCHOR,
    P79D_SPEC_REJECT_REPLACEMENT,
    _make_async_scheduler_patcher,
    _make_scheduler_patcher,
)

PRISTINE_ROOT = Path("/private/tmp/candidate_pin_current/vllm")

ALL_REPLACEMENTS = (
    P79D_PREEMPT_REPLACEMENT,
    P79D_RESET_CREDIT_REPLACEMENT,
    P79D_SPEC_REJECT_REPLACEMENT,
    P79D_DRAIN_REPLACEMENT,
)


# ─── synthetic-but-compilable fakes carrying the byte-exact anchors ──────
#
# The fakes mirror the pristine structure closely enough that (a) every
# anchor matches byte-for-byte at its real indentation depth and (b) the
# patched source still compiles and runs, so the credit math can be
# exercised end-to-end without torch or a vLLM install.

FAKE_SCHEDULER_PY = '''\
class RequestStatus:
    RUNNING = "running"
    PREEMPTED = "preempted"


class EngineCoreEventType:
    PREEMPTED = "preempted_event"


class FakeManager:
    def free(self, request):
        pass


class FakeWaiting:
    def __init__(self):
        self.items = []

    def prepend_request(self, request):
        self.items.insert(0, request)


class Scheduler:
    def __init__(self):
        self.kv_cache_manager = FakeManager()
        self.encoder_cache_manager = FakeManager()
        self._inflight_prefills = set()
        self.waiting = FakeWaiting()
        self.running = []
        self.log_stats = False
        self.prev_step_scheduled_req_ids = set()

    def _preempt_request(self, request, timestamp):
        assert request.status == RequestStatus.RUNNING, (
            "Only running requests can be preempted"
        )
        self.kv_cache_manager.free(request)
        self.encoder_cache_manager.free(request)
        self._inflight_prefills.discard(request)
        request.status = RequestStatus.PREEMPTED
        request.num_computed_tokens = 0
        if request.spec_token_ids:
            request.spec_token_ids = []
        request.num_preemptions += 1
        if self.log_stats:
            request.record_event(EngineCoreEventType.PREEMPTED, timestamp)

        # Put the request back to the waiting queue.
        self.waiting.prepend_request(request)

    def force_preempt_all(self, timestamp, reset_running_requests=True):
        if reset_running_requests:
            while self.running:
                request = self.running.pop()
                self._preempt_request(request, timestamp)
                request.async_tokens_to_discard = request.num_output_placeholders
                request.num_output_placeholders = 0

            self.prev_step_scheduled_req_ids.clear()

    def spec_rejection_adjust(self, request, num_rejected):
        for _ in (0,):
            if num_rejected >= 0:
                if request.num_computed_tokens > 0:
                    request.num_computed_tokens -= num_rejected
                # If async scheduling, num_output_placeholders also includes
                # the scheduled spec tokens count and so is similarly adjusted.
                if request.num_output_placeholders > 0:
                    request.num_output_placeholders -= num_rejected
'''

FAKE_ASYNC_SCHEDULER_PY = '''\
class RequestStatus:
    RUNNING = "running"


class Scheduler:
    def _update_request_with_output(self, request, new_token_ids):
        stopped = False
        for output_token_id in new_token_ids:
            request.output_token_ids.append(output_token_id)
        return new_token_ids, stopped


class AsyncScheduler(Scheduler):
    def _update_request_with_output(self, request, new_token_ids):
        if request.async_tokens_to_discard > 0:
            # The request was force-preempted in reset_prefix_cache; drop one
            # stale in-flight async output frame per call until the counter
            # is drained.
            request.async_tokens_to_discard -= 1
            return [], False

        status_before_update = request.status
        new_token_ids, stopped = super()._update_request_with_output(
            request, new_token_ids
        )

        # Update the number of output placeholders.
        request.num_output_placeholders -= len(new_token_ids)
        assert request.num_output_placeholders >= 0
        return new_token_ids, stopped
'''


class FakeRequest:
    def __init__(self, num_output_placeholders=0, num_computed_tokens=0,
                 spec_token_ids=None, status="running"):
        self.num_output_placeholders = num_output_placeholders
        self.num_computed_tokens = num_computed_tokens
        self.spec_token_ids = spec_token_ids or []
        self.status = status
        self.num_preemptions = 0
        self.async_tokens_to_discard = 0
        self.output_token_ids = []


@pytest.fixture
def fake_scheduler_py(tmp_path):
    p = tmp_path / "scheduler.py"
    p.write_text(FAKE_SCHEDULER_PY)
    return str(p)


@pytest.fixture
def fake_async_scheduler_py(tmp_path):
    p = tmp_path / "async_scheduler.py"
    p.write_text(FAKE_ASYNC_SCHEDULER_PY)
    return str(p)


def _apply_both(fake_scheduler_py, fake_async_scheduler_py):
    """Apply both patchers atomically; return (sched_src, async_src)."""
    txn = MultiFilePatchTransaction(
        [
            _make_scheduler_patcher(target_file=fake_scheduler_py),
            _make_async_scheduler_patcher(target_file=fake_async_scheduler_py),
        ],
        name="P79d-test",
    )
    status, detail = txn.apply_or_skip()
    assert status == "applied", f"txn did not apply: {detail}"
    return (
        Path(fake_scheduler_py).read_text(),
        Path(fake_async_scheduler_py).read_text(),
    )


def _exec_module(src):
    ns = {}
    exec(compile(src, "<patched>", "exec"), ns)
    return ns


# ═══ 1. Anchor contract against the PRISTINE pin tree ════════════════════


@pytest.mark.skipif(
    not (PRISTINE_ROOT / "v1/core/sched/scheduler.py").is_file(),
    reason="pristine candidate pin tree not present on this machine",
)
def test_pristine_anchors_present_exactly_once():
    sched = (PRISTINE_ROOT / "v1/core/sched/scheduler.py").read_text()
    async_sched = (PRISTINE_ROOT / "v1/core/sched/async_scheduler.py").read_text()
    assert sched.count(P79D_PREEMPT_ANCHOR) == 1
    assert sched.count(P79D_RESET_CREDIT_ANCHOR) == 1
    assert sched.count(P79D_SPEC_REJECT_ANCHOR) == 1
    assert async_sched.count(P79D_DRAIN_ANCHOR) == 1


@pytest.mark.skipif(
    not (PRISTINE_ROOT / "v1/core/sched/scheduler.py").is_file(),
    reason="pristine candidate pin tree not present on this machine",
)
def test_pristine_staleness_facts_still_hold():
    """The staleness facts that triggered this rewrite (roadmap chunk 2).

    If either fact changes on a future pin, the rewrite needs re-study.
    """
    sched = (PRISTINE_ROOT / "v1/core/sched/scheduler.py").read_text()
    async_sched = (PRISTINE_ROOT / "v1/core/sched/async_scheduler.py").read_text()
    # The v1 boolean is dead upstream.
    assert "discard_latest_async_tokens" not in sched
    assert "discard_latest_async_tokens" not in async_sched
    # The assert that v1 would have tripped is still live.
    assert "assert request.num_output_placeholders >= 0" in async_sched


# ═══ 2. Replacement hygiene ═══════════════════════════════════════════════


def test_no_dead_boolean_in_replacements():
    for repl in ALL_REPLACEMENTS:
        assert "discard_latest_async_tokens" not in repl


def test_credit_granted_strictly_before_zeroing():
    grant = "request.async_tokens_to_discard += request.num_output_placeholders"
    zero = "request.num_output_placeholders = 0"
    for repl in (P79D_PREEMPT_REPLACEMENT, P79D_RESET_CREDIT_REPLACEMENT):
        assert grant in repl
        assert zero in repl
        assert repl.index(grant) < repl.index(zero)


def test_reset_credit_replacement_drops_plain_assignment():
    """The pristine '=' would wipe the credit granted by the patched
    _preempt_request — the replacement must not keep it."""
    assert (
        "request.async_tokens_to_discard = request.num_output_placeholders"
        not in P79D_RESET_CREDIT_REPLACEMENT
    )


def test_drift_markers_have_no_self_collision():
    """PN369 false-skip class: a drift marker must never be a substring
    of the patch's own emitted text, unless it uses the defended
    '[Genesis' prefix (mirrors tools/lint_drift_markers.py)."""
    for patcher in (
        _make_scheduler_patcher(target_file="/nonexistent"),
        _make_async_scheduler_patcher(target_file="/nonexistent"),
    ):
        marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            assert dm not in marker_line
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement


# ═══ 3. Credit math — end-to-end on patched executable fakes ═════════════


def test_v1_design_reproduces_the_assert_crash(fake_async_scheduler_py):
    """Staleness history: v1 zeroed placeholders WITHOUT credit. The
    stale frame's return then drives the placeholder count negative and
    trips the assert (async_scheduler.py:60 on the pristine pin). This
    reproduces the crash on the UNPATCHED drain — the contract v2 must
    fix."""
    ns = _exec_module(Path(fake_async_scheduler_py).read_text())
    sched = ns["AsyncScheduler"]()
    req = FakeRequest(num_output_placeholders=0)  # v1: zeroed, no credit
    req.async_tokens_to_discard = 0
    with pytest.raises(AssertionError):
        sched._update_request_with_output(req, [101])


def test_credit_math_standard_preempt_mtp_k3(
    fake_scheduler_py, fake_async_scheduler_py
):
    """Standard preemption with MTP K=3 and one frame in flight.

    Placeholders at preempt = 1 + 3 = 4 (token-denominated). The stale
    frame returns with 2 rejected drafts and 2 accepted tokens:
    rejected drafts drain 2 credits, the frame drain consumes the other
    2 — credit lands on EXACTLY 0 with no token appended and no assert.
    """
    sched_src, async_src = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    ans = _exec_module(async_src)
    scheduler = sns["Scheduler"]()
    async_scheduler = ans["AsyncScheduler"]()

    req = FakeRequest(num_output_placeholders=4, num_computed_tokens=100,
                      spec_token_ids=[7, 8, 9])
    scheduler._preempt_request(req, 0.0)

    # Grant happened BEFORE zeroing.
    assert req.async_tokens_to_discard == 4
    assert req.num_output_placeholders == 0
    assert req.num_computed_tokens == 0
    assert req.status == sns["RequestStatus"].PREEMPTED

    # Stale frame returns: 3 drafts scheduled, 1 accepted -> 2 rejected.
    scheduler.spec_rejection_adjust(req, num_rejected=2)
    assert req.async_tokens_to_discard == 2
    assert req.num_output_placeholders == 0  # untouched (stale path)
    assert req.num_computed_tokens == 0      # untouched (stale path)

    # Frame drain: 2 accepted tokens consume the remaining 2 credits.
    out, stopped = async_scheduler._update_request_with_output(req, [101, 102])
    assert (out, stopped) == ([], False)
    assert req.async_tokens_to_discard == 0
    assert req.output_token_ids == []  # stale tokens dropped, not appended


def test_credit_math_no_spec_single_frame(
    fake_scheduler_py, fake_async_scheduler_py
):
    """Vanilla async (no spec): 1 placeholder -> 1 credit -> 1-token
    frame drains it exactly."""
    sched_src, async_src = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    ans = _exec_module(async_src)
    scheduler = sns["Scheduler"]()
    async_scheduler = ans["AsyncScheduler"]()

    req = FakeRequest(num_output_placeholders=1, num_computed_tokens=50)
    scheduler._preempt_request(req, 0.0)
    assert req.async_tokens_to_discard == 1

    out, stopped = async_scheduler._update_request_with_output(req, [55])
    assert (out, stopped) == ([], False)
    assert req.async_tokens_to_discard == 0
    assert req.output_token_ids == []


def test_credit_math_post_resume_frames_flow_normally(
    fake_scheduler_py, fake_async_scheduler_py
):
    """Once the credit is drained, post-resume frames append normally
    and the placeholder assert holds."""
    sched_src, async_src = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    ans = _exec_module(async_src)
    scheduler = sns["Scheduler"]()
    async_scheduler = ans["AsyncScheduler"]()

    req = FakeRequest(num_output_placeholders=4, num_computed_tokens=100,
                      spec_token_ids=[7, 8, 9])
    scheduler._preempt_request(req, 0.0)
    async_scheduler._update_request_with_output(req, [101, 102, 103, 104])
    assert req.async_tokens_to_discard == 0

    # Resume: a new schedule step grants fresh placeholders.
    req.status = sns["RequestStatus"].RUNNING
    req.num_output_placeholders = 4
    out, stopped = async_scheduler._update_request_with_output(
        req, [201, 202, 203, 204]
    )
    assert out == [201, 202, 203, 204]
    assert stopped is False
    assert req.output_token_ids == [201, 202, 203, 204]
    assert req.num_output_placeholders == 0  # assert >= 0 held


def test_credit_math_upstream_frame_drain_would_under_drain(
    fake_scheduler_py, fake_async_scheduler_py
):
    """Contrast test documenting WHY the drain must be token-denominated:
    with upstream's 1-per-frame decrement, an MTP K=3 grant of 4 leaves
    3 leftover credits after the single stale frame — which would then
    silently swallow 3 legitimate post-resume frames. The patched drain
    must leave exactly 0."""
    sched_src, async_src = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    ans = _exec_module(async_src)
    scheduler = sns["Scheduler"]()
    async_scheduler = ans["AsyncScheduler"]()

    req = FakeRequest(num_output_placeholders=4, spec_token_ids=[7, 8, 9])
    scheduler._preempt_request(req, 0.0)
    assert req.async_tokens_to_discard == 4

    # Stale frame: all 3 drafts accepted -> 4 tokens, 0 rejected.
    out, stopped = async_scheduler._update_request_with_output(
        req, [101, 102, 103, 104]
    )
    assert (out, stopped) == ([], False)
    # Upstream's `-= 1` would leave 3 here. Token-denominated leaves 0.
    assert req.async_tokens_to_discard == 0


def test_credit_math_reset_prefix_cache_wipe_neutralized(
    fake_scheduler_py, fake_async_scheduler_py
):
    """The pristine reset_prefix_cache loop assigns credit with '=' AFTER
    calling _preempt_request. With the patched _preempt_request having
    already zeroed the placeholders, that '=' would WIPE the credit to 0
    — the patched loop must use '+=' and keep it."""
    sched_src, _ = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    scheduler = sns["Scheduler"]()

    req = FakeRequest(num_output_placeholders=4, num_computed_tokens=100,
                      spec_token_ids=[7, 8, 9])
    scheduler.running.append(req)
    scheduler.force_preempt_all(0.0)

    assert req.async_tokens_to_discard == 4  # NOT wiped to 0
    assert req.num_output_placeholders == 0


def test_credit_math_repeat_preemption_accumulates(
    fake_scheduler_py, fake_async_scheduler_py
):
    """'+=' semantics: debt from an earlier preemption that has not
    drained yet must survive a second preemption (a plain '=' would
    overwrite it)."""
    sched_src, _ = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    scheduler = sns["Scheduler"]()

    req = FakeRequest(num_output_placeholders=3, num_computed_tokens=10)
    req.async_tokens_to_discard = 2  # leftover from an earlier preemption
    scheduler._preempt_request(req, 0.0)
    assert req.async_tokens_to_discard == 5


def test_credit_math_live_frame_rejection_path_unchanged(
    fake_scheduler_py, fake_async_scheduler_py
):
    """With NO credit outstanding, the rejection adjustment must behave
    exactly like pristine (live counters absorb the rejections)."""
    sched_src, _ = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    sns = _exec_module(sched_src)
    scheduler = sns["Scheduler"]()

    req = FakeRequest(num_output_placeholders=4, num_computed_tokens=100)
    scheduler.spec_rejection_adjust(req, num_rejected=2)
    assert req.num_computed_tokens == 98
    assert req.num_output_placeholders == 2
    assert req.async_tokens_to_discard == 0


def test_credit_math_drain_never_goes_negative(
    fake_scheduler_py, fake_async_scheduler_py
):
    """Defensive clamp: a frame carrying more tokens than the remaining
    credit must clamp to 0, never negative (a negative credit would be
    invisible to the `> 0` gates and mask the accounting bug)."""
    _, async_src = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    ans = _exec_module(async_src)
    async_scheduler = ans["AsyncScheduler"]()

    req = FakeRequest(num_output_placeholders=0)
    req.async_tokens_to_discard = 1
    out, stopped = async_scheduler._update_request_with_output(req, [1, 2, 3])
    assert (out, stopped) == ([], False)
    assert req.async_tokens_to_discard == 0


# ═══ 4. Idempotency / atomicity ═══════════════════════════════════════════


def test_idempotent_second_apply(fake_scheduler_py, fake_async_scheduler_py):
    sched_src, async_src = _apply_both(fake_scheduler_py, fake_async_scheduler_py)
    assert GENESIS_P79D_MARKER in sched_src
    assert GENESIS_P79D_MARKER in async_src

    for make, target in (
        (_make_scheduler_patcher, fake_scheduler_py),
        (_make_async_scheduler_patcher, fake_async_scheduler_py),
    ):
        patcher = make(target_file=target)
        result, failure = patcher.apply()
        assert result == TextPatchResult.IDEMPOTENT, failure

    assert Path(fake_scheduler_py).read_text() == sched_src
    assert Path(fake_async_scheduler_py).read_text() == async_src


def test_atomic_skip_when_one_anchor_missing(
    fake_scheduler_py, fake_async_scheduler_py
):
    """If the async drain anchor is gone (e.g. upstream rewrote the
    drain), NEITHER file may be modified — a grant without the
    token-denominated drain would under-drain under MTP."""
    broken = FAKE_ASYNC_SCHEDULER_PY.replace(
        "request.async_tokens_to_discard -= 1",
        "request.async_tokens_to_discard -= 1  # moved",
    )
    Path(fake_async_scheduler_py).write_text(broken)
    before_sched = Path(fake_scheduler_py).read_text()

    txn = MultiFilePatchTransaction(
        [
            _make_scheduler_patcher(target_file=fake_scheduler_py),
            _make_async_scheduler_patcher(target_file=fake_async_scheduler_py),
        ],
        name="P79d-test",
    )
    status, detail = txn.apply_or_skip()
    assert status == "skipped", detail
    assert Path(fake_scheduler_py).read_text() == before_sched
    assert Path(fake_async_scheduler_py).read_text() == broken
