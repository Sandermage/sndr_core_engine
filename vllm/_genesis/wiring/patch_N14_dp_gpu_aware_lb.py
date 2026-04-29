# SPDX-License-Identifier: Apache-2.0
"""Wiring for Patch N14 — GPU-aware DP load balancing.

Problem
-------
vLLM's internal DP load balancer (DPLBAsyncMPClient) scores engines using
only request queue counts: `score = waiting * 4 + running`. This is blind
to actual GPU utilization — an engine chewing through a long decode at 100%
GPU gets the same score as an idle engine with one short request.

With 3+ DP instances on separate GPUs, this causes severe imbalance:
requests pile up on "low-score" engines while other GPUs sit idle.

Fix
---
Extend the stats pipeline to include per-engine GPU utilization (%):

  1. core.py:    _maybe_publish_request_counts() appends GPU util (via pynvml)
  2. coordinator.py: EngineState.request_counts becomes [waiting, running, gpu_util]
  3. core_client.py: Score = gpu_util*W1 + waiting*W2 + running*W3

Weights (W1, W2, W3) are configurable via GENESIS_DP_LB_WEIGHTS env var
(default: 10,4,1). Falls back to 2-element scoring if GPU util unavailable.

Author: Clawd
"""
from __future__ import annotations

import logging

from vllm._genesis.guards import resolve_vllm_file
from vllm._genesis.wiring.text_patch import (
    TextPatch, TextPatcher, TextPatchResult,
)

log = logging.getLogger("genesis.wiring.pN14_dp_gpu_aware_lb")

GENESIS_PN14_MARKER = "Genesis PN14 DP GPU-aware LB v1.0"

UPSTREAM_DRIFT_MARKERS = [
    # If upstream ever adds gpu_util to SchedulerStats or coordinator stats
    "gpu_util",
    "gpu_utilization",
]


# ─── Patch 0: stats.py — add gpu_util field to SchedulerStats dataclass ───

_STATS_OLD = (
    "    # These are used for internal DP load-balancing.\n"
    "    step_counter: int = 0\n"
    "    current_wave: int = 0"
)

_STATS_NEW = (
    "    # These are used for internal DP load-balancing.\n"
    "    step_counter: int = 0\n"
    "    current_wave: int = 0\n"
    "    # [Genesis PN14] GPU utilization for DP load balancing.\n"
    "    gpu_util: float = 0.0"
)


# ─── Patch 1: core.py — add GPU util to SchedulerStats ────────────────────

_CORE_OLD = (
    "    def _maybe_publish_request_counts(self):\n"
    "        if not self.publish_dp_lb_stats:\n"
    "            return\n"
    "\n"
    "        # Publish our request counts (if they've changed).\n"
    "        counts = self.scheduler.get_request_counts()\n"
    "        if counts != self.last_counts:\n"
    "            self.last_counts = counts\n"
    "            stats = SchedulerStats(\n"
    "                *counts, step_counter=self.step_counter, current_wave=self.current_wave\n"
    "            )\n"
    "            self.output_queue.put_nowait((-1, EngineCoreOutputs(scheduler_stats=stats)))"
)

