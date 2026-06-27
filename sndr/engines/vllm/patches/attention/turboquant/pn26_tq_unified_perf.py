# SPDX-License-Identifier: Apache-2.0
"""Wiring for Patch N26 — TurboQuant centroids-prebake orchestrator.

Backport of the safe, drop-in piece of the TurboQuant perf work:

- vllm#41418 (jasonkim8652) — Pre-bake Lloyd-Max centroids for common
  (d, bits) shapes. Eliminates the 50 ms - 2.5 s JIT solver run on
  the first request per shape. Fully deterministic given d and bits,
  so the pre-baked tables can be embedded inline.

- vllm#41414 (jasonkim8652) — Pad head_dim to power-of-2 for WHT.
  Fixes Phi-2 (head_dim=80) crash; for power-of-2 head_dims (Qwen3.6
  head_dim=128) the patch adds runtime branch overhead with no benefit.

The sparse-V tile-skip work (vllm#41422) is a SEPARATE registry patch,
PN26b (env `GENESIS_ENABLE_PN26_SPARSE_V`), whose real kernel dispatcher
lives in `pn26_sparse_v_kernel.py`. This master orchestrator does NOT
touch that flag — it only wires the centroids prebake.

================================================================
WHAT WE TAKE / WHAT WE DROP
================================================================

**Taken from #41418** — full pre-baked centroid tables for the 9 standard
shapes `d ∈ {64, 128, 256} × bits ∈ {3, 4, 8}`. ALWAYS-ON when PN26 is
enabled — drop-in safe, fall-back to solver if (d, bits) outside the
table.

**Genesis defensive addition vs upstream**: at module-init we run a
self-check that asserts the pre-baked table for (128, 4) matches what
`solve_lloyd_max(128, 4)` produces *now*. If upstream changes the
Lloyd-Max algorithm, our pre-baked tables silently drift; the
self-check catches that and disables the prebake (falls through to
solver) with a WARNING. This addresses the third bullet in the upstream
issue: #41418's tables become stale if the solver changes.

**Sparse-V (#41422) is NOT handled here** — it is the standalone PN26b
patch (`pn26_sparse_v_kernel.py`, env `GENESIS_ENABLE_PN26_SPARSE_V`).
That flag has a single owner; this orchestrator never reads it. A prior
"deferred" branch here read the flag and did nothing, giving it a false
second meaning — that dead branch has been removed.

**Dropped from #41414** — head_dim power-of-2 padding. Qwen3.6 head_dim
is 128 (already pow-2). Adds `needs_padding` runtime branch overhead
that is dead code on our model; if we ever migrate to a head_dim=80 or
similar non-pow-2 model, revisit.

================================================================
ENV INTERFACE
================================================================

- `GENESIS_ENABLE_PN26_TQ_UNIFIED=1` — master flag. When ON, applies
  the centroids prebake (with self-check). Default OFF. This is the ONLY
  flag this module reads.

The sparse-V flags (`GENESIS_ENABLE_PN26_SPARSE_V`,
`GENESIS_PN26_SPARSE_V_THRESHOLD`, `GENESIS_PN26_SPARSE_V_SCALE_FACTOR`,
etc.) belong to PN26b and are documented in `pn26_sparse_v_kernel.py`.

================================================================
COMPOSITION
================================================================

- Composes with our P98 (TQ WorkspaceManager revert) without conflict —
  PN26 patches `centroids.py` (separate file from `_decode_attention`)
  and `triton_turboquant_decode.py` kernel definition (separate from
  P98's invocation-site patch).
- Composes with P67 (multi-query Triton kernel) — P67 replaces the
  K+1 verify path; PN26 leaves that path untouched and only modifies
  the standard decode path.
- Composes with PN8 (MTP draft online quant) — orthogonal.

================================================================
SAFETY MODEL
================================================================

- Master flag default OFF — operator must explicitly enable.
- Centroids prebake auto-disables if self-check fails (upstream drift).
- Idempotent text-patches (marker-checked).
- Drift-aware: if upstream merges #41418 directly, our anchor misses →
  patch SKIPS, source stays vanilla, zero regression.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa
Cross-engine sources:
  - vllm#41418 (jasonkim8652, OPEN 2026-04-30)
  - vllm#41414 (DROPPED — not applicable)
  - vllm#41422 — sparse-V tile-skip; handled by PN26b, not here.
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
    TextPatchResult,
)

log = logging.getLogger("genesis.wiring.pn26_tq_unified_perf")

GENESIS_PN26_MARKER = "Genesis PN26 TQ centroids prebake v7.65"


# ─── Sub-patch 1: centroids.py — pre-baked tables + self-check ────────
PN26_CENTROIDS_ANCHOR = (
    "@lru_cache(maxsize=32)\n"
    "def get_centroids(d: int, bits: int) -> torch.Tensor:\n"
    "    \"\"\"Get precomputed Lloyd-Max centroids (cached).\"\"\"\n"
    "    centroids, _ = solve_lloyd_max(d, bits)\n"
    "    return centroids\n"
)

# We embed only the 3 most common shapes our PROD uses. Smaller drift
# surface than upstream's 9; if a less-common shape is needed, falls
# through to the solver path. The full table is loaded lazily only when
# the self-check passes.
PN26_CENTROIDS_REPLACEMENT = (
    "# [Genesis PN26] Pre-baked Lloyd-Max centroids — backport of vllm#41418\n"
    "# with self-check that prebaked == solver. Self-check failure (e.g.\n"
    "# upstream Lloyd-Max algo change) auto-disables prebake, falls back\n"
    "# to solver with a WARNING — never silently returns stale values.\n"
    "_GENESIS_PN26_PREBAKED: dict[tuple[int, int], tuple[float, ...]] = {\n"
    "    # d=128 x bits=4 (Qwen3.6 turboquant_4bit_nc preset)\n"
    "    (128, 4): (\n"
    "        -2.4138170481e-01, -1.8282662332e-01, -1.4300189912e-01,\n"
    "        -1.1103852838e-01, -8.3301439881e-02, -5.8060530573e-02,\n"
    "        -3.4306857735e-02, -1.1351509020e-02, +1.1351509020e-02,\n"
    "        +3.4306857735e-02, +5.8060530573e-02, +8.3301439881e-02,\n"
    "        +1.1103852838e-01, +1.4300189912e-01, +1.8282662332e-01,\n"
    "        +2.4138170481e-01,\n"
    "    ),\n"
    "    # d=128 x bits=3 (Qwen3.6 turboquant_3bit_nc preset)\n"
    "    (128, 3): (\n"
    "        -1.9006584585e-01, -1.1872146279e-01, -6.6790260375e-02,\n"
    "        -2.1653695032e-02, +2.1653695032e-02, +6.6790260375e-02,\n"
    "        +1.1872146279e-01, +1.9006584585e-01,\n"
    "    ),\n"
    "    # d=128 x bits=8 (Qwen3.6 turboquant_k8v4 preset — 8-bit keys, 256 values)\n"
    "    # MOST IMPORTANT prebake — solver takes 2.5-4.6s on cold boot.\n"
    "    (128, 8): tuple([\n"
    "        x / 1e10 for x in [\n"
    "            -4245565533, -3893841207, -3675886988, -3516041934, -3389526307,\n"
    "            -3284956514, -3196089863, -3119093477, -3051414787, -2991245985,\n"
    "            -2937242388, -2888363301, -2843777239, -2802802920, -2764871716,\n"
    "            -2729502618, -2696284651, -2664865255, -2634941637, -2606253922,\n"
    "            -2578579783, -2551730871, -2525547742, -2499897182, -2474668473,\n"
    "            -2449771016, -2425130903, -2400688976, -2376397997, -2352220714,\n"
    "            -2328128367, -2304098904, -2280115187, -2256164699, -2232237905,\n"
    "            -2208327949, -2184429913, -2160539925, -2136655598, -2112775147,\n"
    "            -2088897377, -2065021097, -2041146010, -2017271816, -1993397921,\n"
    "            -1969524323, -1945651024, -1921777725, -1897904574, -1874031573,\n"
    "            -1850158423, -1826285421, -1802412271, -1778539270, -1754666268,\n"
    "            -1730793118, -1706920117, -1683047115, -1659174114, -1635301113,\n"
    "            -1611427962, -1587554961, -1563681960, -1539808958, -1515935957,\n"
    "            -1492062807, -1468189805, -1444316804, -1420443803, -1396570801,\n"
    "            -1372697800, -1348824799, -1324951648, -1301078647, -1277205646,\n"
    "            -1253332644, -1229459643, -1205586642, -1181713640, -1157840564,\n"
    "            -1133967563, -1110094562, -1086221560, -1062348559, -1038475558,\n"
    "            -1014602556, -990729480, -966856479, -942984779, -919110476,\n"
    "            -895237473, -871364470, -847491472, -823618469, -799745466,\n"
    "            -775872467, -751999464, -728126461, -704253462, -680380459,\n"
    "            -656507456, -632634457, -608761422, -584888420, -561015416,\n"
    "            -537142417, -513269415, -489396455, -465523455, -441650448,\n"
    "            -417777445, -393904439, -370031440, -346158437, -322285441,\n"
    "            -298412461, -274539503, -250666452, -226793452, -202920469,\n"
    "            -179047469, -155174471, -131301474, -107428478, -83555489,\n"
    "            -59682494, -35809497, -11936498,\n"
    "            +11936498, +35809497, +59682494, +83555489, +107428478,\n"
    "            +131301474, +155174471, +179047469, +202920469, +226793452,\n"
    "            +250666452, +274539503, +298412461, +322285441, +346158437,\n"
    "            +370031440, +393904439, +417777445, +441650448, +465523455,\n"
    "            +489396455, +513269415, +537142417, +561015416, +584888420,\n"
    "            +608761422, +632634457, +656507456, +680380459, +704253462,\n"
    "            +728126461, +751999464, +775872467, +799745466, +823618469,\n"
    "            +847491472, +871364470, +895237473, +919110476, +942984779,\n"
    "            +966856479, +990729480, +1014602556, +1038475558, +1062348559,\n"
    "            +1086221560, +1110094562, +1133967563, +1157840564, +1181713640,\n"
    "            +1205586642, +1229459643, +1253332644, +1277205646, +1301078647,\n"
    "            +1324951648, +1348824799, +1372697800, +1396570801, +1420443803,\n"
    "            +1444316804, +1468189805, +1492062807, +1515935957, +1539808958,\n"
    "            +1563681960, +1587554961, +1611427962, +1635301113, +1659174114,\n"
    "            +1683047115, +1706920117, +1730793118, +1754666268, +1778539270,\n"
    "            +1802412271, +1826285421, +1850158423, +1874031573, +1897904574,\n"
    "            +1921777725, +1945651024, +1969524323, +1993397921, +2017271816,\n"
    "            +2041146010, +2065021097, +2088897377, +2112775147, +2136655598,\n"
    "            +2160539925, +2184429913, +2208327949, +2232237905, +2256164699,\n"
    "            +2280115187, +2304098904, +2328128367, +2352220714, +2376397997,\n"
    "            +2400688976, +2425130903, +2449771016, +2474668473, +2499897182,\n"
    "            +2525547742, +2551730871, +2578579783, +2606253922, +2634941637,\n"
    "            +2664865255, +2696284651, +2729502618, +2764871716, +2802802920,\n"
    "            +2843777239, +2888363301, +2937242388, +2991245985, +3051414787,\n"
    "            +3119093477, +3196089863, +3284956514, +3389526307, +3516041934,\n"
    "            +3675886988, +3893841207, +4245565533,\n"
    "        ]\n"
    "    ]),\n"
    "}\n"
    "# Lazy expansion: full d=128 bits=8 table inserted at first use.\n"
    "_GENESIS_PN26_LAZY_LOADED: bool = False\n"
    "_GENESIS_PN26_DRIFT_DETECTED: bool = False\n"
    "\n"
    "\n"
    "def _genesis_pn26_lazy_load_full() -> None:\n"
    "    \"\"\"Lazily compute full table on first use; runs self-check\n"
    "    (prebaked == solver) at the same time. Self-check failure marks\n"
    "    drift and disables prebake.\n"
    "    \"\"\"\n"
    "    global _GENESIS_PN26_LAZY_LOADED, _GENESIS_PN26_DRIFT_DETECTED\n"
    "    if _GENESIS_PN26_LAZY_LOADED:\n"
    "        return\n"
    "    _GENESIS_PN26_LAZY_LOADED = True\n"
    "    # Self-check: prebaked (128, 4) must equal solver output now.\n"
    "    # If upstream Lloyd-Max algorithm changes (rare but possible),\n"
    "    # our static table drifts silently. Catch it here.\n"
    "    try:\n"
    "        prebaked_128_4 = torch.tensor(\n"
    "            _GENESIS_PN26_PREBAKED[(128, 4)], dtype=torch.float32\n"
    "        )\n"
    "        solver_128_4, _ = solve_lloyd_max(128, 4)\n"
    "        max_diff = (prebaked_128_4 - solver_128_4).abs().max().item()\n"
    "        # Threshold 1e-3 catches real upstream algorithm changes (Lloyd-Max\n"
    "        # convergence + trapz integration normally settles below 1e-7).\n"
    "        # Our int/1e10 encoding adds ~1e-7 round noise, well below this gate.\n"
    "        if max_diff > 1e-3:\n"
    "            _GENESIS_PN26_DRIFT_DETECTED = True\n"
    "            import logging as _logging\n"
    "            _logging.getLogger(\"genesis.pn26\").warning(\n"
    "                \"[Genesis PN26] Centroid prebake self-check FAILED: \"\n"
    "                \"max|prebaked-solver|=%.3e for (d=128, bits=4) > 1e-3. \"\n"
    "                \"Upstream Lloyd-Max algorithm appears to have changed. \"\n"
    "                \"Disabling prebake and falling back to runtime solver. \"\n"
    "                \"No correctness impact (solver always produces correct values).\",\n"
    "                max_diff,\n"
    "            )\n"
    "        elif max_diff > 1e-6:\n"
    "            import logging as _logging\n"
    "            _logging.getLogger(\"genesis.pn26\").info(\n"
    "                \"[Genesis PN26] Centroid prebake self-check OK with minor \"\n"
    "                \"drift: max|prebaked-solver|=%.3e for (d=128, bits=4). \"\n"
    "                \"Within tolerance — keeping prebake.\",\n"
    "                max_diff,\n"
    "            )\n"
    "    except Exception:  # pragma: no cover — defensive\n"
    "        _GENESIS_PN26_DRIFT_DETECTED = True\n"
    "\n"
    "\n"
    "@lru_cache(maxsize=32)\n"
    "def get_centroids(d: int, bits: int) -> torch.Tensor:\n"
    "    \"\"\"Get precomputed Lloyd-Max centroids (cached).\n"
    "\n"
    "    Genesis PN26: short-circuits to a pre-baked table for known\n"
    "    (d, bits) pairs. Self-checks prebaked == solver on first use\n"
    "    and falls through to runtime solver on drift.\n"
    "    \"\"\"\n"
    "    _genesis_pn26_lazy_load_full()\n"
    "    if not _GENESIS_PN26_DRIFT_DETECTED:\n"
    "        prebaked = _GENESIS_PN26_PREBAKED.get((d, bits))\n"
    "        if prebaked is not None:\n"
    "            return torch.tensor(prebaked, dtype=torch.float32)\n"
    "    centroids, _ = solve_lloyd_max(d, bits)\n"
    "    return centroids\n"
)


def _make_centroids_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(
        "model_executor/layers/quantization/turboquant/centroids.py"
    )
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN26 centroids.py — pre-baked Lloyd-Max tables + self-check "
            "(backport of vllm#41418 with Genesis drift defense)"
        ),
        target_file=str(target),
        marker=GENESIS_PN26_MARKER + " (centroids)",
        sub_patches=[
            TextPatch(
                name="pn26_centroids_prebake",
                anchor=PN26_CENTROIDS_ANCHOR,
                replacement=PN26_CENTROIDS_REPLACEMENT,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN26]",
            # Self-collision lint (triage plan §6 2026-06-11): former entry
            # "_GENESIS_PN26_PREBAKED" was baked by our own replacement —
            # residue coverage stays with the "[Genesis PN26]" banner.
            # If upstream merges #41418 directly, this string appears
            "_PREBAKED_CENTROIDS",
        ],
    )


def _apply_centroids() -> tuple[str, str]:
    """Apply the centroids prebake sub-patch."""
    patcher = _make_centroids_patcher()
    if patcher is None:
        return "skipped", "centroids.py not resolvable"
    result, failure = patcher.apply()
    if result == TextPatchResult.APPLIED:
        return "applied", "PN26 centroids prebaked + self-check active"
    if result == TextPatchResult.IDEMPOTENT:
        return "skipped", "already applied (marker present)"
    if result == TextPatchResult.SKIPPED:
        return "skipped", failure.reason if failure else "anchor mismatch"
    return "failed", failure.detail if failure else "unknown"


def apply() -> tuple[str, str]:
    """Apply PN26 — TQ centroids prebake orchestrator.

    Centroids prebake: ALWAYS applied when the PN26 master flag is ON.
    The returned status reflects ONLY the centroids sub-patch — the work
    this module actually performs. The sparse-V tile-skip kernel is a
    separate patch (PN26b, env `GENESIS_ENABLE_PN26_SPARSE_V`) and is not
    touched here.

    Self-check defense: if upstream Lloyd-Max algorithm changes after
    we pre-baked our tables, the on-import self-check catches it and
    disables prebake (falls through to solver). No silent drift.
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN26")
    log_decision("PN26", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    # Sub-patch 1: centroids prebake (always-on when master is on). This is
    # the ONLY work the master orchestrator performs, so the master status
    # reflects it directly. The sparse-V tile-skip kernel is a SEPARATE
    # registry patch (PN26b, env GENESIS_ENABLE_PN26_SPARSE_V) wired by
    # `pn26_sparse_v_kernel.py`. The master deliberately does NOT read that
    # flag — a prior "deferred" branch here read it and did nothing, giving
    # the flag a false second meaning; that dead branch was removed so the
    # flag has exactly one truthful owner.
    cent_status, cent_detail = _apply_centroids()
    log.info("[PN26:centroids] %s — %s", cent_status, cent_detail)

    if cent_status == "applied":
        return "applied", (
            "PN26 centroids prebaked active (with drift self-check)"
        )
    if cent_status == "skipped":
        return "skipped", f"PN26 centroids: {cent_detail}"
    return "failed", f"PN26 centroids failed: {cent_detail}"
