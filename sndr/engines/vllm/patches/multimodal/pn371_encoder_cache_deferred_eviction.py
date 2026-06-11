# SPDX-License-Identifier: Apache-2.0
"""PN371 — deferred ref-pinned encoder-cache eviction (vendor of vllm#45199).

Upstream bug (vllm#38551, OPEN): the scheduler requests eviction of
encoder outputs (``free_encoder_mm_hashes``) based on its own view of
request progress, which can be STALE by the time the step reaches the
worker — under async scheduling ``num_computed_tokens`` is advanced
speculatively and rolled back on draft-token rejection, and an entry can
be shared by concurrent requests with identical content (same mm_hash).
Evicting an entry that an in-flight request may still read kills the
WHOLE ENGINE with::

    AssertionError: Encoder cache miss for <mm_hash>.

in ``GPUModelRunner._gather_mm_embeddings``. That is exactly the
Gemma-4 vision + MTP K=3 + async-scheduling triple our gemma4 composes
run (roadmap 2026-06-11 chunk-1 Theme B, only wave-1 item).

Upstream PR #45199 ("[BugFix] Defer encoder cache eviction while entries
are referenced by in-flight requests") fixes this by ref-counting: the
``EncoderCache`` tracks which in-flight requests reference each mm_hash
and defers a scheduler-requested eviction until the last referencing
request is removed. Unreferenced entries are evicted eagerly, exactly as
before; memory overhead is bounded by the encoder outputs of in-flight
requests. Encoder-decoder models (e.g. Whisper) keep eager eviction
(``eager_eviction=True``) — the scheduler only frees their entries once
cross-attention KV is cached and the output is provably dead.

UPSTREAM STATUS (verified 2026-06-11 via ``gh pr view 45199``): the PR
was CLOSED unmerged on 2026-06-11 (no comments, no successor named).
Issue #38551 is still OPEN; sibling PR #39544 ("Retain encoder cache
entries for multimodal models under async scheduling") is still OPEN —
WATCHLIST: if #39544 (different mechanism, scheduler-side) merges
instead, PN371's legacy-runner anchors will drift and the patch will
skip loudly at the next pin bump — re-evaluate then.

Verified at pin 0.22.1rc1.dev259+g303916e93 (2026-06-11): all 11
anchors byte-exact, count==1, drift markers absent (script in the
PR-sweep journal). The pin contains BOTH runners — the modular
``v1/worker/gpu/model_runner.py`` (already wired to EncoderCache
add/remove/free) and the legacy ``v1/worker/gpu_model_runner.py``
(raw dict, no tracking; selected unless ``use_v2_model_runner``).

Vendoring scope vs upstream #45199:
  * VENDORED 1:1: ref-counted ``EncoderCache`` (``eager_eviction`` +
    caller-owned ``encoder_outputs`` dict + ``update_request`` +
    deferred ``free_encoder_cache``) in ``gpu/mm/encoder_cache.py``;
    modular-runner ``eager_eviction=is_encoder_decoder`` wiring; the 5
    legacy-runner tracker points (finished-request unref, deferred
    free, new-request ref, streaming update, reset).
  * ADAPTED: the legacy tracker attribute is named
    ``_g_pn371_ec_tracker`` (upstream: ``encoder_cache_tracker``) so
    the legacy drift marker — upstream's exact tracker call text —
    can never match our own replacement (lint_drift_markers contract);
    the EncoderCache ``__init__`` signature is written single-line for
    the same reason (the drift marker is upstream's two-line form).
    The import is inlined at the ctor wiring point instead of a
    module-header sub-patch (one fewer anchor).
  * GENESIS EXTEND (per roadmap): the fatal "Encoder cache miss"
    assert in ``_gather_mm_embeddings`` is demoted to
    ``logger.warning_once`` + skip-feature in the DRAFTER path only
    (``shift_computed_tokens != 0`` — the drafter's shifted window,
    sole non-zero caller at this pin). The target model verifies every
    draft token, so a skipped feature only degrades draft quality for
    those positions; the verifier path keeps the hard assert.

Self-skips when #45199 (or its exact form) lands: drift markers are
exact substrings of the PR's merged form — the ``eager_eviction``
two-line ``__init__`` signature (encoder_cache.py), the multi-line
``EncoderCache(eager_eviction=...)`` ctor (modular runner), and the
``encoder_cache_tracker.free_encoder_cache`` call (legacy runner).

Enablement: opt-in via GENESIS_ENABLE_PN371_ENCODER_CACHE_EVICTION=1
(default_on=False). Intended ON for the gemma4 composes (model_arch
Gemma4*); zero impact on text-only Qwen PROD — with no mm features the
tracker never holds a reference and every eviction stays eager.
"""
from __future__ import annotations