_CORE_NEW = (
    "    def _maybe_publish_request_counts(self):\n"
    "        if not self.publish_dp_lb_stats:\n"
    "            return\n"
    "\n"
    "        # Publish our request counts (if they've changed).\n"
    "        counts = self.scheduler.get_request_counts()\n"
    "        if counts != self.last_counts:\n"
    "            self.last_counts = counts\n"
    "            # [Genesis PN14] Append GPU utilization for DP load balancing.\n"
    "            # Each engine core has CUDA_VISIBLE_DEVICES set to its own GPU,\n"
    "            # so pynvml device 0 is always the correct device for this engine.\n"
    "            _gpu_util = 0.0\n"
    "            try:\n"
    "                _pynvml = None\n"
    "                try:\n"
    "                    from vllm.utils.import_utils import import_pynvml\n"
    "                    _pynvml = import_pynvml()\n"
    "                except Exception:\n"
    "                    try:\n"
    "                        import pynvml as _pynvml\n"
    "                    except Exception:\n"
    "                        pass\n"
    "                if _pynvml is not None:\n"
    "                    try:\n"
    "                        _pynvml.nvmlInit()\n"
    "                        _handle = _pynvml.nvmlDeviceGetHandleByIndex(0)\n"
    "                        _util = _pynvml.nvmlDeviceGetUtilizationRates(_handle)\n"
    "                        _gpu_util = float(_util.gpu)\n"
    "                    except Exception:\n"
    "                        pass\n"
    "            except Exception:\n"
    "                pass\n"
    "            stats = SchedulerStats(\n"
    "                *counts, step_counter=self.step_counter, current_wave=self.current_wave,\n"
    "                gpu_util=_gpu_util\n"
    "            )\n"
    "            self.output_queue.put_nowait((-1, EngineCoreOutputs(scheduler_stats=stats)))"
)


# ─── Patch 2: coordinator.py — extend request_counts to 3 elements ────────

_COORD_OLD = (
    "class EngineState:\n"
    "    def __init__(self):\n"
    "        self.request_counts = [0, 0]  # [waiting, running]"
)

_COORD_NEW = (
    "class EngineState:\n"
    "    def __init__(self):\n"
    "        self.request_counts = [0, 0, 0.0]  # [waiting, running, gpu_util]  # [Genesis PN14]"
)

_COORD_STATS_OLD = (
    "                        stats[0] = scheduler_stats.num_waiting_reqs\n"
    "                        stats[1] = scheduler_stats.num_running_reqs\n"
    "                        stats_changed = True"
)

_COORD_STATS_NEW = (
    "                        stats[0] = scheduler_stats.num_waiting_reqs\n"
    "                        stats[1] = scheduler_stats.num_running_reqs\n"
    "                        # [Genesis PN14] GPU utilization for DP load balancing.\n"
    "                        if hasattr(scheduler_stats, 'gpu_util'):\n"
    "                            stats[2] = scheduler_stats.gpu_util\n"
    "                        stats_changed = True"
)


# ─── Patch 3: core_client.py — hybrid GPU-aware scoring ───────────────────

_CLIENT_SCORE_OLD = (
    "                waiting, running = current_counts[idx]\n"
    "                score = waiting * 4 + running"
)

_CLIENT_SCORE_NEW = (
    "                # [Genesis PN14] GPU-aware hybrid DP load balancing.\n"
    "                # Weights configurable via GENESIS_DP_LB_WEIGHTS=W1,W2,W3\n"
    "                # (default: 10,4,1). Falls back to waiting*4+running if\n"
    "                # gpu_util (3rd element) is not present.\n"
    "                _genesis_dp_w1, _genesis_dp_w2, _genesis_dp_w3 = 10, 4, 1\n"
    "                try:\n"
    "                    import os as _os\n"
    "                    _genesis_dp_w = _os.environ.get('GENESIS_DP_LB_WEIGHTS', '10,4,1').split(',')\n"
    "                    if len(_genesis_dp_w) == 3:\n"
    "                        _genesis_dp_w1, _genesis_dp_w2, _genesis_dp_w3 = int(_genesis_dp_w[0]), int(_genesis_dp_w[1]), int(_genesis_dp_w[2])\n"
    "                except Exception:\n"
    "                    pass\n"
    "                waiting, running = current_counts[idx][0], current_counts[idx][1]\n"
    "                if len(current_counts[idx]) >= 3:\n"
    "                    _gpu_util = current_counts[idx][2]\n"
    "                    score = _gpu_util * _genesis_dp_w1 + waiting * _genesis_dp_w2 + running * _genesis_dp_w3\n"
    "                else:\n"
    "                    score = waiting * 4 + running"
)


