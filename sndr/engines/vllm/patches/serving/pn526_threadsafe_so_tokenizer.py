# SPDX-License-Identifier: Apache-2.0
"""PN526 — thread-safe StructuredOutputManager tokenizer (vllm#47509).

================================================================
UPSTREAM BUG (vllm#47509) — 'Already borrowed' RACE, LATENT ON 35B PROD
================================================================

``StructuredOutputManager.__init__`` (pristine dev748 L79-81,
byte-verified via gh api at 2dfaae752) stores the PROCESS-GLOBAL
``cached_tokenizer_from_config`` instance and hands it to concurrent
``self.executor`` threads (grammar compilation) plus the request-scoped
reasoner. HF fast tokenizers mutate shared Rust state inside ``encode``
(``set_truncation_and_padding``), so concurrent calls raise
``RuntimeError: Already borrowed``.

Reachable on our 35B PROD lane: ``reasoning_parser qwen3`` +
``GENESIS_ENABLE_P62_STRUCT_OUT_SPEC_TIMING=1`` + structured outputs
live. REAL but never observed in incident memory -> P3, opt-in flag
(default_on=False); flip on for a structured-output soak or on first
'Already borrowed' sighting in engine logs.

================================================================
THE FIX — copy, then route through a deep-copied pool
================================================================

Fix deps are IN-pin (vllm/tokenizers/hf.py: ``ThreadSafeHFTokenizerMixin``
L19 + ``maybe_make_thread_pool`` L25, re-exported by
``vllm/tokenizers/__init__`` — all byte-verified at 2dfaae752). PR
#47509 inserts after the cached_tokenizer_from_config call:

    assert self.tokenizer is not None
    self.tokenizer = copy.copy(self.tokenizer)
    maybe_make_thread_pool(self.tokenizer, max_workers + 1)

``maybe_make_thread_pool`` mutates IN PLACE (swaps ``__class__`` to
route public calls through a deep-copied tokenizer pool), so the
``copy.copy`` first is load-bearing: the in-place swap must land on the
manager's own instance, never the shared cache entry. Pool size
``max_workers + 1`` = grammar-compile threads + the reasoner.

PN526 vendors upstream-identical semantics as ONE function-local
insertion, importing ``copy``/``maybe_make_thread_pool`` under Genesis
aliases — upstream's literal rewritten import line
(``cached_tokenizer_from_config, maybe_make_thread_pool``) never
appears in our emitted text and serves as the SELF_COLLISION-safe
drift marker. Expected retire outcome (a) byte-similar when #47509
merges.

================================================================
SAFETY MODEL / SAME-FILE HYGIENE
================================================================

  * One shallow copy + one in-place wrap at engine init; zero per-step
    cost. Slow tokenizers / non-fast paths: maybe_make_thread_pool
    no-ops (upstream's own gate), behavior unchanged.
  * VERDICT CORRECTION from the triage cross-check: disjointness is
    declared (and test-pinned) against BOTH same-file patches — P62
    (grammar_bitmask / update-from-output regions) AND PN58 Sub-D
    (module-level 'logger = init_logger' anchor BEFORE the class) —
    PN58 was missed in the first pass. Anchor is inside __init__;
    grep-verified no overlap with either.
  * Anchor byte-verified count==1 in pristine dev748; drift marker
    count==0 there.
  * Full concurrency proof (the PR's transformers hammer:
    32 threads x 200 truncation-toggling encodes) is the blue/green
    container gate, not a unit test.

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Original PR: vllm#47509 (OPEN as of 2026-07-05).
"""

from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import (
    TextPatch,
    TextPatcher,
)

log = logging.getLogger("genesis.wiring.pn526_threadsafe_so_tokenizer")

GENESIS_PN526_MARKER = (
    "Genesis PN526 thread-safe StructuredOutputManager tokenizer "
    "(vendor of vllm#47509) v1"
)

# ── Sub-patch (required): copy + thread-pool wrap after tokenizer init ─
# Anchor: the unique cached_tokenizer_from_config assignment span inside
# StructuredOutputManager.__init__ (count==1 byte-verified in pristine
# dev748 2dfaae752 via gh api 2026-07-05).

PN526_TOKENIZER_OLD = (
    "            self.tokenizer = cached_tokenizer_from_config(\n"
    "                model_config=self.vllm_config.model_config\n"
    "            )\n"
)