import logging

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from sndr.kernel import TextPatch, TextPatcher, result_to_wiring_status
from sndr.kernel.text_patch import TextPatchResult

log = logging.getLogger("genesis.wiring.pn371_encoder_cache_deferred_eviction")

GENESIS_PN371_MARKER = (
    "Genesis PN371 deferred ref-pinned encoder-cache eviction "
    "(vendor of vllm#45199) v1"
)

_ENCODER_CACHE_REL = "v1/worker/gpu/mm/encoder_cache.py"
_MODULAR_RUNNER_REL = "v1/worker/gpu/model_runner.py"
_LEGACY_RUNNER_REL = "v1/worker/gpu_model_runner.py"

# Drift markers — exact substrings of #45199's merged form, verified
# against `gh pr diff 45199` on 2026-06-11. Absent at pin g303916e93 and
# deliberately NOT substrings of our own replacement texts: our
# EncoderCache __init__ is single-line (the marker is upstream's
# two-line signature), our modular ctor call is single-line (the marker
# is upstream's three-line form), and our legacy tracker attribute is
# `_g_pn371_ec_tracker` (the marker is upstream's
# `encoder_cache_tracker` call).
_ENCODER_CACHE_DRIFT_MARKERS = (
    "        eager_eviction: bool = False,\n"
    "        encoder_outputs: dict[str, torch.Tensor] | None = None,",
)
_MODULAR_RUNNER_DRIFT_MARKERS = (
    "            self.encoder_cache = EncoderCache(\n"
    "                eager_eviction=self.model_config.is_encoder_decoder\n"
    "            )",
)
_LEGACY_RUNNER_DRIFT_MARKERS = (
    "self.encoder_cache_tracker.free_encoder_cache(mm_hash)",
)

# ── encoder_cache.py — vendored ref-counted class ────────────────────

PN371_EC_CTOR_OLD = (
    "    def __init__(self):\n"
    "        # req_id -> MM features\n"
    "        self.mm_features: dict[str, list[MultiModalFeatureSpec]] = {}\n"
    "        # MM hash -> encoder outputs\n"
    "        self.encoder_outputs: dict[str, torch.Tensor] = {}\n"
)

PN371_EC_CTOR_NEW = (
    "    # [Genesis PN371] ref-counted eviction (vendor of vllm#45199):\n"
    "    # entries referenced by in-flight requests survive scheduler\n"
    "    # frees until the last referencing request is removed. Signature\n"
    "    # kept single-line on purpose (drift-marker hygiene).\n"
    "    def __init__(self, eager_eviction: bool = False, encoder_outputs: dict[str, torch.Tensor] | None = None):\n"  # noqa: E501
    "        # req_id -> MM features\n"
    "        self.mm_features: dict[str, list[MultiModalFeatureSpec]] = {}\n"
    "        # MM hash -> encoder outputs. May be a caller-owned dict so\n"
    "        # that existing code holding a reference observes evictions.\n"
    "        self.encoder_outputs: dict[str, torch.Tensor] = (\n"
    "            encoder_outputs if encoder_outputs is not None else {}\n"
    "        )\n"
    "        # Evict on free_encoder_cache() even while referenced\n"
    "        # (encoder-decoder models: entry provably dead when freed).\n"
    "        self.eager_eviction = eager_eviction\n"
    "        # MM hash -> ids of in-flight requests referencing it.\n"
    "        self._mm_hash_refs: dict[str, set[str]] = {}\n"
    "        # Hashes whose eviction was requested while still referenced.\n"
    "        self._pending_free: set[str] = set()\n"
)

PN371_EC_TRACK_OLD = (
    "    def add_request(\n"
    "        self, req_id: str, mm_features: list[MultiModalFeatureSpec]\n"
    "    ) -> None:\n"
    "        self.mm_features[req_id] = mm_features\n"
    "\n"
    "    def remove_request(self, req_id: str) -> None:\n"
    "        self.mm_features.pop(req_id, None)\n"
)