def _make_patcher() -> list[TextPatcher | None]:
    patchers: list[TextPatcher | None] = []

    # Patch 0: stats.py — add gpu_util field to SchedulerStats
    stats_file = resolve_vllm_file("v1/metrics/stats.py")
    if stats_file is not None:
        patchers.append(TextPatcher(
            patch_name="PN14 DP GPU-aware LB (stats.py)",
            target_file=stats_file,
            marker=GENESIS_PN14_MARKER,
            sub_patches=[
                TextPatch(
                    name="add_gpu_util_field_to_scheduler_stats",
                    anchor=_STATS_OLD,
                    replacement=_STATS_NEW,
                    required=True,
                ),
            ],
            upstream_drift_markers=UPSTREAM_DRIFT_MARKERS,
        ))

    # Patch 1: core.py
    core_file = resolve_vllm_file("v1/engine/core.py")
    if core_file is not None:
        patchers.append(TextPatcher(
            patch_name="PN14 DP GPU-aware LB (core.py)",
            target_file=core_file,
            marker=GENESIS_PN14_MARKER,
            sub_patches=[
                TextPatch(
                    name="add_gpu_util_to_stats",
                    anchor=_CORE_OLD,
                    replacement=_CORE_NEW,
                    required=True,
                ),
            ],
            upstream_drift_markers=UPSTREAM_DRIFT_MARKERS,
        ))

    # Patch 2: coordinator.py
    coord_file = resolve_vllm_file("v1/engine/coordinator.py")
    if coord_file is not None:
        patchers.append(TextPatcher(
            patch_name="PN14 DP GPU-aware LB (coordinator.py)",
            target_file=coord_file,
            marker=GENESIS_PN14_MARKER,
            sub_patches=[
                TextPatch(
                    name="extend_request_counts_to_3",
                    anchor=_COORD_OLD,
                    replacement=_COORD_NEW,
                    required=True,
                ),
                TextPatch(
                    name="extract_gpu_util_from_stats",
                    anchor=_COORD_STATS_OLD,
                    replacement=_COORD_STATS_NEW,
                    required=False,
                ),
            ],
            upstream_drift_markers=UPSTREAM_DRIFT_MARKERS,
        ))

    # Patch 3: core_client.py
    client_file = resolve_vllm_file("v1/engine/core_client.py")
    if client_file is not None:
        patchers.append(TextPatcher(
            patch_name="PN14 DP GPU-aware LB (core_client.py)",
            target_file=client_file,
            marker=GENESIS_PN14_MARKER,
            sub_patches=[
                TextPatch(
                    name="hybrid_gpu_aware_scoring",
                    anchor=_CLIENT_SCORE_OLD,
                    replacement=_CLIENT_SCORE_NEW,
                    required=True,
                ),
            ],
            upstream_drift_markers=UPSTREAM_DRIFT_MARKERS,
        ))

    return patchers


def apply() -> tuple[str, str]:
    """Apply all three sub-patches for GPU-aware DP load balancing."""
    patchers = _make_patcher()
    results: list[tuple[str, str]] = []

    for p in patchers:
        if p is None:
            continue
        status, failure = p.apply()
        if status == TextPatchResult.APPLIED:
            results.append(("applied", f"{p.patch_name} applied"))
        elif status == TextPatchResult.IDEMPOTENT:
            results.append(("applied", f"{p.patch_name} already applied"))
        elif status == TextPatchResult.SKIPPED:
            reason = failure.reason if failure else "unknown"
            results.append(("skipped", f"{p.patch_name} skipped: {reason}"))
        else:
            reason = failure.reason if failure else "unknown"
            results.append(("failed", f"{p.patch_name} failed: {reason}"))

    if not results:
        return "skipped", "no target files found (vLLM not installed or path mismatch)"

    # If any failed, report failure
    for st, msg in results:
        if st == "failed":
            return "failed", "; ".join(msg for _, msg in results)

    # If any skipped (but none failed), still apply — partial is ok
    applied = [msg for st, msg in results if st == "applied"]
    skipped = [msg for st, msg in results if st == "skipped"]

    if applied:
        reason = "; ".join(applied)
        if skipped:
            reason += " (skipped: " + "; ".join(skipped) + ")"
        return "applied", reason

    return "skipped", "; ".join(skipped)