PN526_TOKENIZER_NEW = (
    "            self.tokenizer = cached_tokenizer_from_config(\n"
    "                model_config=self.vllm_config.model_config\n"
    "            )\n"
    "            # [Genesis PN526 vendor of vllm#47509] The cached tokenizer is\n"
    "            # a single process-global instance, but grammar compilation\n"
    "            # (self.executor threads) and the request-scoped reasoner run\n"
    "            # it concurrently; HF fast tokenizers mutate shared Rust state\n"
    "            # inside encode (set_truncation_and_padding) -> RuntimeError\n"
    "            # 'Already borrowed'. Wrap a COPY in a deep-copied call pool\n"
    "            # (the wrap swaps __class__ IN PLACE, so copying first keeps\n"
    "            # the shared cache entry pristine). Pool = grammar-compile\n"
    "            # threads + the reasoner. Upstream-identical semantics;\n"
    "            # imports aliased so the upstream import line stays a\n"
    "            # collision-free drift marker.\n"
    "            import copy as _genesis_pn526_copy\n"
    "            from vllm.tokenizers import (\n"
    "                maybe_make_thread_pool as _genesis_pn526_thread_pool,\n"
    "            )\n"
    "            assert self.tokenizer is not None\n"
    "            self.tokenizer = _genesis_pn526_copy.copy(self.tokenizer)\n"
    "            _genesis_pn526_thread_pool(self.tokenizer, max_workers + 1)\n"
)

# Drift markers — #47509's rewritten import line plus its exact comment
# head (from `gh pr diff 47509`, 2026-07-05). Byte-verified absent in
# pristine dev748 (count 0). Our replacement aliases the imports and
# rewords the comment, so neither appears in our emitted text —
# SELF_COLLISION-safe (PN369).
_DRIFT_MARKERS = (
    "from vllm.tokenizers import cached_tokenizer_from_config, maybe_make_thread_pool\n",
    "# `cached_tokenizer_from_config` returns a single process-global\n",
    # Defended convention entry (our own banner).
    "[Genesis PN526",
)


def _make_patcher() -> TextPatcher | None:
    target = resolve_vllm_file("v1/structured_output/__init__.py")
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN526 v1/structured_output/__init__.py — thread-safe manager "
            "tokenizer (vendor of vllm#47509)"
        ),
        target_file=str(target),
        marker=GENESIS_PN526_MARKER,
        sub_patches=[
            TextPatch(
                name="pn526_tokenizer_copy_thread_pool",
                anchor=PN526_TOKENIZER_OLD,
                replacement=PN526_TOKENIZER_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:  # noqa: PLR0911 - dispatcher early-return cascade: distinct skip/self-retire reasons per gate
    """Apply PN526 — thread-safe StructuredOutputManager tokenizer.

    Gated through the dispatcher on
    ``GENESIS_ENABLE_PN526_THREADSAFE_SO_TOKENIZER`` (opt-in,
    default_on=False — latent race, never observed in incident memory;
    flip on for structured-output soaks or on the first 'Already
    borrowed' log line). Never raises.
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN526")
    log_decision("PN526", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patcher = _make_patcher()
    if patcher is None:
        return "skipped", "vllm/v1/structured_output/__init__.py not found"

    if not os.path.isfile(patcher.target_file):
        return "skipped", f"target disappeared: {patcher.target_file}"
    with open(patcher.target_file, encoding="utf-8") as f:
        content = f.read()
    if patcher.marker in content:
        return "skipped", f"{patcher.patch_name}: already applied (marker present)"
    for m in patcher.upstream_drift_markers:
        if m.startswith("[Genesis"):
            continue
        if m in content:
            return (
                "skipped",
                f"upstream drift marker {m!r} present — upstream PR "
                "#47509 (or equivalent fix) appears merged (upstream_merged)",
            )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001 - dispatcher contract: never raise
        return "failed", f"PN526 apply raised {e!r}"

    from sndr.kernel import TextPatchResult

    if result == TextPatchResult.FAILED:
        return "failed", f"PN526: {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.SKIPPED:
        return "skipped", f"PN526: {failure.reason if failure else 'unknown'}"
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", "PN526 already applied (idempotent)"

    return (
        "applied",
        "PN526 applied: StructuredOutputManager.__init__ now copy.copy()s "
        "the process-global cached tokenizer and routes its public calls "
        "through a deep-copied thread pool (max_workers + 1), so concurrent "
        "grammar compilation + the reasoner can no longer race the shared "
        "Rust state ('Already borrowed', vllm#47509). Shared cache entry "
        "stays unwrapped.",
    )


def is_applied() -> bool:
    """Return True iff our marker is present in the target file."""
    if vllm_install_root() is None:
        return False
    patcher = _make_patcher()
    if patcher is None:
        return False
    try:
        with open(patcher.target_file, encoding="utf-8") as f:
            return patcher.marker in f.read()
    except OSError:
        return False