PN371_EC_TRACK_NEW = (
    "    def add_request(\n"
    "        self, req_id: str, mm_features: list[MultiModalFeatureSpec]\n"
    "    ) -> None:\n"
    "        self.mm_features[req_id] = mm_features\n"
    "        if not mm_features:\n"
    "            return\n"
    "        for mm_hash in {f.identifier for f in mm_features}:\n"
    "            self._mm_hash_refs.setdefault(mm_hash, set()).add(req_id)\n"
    "            # Referenced again — cancel any deferred eviction.\n"
    "            self._pending_free.discard(mm_hash)\n"
    "\n"
    "    def update_request(\n"
    "        self, req_id: str, mm_features: list[MultiModalFeatureSpec]\n"
    "    ) -> None:\n"
    "        # [Genesis PN371] replace the request's MM features, carrying\n"
    "        # references over for hashes present in both lists.\n"
    "        old_features = self.mm_features.get(req_id) or []\n"
    "        old_hashes = {f.identifier for f in old_features}\n"
    "        self.add_request(req_id, mm_features)\n"
    "        new_hashes = {f.identifier for f in mm_features or []}\n"
    "        for mm_hash in old_hashes - new_hashes:\n"
    "            self._unref(mm_hash, req_id)\n"
    "\n"
    "    def remove_request(self, req_id: str) -> None:\n"
    "        mm_features = self.mm_features.pop(req_id, None)\n"
    "        if not mm_features:\n"
    "            return\n"
    "        for mm_hash in {f.identifier for f in mm_features}:\n"
    "            self._unref(mm_hash, req_id)\n"
    "\n"
    "    def _unref(self, mm_hash: str, req_id: str) -> None:\n"
    "        refs = self._mm_hash_refs.get(mm_hash)\n"
    "        if refs is None:\n"
    "            return\n"
    "        refs.discard(req_id)\n"
    "        if refs:\n"
    "            return\n"
    "        del self._mm_hash_refs[mm_hash]\n"
    "        if mm_hash in self._pending_free:\n"
    "            # Scheduler requested eviction while still referenced;\n"
    "            # the last reference is gone, so evict now.\n"
    "            self._pending_free.discard(mm_hash)\n"
    "            self.encoder_outputs.pop(mm_hash, None)\n"
)

PN371_EC_FREE_OLD = (
    "        self.encoder_outputs.clear()\n"
    "\n"
    "    def free_encoder_cache(self, mm_hash: str) -> None:\n"
    "        self.encoder_outputs.pop(mm_hash, None)\n"
)

PN371_EC_FREE_NEW = (
    "        self.encoder_outputs.clear()\n"
    "        self._pending_free.clear()\n"
    "\n"
    "    def free_encoder_cache(self, mm_hash: str) -> None:\n"
    "        # [Genesis PN371] an in-flight request may still read this\n"
    "        # entry: the scheduler frees based on speculative progress\n"
    "        # that async scheduling rolls back on draft-token rejection,\n"
    "        # and concurrent requests can share the same content hash.\n"
    "        # Defer until the last referencing request is removed.\n"
    "        if not self.eager_eviction and self._mm_hash_refs.get(mm_hash):\n"
    "            self._pending_free.add(mm_hash)\n"
    "        else:\n"
    "            self.encoder_outputs.pop(mm_hash, None)\n"
)

# ── gpu/model_runner.py (modular runner) — eager for encoder-decoder ─

PN371_MODULAR_CTOR_OLD = (
    "            self.encoder_cache = EncoderCache()\n"
)

PN371_MODULAR_CTOR_NEW = (
    "            # [Genesis PN371] encoder-decoder models free entries\n"
    "            # only once provably dead -> eager eviction; all other\n"
    "            # multimodal models defer while referenced.\n"
    "            self.encoder_cache = EncoderCache(eager_eviction=self.model_config.is_encoder_decoder)\n"  # noqa: E501
)

# ── gpu_model_runner.py (legacy runner) — 5 tracker points + EXTEND ──

