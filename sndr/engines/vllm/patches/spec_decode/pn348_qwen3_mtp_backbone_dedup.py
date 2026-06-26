# SPDX-License-Identifier: Apache-2.0
"""PN348 — vendor of OPEN PR vllm#44644 (Qwen3.5/3.6 MTP backbone dedup).

Deep-dive understanding of the upstream PR
==========================================

**Problem**: ``Qwen3_5MultiTokenPredictor.__init__`` unconditionally
allocates ``embed_tokens = VocabParallelEmbedding(vocab_size, hidden_size)``,
and ``Qwen3_5MTP.__init__`` unconditionally allocates ``lm_head`` as a fresh
``ParallelLMHead`` whenever ``tie_word_embeddings=False``. When the MTP head
is logically meant to share the target model's embedding + projection
table — as Qwen3.5/3.6 checkpoints do via the model-config flag
``mtp_use_dedicated_embeddings=False`` — the MTP backbone ends up with
its OWN copy of two ``[vocab_size, hidden_size]`` BF16 tensors that are
NEVER USED at inference (the spec-decode draft path reads embeddings
from the target model, not the MTP backbone).

**Concrete math on our PROD `Qwen3.6-35B-A3B-FP8`**:

  * ``vocab_size = 248,320``, ``hidden_size = 2,048``, BF16 storage = 2 B/elt
  * One ``[vocab, hidden] BF16`` tensor = 248,320 × 2,048 × 2 = 1.017 GiB
  * Two tensors (embed_tokens + lm_head) per worker = ~2.0 GiB
  * TP=2 sharding splits column dim → ~509 MiB per tensor per rank
  * **Duplicate dead weight per rank = ~1.0 GiB**
  * **Cluster-wide on 2× A5000 = ~2.0 GiB freed**
  * Author independently measured 0.4-1.0 GiB per worker (varies with
    vocab × hidden × dtype); our shape lands at the upper end.

**Why our PROD hits this**:

  * ``Qwen3.6-35B-A3B-FP8/config.json`` (HuggingFace Qwen team) sets
    ``text_config.mtp_use_dedicated_embeddings = False`` AND
    ``text_config.tie_word_embeddings = False``. This is the model
    author's signal "MTP should share the target's embed+lm_head".
  * Our pin (0.22.1rc1.dev259+g303916e93) PRE-DATES the fix — the
    upstream allocation branch is unconditional. Verified by reading
    live container file lines 75-78 (embed_tokens) and 380-388
    (lm_head): both unconditional.
  * The MTP backbone runs at PP=1 in our deployment (TP=2 PP=1) so
    the upstream gate ``get_pp_group().world_size == 1`` fires.

Why we VENDOR this OPEN PR (don't just wait)
============================================

  * PR is open as of 2026-06-09 (~4 days old, no maintainer review yet).
    On Genesis cadence (weekly pin bumps), waiting costs 2+ weeks.
  * The fix is structural and small (3 hunks, ~14 LOC) — low merge risk.
  * VRAM unlock is non-trivial on 2× A5000 (24 GB each, headroom is
    perpetually tight on the 35B+MTP K=3 stack).
  * 2 GiB cluster-wide opens room for: deeper KV-cache budget (more
    concurrent requests), or larger ``max_model_len``, or DFlash drafter
    (PN38) memory headroom.

Implementation strategy
=======================

Three required sub-patches on the single file ``models/qwen3_5_mtp.py``:

  * Sub-1 (embed_tokens predicate): replace the single-branch
    ``VocabParallelEmbedding`` allocation with the gated form. Anchor
    on the 4-line block immediately following ``self.num_mtp_layers = ...``.
  * Sub-2 (lm_head fallthrough): extend the ``if get_pp_group().is_last_rank:``
    branch with the share-backbone short-circuit. Anchor on the existing
    ``if config.tie_word_embeddings:`` line.
  * Sub-3 (weight loader skip): in ``remap_weight_names``, skip
    embed_tokens/lm_head when shared so AutoWeightsLoader doesn't
    duplicate-load them onto the MTP backbone. Anchor on the existing
    ``elif any(key in name for key in ["embed_tokens", "lm_head"]):`` line.

All sub-patches ``required=True`` — partial application would leave the
model in an inconsistent state (e.g. PPMissingLayer for embed but real
lm_head; or weights loaded into a layer that doesn't exist). On any
sub-patch failure, the patcher aborts cleanly with no state mutation
(TextPatcher semantics).

Composition + safety
====================

  * Conflict surface vs. existing Genesis patches: ZERO. Repo scan
    shows no other Genesis patch touches ``qwen3_5_mtp.py`` or
    ``share_backbone_input_output``.
  * Composes with PN108 + PN133 + PN290 (MTP runtime patches in
    different files; no anchor overlap).
  * Composes with PN340 + PN341 + PN345 (constructor-time fix vs.
    runtime fixes — orthogonal layers).
  * Composes with PN77 (FP8 lm_head): PN77 affects TARGET model's
    lm_head dtype; PN348 gates the MTP backbone's lm_head EXISTENCE.
    PN77 becomes moot for the now-PPMissingLayer MTP backbone.
  * Risk on models that DON'T opt in to shared backbone: NONE. The
    ``getattr(config, "mtp_use_dedicated_embeddings", True)`` default
    preserves the legacy allocate-fresh-tensor path.
  * Risk on PP>1 deployments: NONE. The ``world_size == 1`` gate keeps
    the legacy path on pipeline-parallel setups.

Per harsha20032020 PR #44720 (already in pin), Qwen3.6 reuses the
``Qwen3_5MoeForConditionalGeneration`` model class — single-file patch
covers both 27B and 35B Qwen3.6 SKUs.

Runtime verification (post-restart)
===================================

  docker exec vllm-qwen3.6-35b-balanced-k3 python3 -c "
  import gc, torch
  mtps = [o for o in gc.get_objects()
          if type(o).__name__ in ('Qwen3_5MTP','Qwen3_5MoeMTP')]
  for m in mtps:
      print(' share:', getattr(m.model,'share_backbone_input_output','?'),
            ' embed:', type(m.model.embed_tokens).__name__,
            ' lm_head:', type(m.lm_head).__name__)
  "

Expected: ``share: True`` and BOTH ``lm_head`` and
``model.embed_tokens`` typed ``PPMissingLayer``. Differential VRAM
test: capture per-GPU ``mem_get_info`` with PN348 disabled vs enabled,
expect ~500 MiB drop per rank.

Author: Sander (Sandermage / Aleksandr Barzov), Odessa, Ukraine.
Vendor target: vllm-project/vllm#44644 (open as of 2026-06-09).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, TextPatchResult

log = logging.getLogger("genesis.wiring.pn348_qwen3_mtp_backbone_dedup")

GENESIS_PN348_MARKER = (
    "Genesis PN348 vendor of vllm#44644 (Qwen3.5/3.6 MTP backbone dedup) v1"
)

_TARGET_REL = "model_executor/models/qwen3_5_mtp.py"


# ── Sub-1: embed_tokens predicate ───────────────────────────────────────
# Anchor: 5 lines just below the ``mtp_num_hidden_layers`` assignment in
# ``Qwen3_5MultiTokenPredictor.__init__``. Uniquely occurring in the
# file (only one VocabParallelEmbedding allocation on the MTP backbone).
PN348_EMBED_OLD = (
    '        self.mtp_start_layer_idx = config.num_hidden_layers\n'
    '        self.num_mtp_layers = getattr(config, "mtp_num_hidden_layers", 1)\n'
    '\n'
    '        self.embed_tokens = VocabParallelEmbedding(\n'
    '            self.vocab_size,\n'
    '            config.hidden_size,\n'
    '        )\n'
)
PN348_EMBED_NEW = (
    '        self.mtp_start_layer_idx = config.num_hidden_layers\n'
    '        self.num_mtp_layers = getattr(config, "mtp_num_hidden_layers", 1)\n'
    '        # [Genesis PN348 vendor of vllm#44644] share embed+lm_head\n'
    '        # with target model when checkpoint opts in (Qwen3.5/3.6 set\n'
    '        # text_config.mtp_use_dedicated_embeddings=False). Saves\n'
    '        # vocab*hidden*2 B = ~1 GiB/worker on Qwen3.6-35B-A3B-FP8.\n'
    '        # PP=1 gate keeps legacy path on pipeline-parallel setups.\n'
    '        self.share_backbone_input_output = (\n'
    '            not getattr(config, "mtp_use_dedicated_embeddings", True)\n'
    '            and get_pp_group().world_size == 1\n'
    '        )\n'
    '        if self.share_backbone_input_output:\n'
    '            self.embed_tokens = PPMissingLayer()\n'
    '        else:\n'
    '            self.embed_tokens = VocabParallelEmbedding(\n'
    '                self.vocab_size,\n'
    '                config.hidden_size,\n'
    '            )\n'
)


# ── Sub-2: lm_head fallthrough ──────────────────────────────────────────
# Anchor: the ``if config.tie_word_embeddings:`` line inside the
# ``if get_pp_group().is_last_rank:`` block. Disambiguated by including
# the surrounding lm_head-assignment lines (unique pair in the file).
PN348_LMHEAD_OLD = (
    '        if get_pp_group().is_last_rank:\n'
    '            if config.tie_word_embeddings:\n'
    '                self.lm_head = self.model.embed_tokens\n'
    '            else:\n'
    '                self.lm_head = ParallelLMHead(\n'
)
PN348_LMHEAD_NEW = (
    '        if get_pp_group().is_last_rank:\n'
    '            if self.model.share_backbone_input_output:\n'
    '                # [Genesis PN348] target owns lm_head — skip allocation.\n'
    '                self.lm_head = PPMissingLayer()\n'
    '            elif config.tie_word_embeddings:\n'
    '                self.lm_head = self.model.embed_tokens\n'
    '            else:\n'
    '                self.lm_head = ParallelLMHead(\n'
)


# ── Sub-3: weight-loader skip ───────────────────────────────────────────
# Anchor: the ``elif any(...embed_tokens..lm_head...)`` line in
# ``remap_weight_names``. Uniquely occurring. Skip BOTH names entirely
# when sharing — the target model loads them; MTP has no Module to
# receive them (PPMissingLayer is a no-op shim).
PN348_LOADER_OLD = (
    '                if name.startswith("mtp."):\n'
    '                    name = name.replace("mtp.", "model.")\n'
    '                elif any(key in name for key in ["embed_tokens", "lm_head"]):\n'
    '                    if "embed_tokens" in name:\n'
    '                        name = name.replace("language_model.", "")\n'
    '                else:\n'
)
PN348_LOADER_NEW = (
    '                if name.startswith("mtp."):\n'
    '                    name = name.replace("mtp.", "model.")\n'
    '                elif any(key in name for key in ["embed_tokens", "lm_head"]):\n'
    '                    # [Genesis PN348] target owns the weight — skip duplicate load.\n'
    '                    if self.model.share_backbone_input_output:\n'
    '                        continue\n'
    '                    if "embed_tokens" in name:\n'
    '                        name = name.replace("language_model.", "")\n'
    '                else:\n'
)


def _env_disabled() -> bool:
    return os.environ.get("GENESIS_DISABLE_PN348", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def apply() -> tuple[str, str]:
    """Apply PN348 — Qwen3.5/3.6 MTP backbone dedup on qwen3_5_mtp.py."""
    if _env_disabled():
        return "skipped", "PN348 disabled via GENESIS_DISABLE_PN348=1"

    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return "skipped", (
            "PN348: target file model_executor/models/qwen3_5_mtp.py not "
            "found (vllm pin may not be Qwen3.5/3.6 era). Skipping."
        )

    patcher = TextPatcher(
        patch_name="PN348 qwen3_5_mtp.py — MTP backbone dedup (vllm#44644)",
        target_file=str(target),
        marker=GENESIS_PN348_MARKER,
        sub_patches=[
            TextPatch(
                name="pn348_embed_predicate",
                anchor=PN348_EMBED_OLD,
                replacement=PN348_EMBED_NEW,
                required=True,
            ),
            TextPatch(
                name="pn348_lm_head_fallthrough",
                anchor=PN348_LMHEAD_OLD,
                replacement=PN348_LMHEAD_NEW,
                required=True,
            ),
            TextPatch(
                name="pn348_loader_skip",
                anchor=PN348_LOADER_OLD,
                replacement=PN348_LOADER_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN348",
            # upstream sentinel from PR #44644 — if merge lands, auto-skip
            "share_backbone_input_output",
        ],
    )

    try:
        result, failure = patcher.apply()
    except Exception as e:  # noqa: BLE001
        return "failed", f"PN348 apply raised {e!r}"

    if result == TextPatchResult.FAILED:
        return "failed", (
            f"PN348 FAILED — {failure.reason if failure else 'unknown anchor mismatch'}"
        )
    if result == TextPatchResult.SKIPPED:
        return "skipped", (
            f"PN348 skipped — {failure.reason if failure else 'unknown'} "
            f"(check for upstream merge of vllm#44644)"
        )
    if result == TextPatchResult.IDEMPOTENT:
        return "applied", (
            "PN348 idempotent (already applied). MTP backbone dedup live: "
            "embed_tokens + lm_head share with target on Qwen3.5/3.6 when "
            "mtp_use_dedicated_embeddings=False; ~1 GiB/worker freed."
        )

    n = len(patcher.applied_sub_patches)
    return "applied", (
        f"PN348 applied: {n}/3 sub-patches on qwen3_5_mtp.py — MTP "
        f"backbone now skips duplicate embed_tokens + lm_head + "
        f"weight-load when target shares them (Qwen3.5/3.6 with "
        f"mtp_use_dedicated_embeddings=False at PP=1). Est. VRAM "
        f"freed: ~1 GiB/worker × TP=2 = ~2 GiB cluster-wide on 35B-A3B-FP8. "
        f"Vendor of OPEN PR vllm#44644. Composes with PN108+PN133+PN290+PN340+PN341+PN77."
    )


def is_applied() -> bool:
    target = resolve_vllm_file(_TARGET_REL)
    if target is None:
        return False
    try:
        return GENESIS_PN348_MARKER in Path(str(target)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
