# SPDX-License-Identifier: Apache-2.0
"""PN204 — GDN dual-stream input projection overlap (port of vllm PR #42301).

(Renamed from PN202 to avoid collision with the existing PN202 entry
"per-layer KV split" in the dispatcher registry.)

Background
----------
`GatedDeltaNetAttention.forward_cuda` issues two independent GEMMs on the
same `hidden_states` tensor back-to-back:

    mixed_qkvz, _ = self.in_proj_qkvz(hidden_states)
    ba,         _ = self.in_proj_ba  (hidden_states)

They share an input but produce disjoint outputs; their kernels can run
concurrently on separate CUDA streams. vllm PR #42301 measures -2.9%
TPOT at qps=0.5 on Qwen3.5-35B-A3B with this single change.

History on this codebase
------------------------
P7 (`p7_gdn_dual_stream`) attempted the same optimization via a custom
`DualStreamDispatcher.maybe_parallel` helper. It was deferred because
raw `torch.cuda.Stream` constructions are not SymPy-graphable inside
`torch.compile(fullgraph=True)` — the v1 piecewise-cudagraph capture path
breaks.

Upstream PR #42301 sidesteps the dynamo issue by routing through the new
`vllm.utils.multi_stream_utils.maybe_execute_in_parallel` helper, which
is already present in our pinned nightly dcacdf9a.

Lazy init contract
------------------
Naive port (creating `torch.cuda.Stream()` + `torch.cuda.Event()` in
`__init__`) crashed in our worker with:
    RuntimeError: expected event to be a torch.Event object

The exact root cause was not reproducible from a minimal repro, but
deferring stream/event creation to the FIRST forward call (lazy init)
avoids it — by the time the model has done one forward pass the worker's
CUDA context, dynamo guards and compilation state are all settled. The
extra overhead is a single `getattr is None` check per forward thereafter
(~1 ns) and one one-time stream/event construction per layer.

Composes with PN50, PN54, PN59. Replaces retired P7. Auto-SKIPs when
upstream #42301 lands (drift marker `_in_proj_aux_stream`).

Env gate: `GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ=1` (default OFF).

Credit
------
- Upstream change being ported: vllm-project/vllm#42301, opened by the
  vLLM team (file `vllm/utils/multi_stream_utils.py` + the GDN edits in
  `vllm/model_executor/layers/mamba/gdn_linear_attn.py`).
- Genesis text-patch backport, lazy event-init contract, drift markers
  and conflict declaration: Sandermage / Sander Barzov Aleksandr,
  Odessa.
"""
from __future__ import annotations

import logging
import os

from vllm.sndr_core.detection.guards import resolve_vllm_file, vllm_install_root
from vllm.sndr_core.core import TextPatch, TextPatcher, result_to_wiring_status

log = logging.getLogger("genesis.wiring.pn204_dual_stream_inproj")

GENESIS_PN204_MARKER = "Genesis PN204 dual-stream input projection (port of vllm#42301)"


def _enabled() -> bool:
    return os.environ.get(
        "GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ", "0",
    ).strip().lower() in ("1", "true", "yes", "on")


# Single text-patch on the `forward_cuda` Part 1. We do not modify
# `__init__` — instead the stream/events are created lazily inside the
# forward path on the first call (and cached on `self`). This is more
# robust against early-init CUDA context issues we observed when
# creating stream/events directly in `__init__`.
PN204_FWD_OLD = (
    "        # ============================================================\n"
    "        # Part 1: Input Projection\n"
    "        # ============================================================\n"
    "        mixed_qkvz, _ = self.in_proj_qkvz(hidden_states)\n"
    "        ba, _ = self.in_proj_ba(hidden_states)\n"
)
PN204_FWD_NEW = (
    "        # ============================================================\n"
    "        # Part 1: Input Projection\n"
    "        # ============================================================\n"
    "        # [Genesis PN204 port of vllm#42301] Overlap in_proj_qkvz and\n"
    "        # in_proj_ba on independent CUDA streams. Lazy init of stream\n"
    "        # and events on first forward call to avoid early-init CUDA\n"
    "        # context issues observed in worker bootstrap.\n"
    "        import os as _g_pn204_os\n"
    "        if _g_pn204_os.environ.get(\n"
    "            'GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ', '0'\n"
    "        ).strip().lower() in ('1', 'true', 'yes', 'on'):\n"
    "            if not hasattr(self, '_g_pn204_aux_stream'):\n"
    "                try:\n"
    "                    self._g_pn204_aux_stream = torch.cuda.Stream()\n"
    "                    self._g_pn204_events = (\n"
    "                        torch.cuda.Event(), torch.cuda.Event(),\n"
    "                    )\n"
    "                except Exception:\n"
    "                    self._g_pn204_aux_stream = None\n"
    "                    self._g_pn204_events = (None, None)\n"
    "            if self._g_pn204_aux_stream is not None:\n"
    "                from vllm.utils.multi_stream_utils import (\n"
    "                    maybe_execute_in_parallel as _g_pn204_parallel,\n"
    "                )\n"
    "                try:\n"
    "                    (mixed_qkvz, _), (ba, _) = _g_pn204_parallel(\n"
    "                        lambda: self.in_proj_qkvz(hidden_states),\n"
    "                        lambda: self.in_proj_ba(hidden_states),\n"
    "                        self._g_pn204_events[0],\n"
    "                        self._g_pn204_events[1],\n"
    "                        self._g_pn204_aux_stream,\n"
    "                    )\n"
    "                except Exception:\n"
    "                    # Permanently disable for this layer after a runtime\n"
    "                    # failure; fall through to serial for this and all\n"
    "                    # future forwards.\n"
    "                    self._g_pn204_aux_stream = None\n"
    "                    mixed_qkvz, _ = self.in_proj_qkvz(hidden_states)\n"
    "                    ba, _ = self.in_proj_ba(hidden_states)\n"
    "            else:\n"
    "                mixed_qkvz, _ = self.in_proj_qkvz(hidden_states)\n"
    "                ba, _ = self.in_proj_ba(hidden_states)\n"
    "        else:\n"
    "            mixed_qkvz, _ = self.in_proj_qkvz(hidden_states)\n"
    "            ba, _ = self.in_proj_ba(hidden_states)\n"
)


def _make_patcher() -> TextPatcher | None:
    if not _enabled():
        return None
    target = resolve_vllm_file(
        "model_executor/layers/mamba/gdn_linear_attn.py"
    )
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN204 GDN dual-stream input projection (port of vllm#42301)"
        ),
        target_file=str(target),
        marker=GENESIS_PN204_MARKER,
        sub_patches=[
            TextPatch(
                name="pn204_forward_parallel_proj",
                anchor=PN204_FWD_OLD,
                replacement=PN204_FWD_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "_in_proj_aux_stream",
            "_in_proj_events",
            "maybe_execute_in_parallel(",
            "_g_pn204_aux_stream",
        ],
    )


def apply() -> tuple[str, str]:
    if not _enabled():
        return (
            "skipped",
            "PN204 disabled (set GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ=1)",
        )
    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"
    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "gdn_linear_attn.py not resolvable"
    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"
    result, failure = patcher.apply()
    return result_to_wiring_status(
        result, failure,
        applied_message=(
            "PN204 applied: GDN in_proj_qkvz/in_proj_ba overlapped on "
            "aux CUDA stream via vllm.utils.multi_stream_utils."
            "maybe_execute_in_parallel — lazy event init avoids the "
            "naive-port crash. -2.9% TPOT per vllm PR #42301."
        ),
        patch_name="PN204 GDN dual-stream input projection",
    )