PN371_LEGACY_CTOR_OLD = (
    "        # mm_hash ->  encoder_output\n"
    "        self.encoder_cache: dict[str, torch.Tensor] = {}\n"
)

PN371_LEGACY_CTOR_NEW = (
    "        # mm_hash ->  encoder_output\n"
    "        self.encoder_cache: dict[str, torch.Tensor] = {}\n"
    "        # [Genesis PN371] deferred ref-pinned eviction tracker —\n"
    "        # SHARES the encoder_cache dict so every existing reader\n"
    "        # observes evictions through the original reference.\n"
    "        from vllm.v1.worker.gpu.mm.encoder_cache import (\n"
    "            EncoderCache as _GPN371EncoderCache,\n"
    "        )\n"
    "        self._g_pn371_ec_tracker = _GPN371EncoderCache(\n"
    "            eager_eviction=self.model_config.is_encoder_decoder,\n"
    "            encoder_outputs=self.encoder_cache,\n"
    "        )\n"
)

PN371_LEGACY_RESET_OLD = (
    "        self.encoder_cache.clear()\n"
    "        self.late_interaction_runner.clear()\n"
)

PN371_LEGACY_RESET_NEW = (
    "        # [Genesis PN371] clear the shared dict AND the pending-free\n"
    "        # set via the tracker (stale pending hashes must not outlive\n"
    "        # a weight update).\n"
    "        self._g_pn371_ec_tracker.reset_encoder_cache()\n"
    "        self.late_interaction_runner.clear()\n"
)

PN371_LEGACY_FINISHED_OLD = (
    "        for req_id in scheduler_output.finished_req_ids:\n"
    "            self.requests.pop(req_id, None)\n"
    "            self.num_prompt_logprobs.pop(req_id, None)\n"
)

PN371_LEGACY_FINISHED_NEW = (
    "        for req_id in scheduler_output.finished_req_ids:\n"
    "            self.requests.pop(req_id, None)\n"
    "            self.num_prompt_logprobs.pop(req_id, None)\n"
    "            # [Genesis PN371] drop this request's encoder-cache refs;\n"
    "            # evicts entries whose eviction was deferred on its behalf.\n"
    "            self._g_pn371_ec_tracker.remove_request(req_id)\n"
)

PN371_LEGACY_FREE_OLD = (
    "        # Free the cached encoder outputs.\n"
    "        for mm_hash in scheduler_output.free_encoder_mm_hashes:\n"
    "            self.encoder_cache.pop(mm_hash, None)\n"
)

PN371_LEGACY_FREE_NEW = (
    "        # Free the cached encoder outputs. [Genesis PN371] eviction\n"
    "        # is deferred for entries still referenced by an in-flight\n"
    "        # request (async-scheduling rollback / spec-decode drafting /\n"
    "        # mm_hash reuse) — see EncoderCache.free_encoder_cache.\n"
    "        for mm_hash in scheduler_output.free_encoder_mm_hashes:\n"
    "            self._g_pn371_ec_tracker.free_encoder_cache(mm_hash)\n"
)

PN371_LEGACY_ADD_OLD = (
    "            self.requests[req_id] = req_state\n"
    "            self.late_interaction_runner.register_request(req_id, pooling_params)\n"
)

PN371_LEGACY_ADD_NEW = (
    "            self.requests[req_id] = req_state\n"
    "            # [Genesis PN371] pin this request's encoder-cache entries.\n"
    "            if new_req_data.mm_features:\n"
    "                self._g_pn371_ec_tracker.add_request(\n"
    "                    req_id, new_req_data.mm_features\n"
    "                )\n"
    "            self.late_interaction_runner.register_request(req_id, pooling_params)\n"
)

PN371_LEGACY_STREAM_OLD = (
    "        req_state.prompt_token_ids = new_req_data.prompt_token_ids\n"
    "        req_state.mm_features = new_req_data.mm_features\n"
)

PN371_LEGACY_STREAM_NEW = (
    "        req_state.prompt_token_ids = new_req_data.prompt_token_ids\n"
    "        req_state.mm_features = new_req_data.mm_features\n"
    "        # [Genesis PN371] carry encoder-cache refs over to the\n"
    "        # streaming session's new feature list.\n"
    "        self._g_pn371_ec_tracker.update_request(\n"
    "            req_id, new_req_data.mm_features or []\n"
    "        )\n"
)

PN371_LEGACY_DRAFTER_OLD = (
    "                mm_hash = mm_feature.identifier\n"
    "                encoder_output = self.encoder_cache.get(mm_hash, None)\n"
    "                assert encoder_output is not None, f\"Encoder cache miss for {mm_hash}.\"\n"  # noqa: E501
)

PN371_LEGACY_DRAFTER_NEW = (
    "                mm_hash = mm_feature.identifier\n"
    "                encoder_output = self.encoder_cache.get(mm_hash, None)\n"
    "                # [Genesis PN371 EXTEND] drafter path only\n"
    "                # (shift_computed_tokens != 0, sole non-zero caller is\n"
    "                # the MTP draft proposal): a missing entry must not\n"
    "                # kill the engine. The target model verifies every\n"
    "                # draft token, so skipping this feature merely degrades\n"
    "                # draft quality for these positions. The verifier path\n"
    "                # below keeps the hard assert.\n"
    "                if encoder_output is None and shift_computed_tokens != 0:\n"
    "                    logger.warning_once(\n"
    "                        \"[Genesis PN371] missing encoder-cache entry %s \"\n"
    "                        \"in the drafter window — feature skipped for \"\n"
    "                        \"draft proposal (degraded draft, not fatal)\",\n"
    "                        mm_hash,\n"
    "                    )\n"
    "                    continue\n"
    "                assert encoder_output is not None, f\"Encoder cache miss for {mm_hash}.\"\n"  # noqa: E501
)


def _make_encoder_cache_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_ENCODER_CACHE_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN371 gpu/mm/encoder_cache.py — ref-counted deferred eviction "
            "(vendor of vllm#45199)"
        ),
        target_file=str(target),
        marker=GENESIS_PN371_MARKER,
        sub_patches=[
            TextPatch(
                name="pn371_ec_ctor_refcount_state",
                anchor=PN371_EC_CTOR_OLD,
                replacement=PN371_EC_CTOR_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_ec_request_ref_tracking",
                anchor=PN371_EC_TRACK_OLD,
                replacement=PN371_EC_TRACK_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_ec_deferred_free",
                anchor=PN371_EC_FREE_OLD,
                replacement=PN371_EC_FREE_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_ENCODER_CACHE_DRIFT_MARKERS),
    )


def _make_modular_runner_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_MODULAR_RUNNER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN371 gpu/model_runner.py — eager eviction for encoder-decoder "
            "models (vendor of vllm#45199)"
        ),
        target_file=str(target),
        marker=GENESIS_PN371_MARKER,
        sub_patches=[
            TextPatch(
                name="pn371_modular_eager_eviction_ctor",
                anchor=PN371_MODULAR_CTOR_OLD,
                replacement=PN371_MODULAR_CTOR_NEW,
                required=True,
            ),
        ],
        upstream_drift_markers=list(_MODULAR_RUNNER_DRIFT_MARKERS),
    )


def _make_legacy_runner_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_LEGACY_RUNNER_REL)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN371 gpu_model_runner.py — encoder-cache tracker wiring + "
            "drafter-path miss demotion (vendor of vllm#45199)"
        ),
        target_file=str(target),
        marker=GENESIS_PN371_MARKER,
        sub_patches=[
            TextPatch(
                name="pn371_legacy_tracker_ctor",
                anchor=PN371_LEGACY_CTOR_OLD,
                replacement=PN371_LEGACY_CTOR_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_legacy_reset_via_tracker",
                anchor=PN371_LEGACY_RESET_OLD,
                replacement=PN371_LEGACY_RESET_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_legacy_finished_unref",
                anchor=PN371_LEGACY_FINISHED_OLD,
                replacement=PN371_LEGACY_FINISHED_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_legacy_deferred_free",
                anchor=PN371_LEGACY_FREE_OLD,
                replacement=PN371_LEGACY_FREE_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_legacy_new_request_ref",
                anchor=PN371_LEGACY_ADD_OLD,
                replacement=PN371_LEGACY_ADD_NEW,
                required=True,
            ),
            TextPatch(
                name="pn371_legacy_streaming_update_ref",
                anchor=PN371_LEGACY_STREAM_OLD,
                replacement=PN371_LEGACY_STREAM_NEW,
                required=True,
            ),
            TextPatch(
                # Genesis EXTEND — belt-and-suspenders; never abort the
                # core tracker wiring if this anchor drifts.
                name="pn371_drafter_cache_miss_demotion",
                anchor=PN371_LEGACY_DRAFTER_OLD,
                replacement=PN371_LEGACY_DRAFTER_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=list(_LEGACY_RUNNER_DRIFT_MARKERS),
    )


def apply() -> tuple[str, str]:
    """Install the deferred-eviction class + runner wiring. Never raises.

    Ordering matters: the EncoderCache class patch MUST land before the
    runner wiring — the pristine class rejects the tracker kwargs with a
    TypeError at runner init. If the class patch cannot land, the runner
    wiring is withheld.
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN371")
    log_decision("PN371", decision, reason)
    if not decision:
        return "skipped", reason

    ec = _make_encoder_cache_patcher()
    if ec is None:
        return "skipped", f"PN371: {_ENCODER_CACHE_REL} not resolvable"
    modular = _make_modular_runner_patcher()
    if modular is None:
        return "skipped", f"PN371: {_MODULAR_RUNNER_REL} not resolvable"
    legacy = _make_legacy_runner_patcher()
    if legacy is None:
        return "skipped", f"PN371: {_LEGACY_RUNNER_REL} not resolvable"

    ec_result, ec_failure = ec.apply()
    if ec_result == TextPatchResult.FAILED:
        _, ec_reason = result_to_wiring_status(
            ec_result, ec_failure,
            applied_message="", patch_name="PN371 encoder-cache class",
        )
        return "failed", ec_reason
    if ec_result == TextPatchResult.SKIPPED:
        skip_reason = ec_failure.reason if ec_failure else "unknown_skip"
        if skip_reason == "upstream_merged":
            return "skipped", (
                "PN371: upstream_merged — #45199's deferred-eviction form "
                "detected in encoder_cache.py; native ref-counting active, "
                "Genesis vendoring obsolete"
            )
        detail = ec_failure.detail if ec_failure and ec_failure.detail else ""
        return "skipped", (
            f"PN371: encoder-cache class patch skipped ({skip_reason}"
            f"{' — ' + detail if detail else ''}) — runner wiring withheld "
            "(pristine EncoderCache rejects the tracker kwargs)"
        )

    # Class patched (or already patched) — wire both runners.
    runner_states: list[tuple[str, TextPatchResult, str]] = []
    for patcher, label in ((modular, "modular runner"), (legacy, "legacy runner")):
        r_result, r_failure = patcher.apply()
        _, r_reason = result_to_wiring_status(
            r_result, r_failure,
            applied_message=f"{label} wiring applied",
            patch_name=f"PN371 {label}",
        )
        if r_result == TextPatchResult.FAILED:
            return "failed", r_reason
        runner_states.append((label, r_result, r_reason))

    detail = " | ".join(f"{lbl}: {rsn}" for lbl, _, rsn in runner_states)
    legacy_result = runner_states[1][1]
    all_results = [ec_result] + [r for _, r, _ in runner_states]

    if all(r == TextPatchResult.IDEMPOTENT for r in all_results):
        return "skipped", "PN371: already applied (markers present)"

    if legacy_result in (TextPatchResult.APPLIED, TextPatchResult.IDEMPOTENT):
        applied_subs = ", ".join(legacy.applied_sub_patches) or "none (idempotent)"
        return "applied", (
            "PN371 applied: EncoderCache is ref-counted — scheduler frees "
            "of entries still referenced by in-flight requests are deferred "
            "until the last referencing request finishes (kills the "
            "whole-engine-fatal 'Encoder cache miss' on Gemma-4 vision + "
            "MTP K=3 + async scheduling, vllm#38551; vendor of vllm#45199). "
            "Drafter-path miss demoted to warning_once + feature skip "
            f"(Genesis EXTEND). legacy subs: {applied_subs} | {detail}"
        )

    # Legacy wiring did not land (anchor drift) — the class patch alone is
    # behavior-neutral for the legacy runner (no tracker calls), so report
    # skipped, loudly.
    return "skipped", (
        f"PN371: legacy-runner wiring did not land — value not delivered "
        f"on the legacy runner (class patch is inert without it). {detail}"
    )
