# SPDX-License-Identifier: Apache-2.0
"""P89 — completion_tokens_details.reasoning_tokens in chat usage (vendor of vllm#45471).

Contract pinned here (TDD, written before the implementation):

  1. The patcher is a TWO-file atomic bundle (engine/protocol.py +
     chat_completion/serving.py). Either both files take the patch or
     neither does (MultiFilePatchTransaction.apply_or_skip semantics).

  2. protocol.py sub-patch adds a ``CompletionTokenUsageInfo`` model AND
     wires ``UsageInfo.completion_tokens_details`` so the usage object
     can carry it. The model carries the PR's ``reasoning_tokens`` field
     verbatim PLUS the Genesis-extended OpenAI-spec-aligned
     ``accepted_prediction_tokens`` / ``rejected_prediction_tokens``
     fields (default ``None`` until the per-request spec-decode counter
     is plumbed — the PR itself defers these).

  3. serving.py import sub-patch adds ``CompletionTokenUsageInfo`` to the
     ``engine.protocol`` import group.

  4. serving.py streaming sub-patches: (a) declare the per-choice
     token-id accumulator, (b) extend it on each decode step, (c) attach
     ``completion_tokens_details`` to the final usage chunk when a
     reasoning parser is configured.

  5. serving.py non-streaming sub-patch: attach
     ``completion_tokens_details`` to the response usage when a reasoning
     parser is configured.

  6. The reasoning-token count flows through the existing
     ``count_reasoning_tokens`` (one O(n) token-id walk, zero GPU cost).

  7. Genesis divergence (iron rule #10), spelling only: our final-usage
     attachment line carries a Genesis inline marker comment so the PR's
     exact structural line stays usable as an upstream drift marker
     without colliding with our own emitted text
     (tools/lint_drift_markers.py self-collision contract).

  8. Second apply() is idempotent (marker short-circuit on both files).

  9. apply() on #45471's merged form self-skips via drift markers
     (reason: upstream_merged) without touching either file.

  10. Opt-in: dispatcher-gated on GENESIS_ENABLE_P89_REASONING_TOKENS_USAGE
      (default_on=False). Gate closed => no file touched.

  11. Drift markers do not collide with P89's own replacement text or its
      Layer-6 marker line, and at least one marker is an exact substring
      of the merged form.

  12. Anchors are unique and drift markers absent in the pristine pin
      tree (opportunistic — skipped when the pin tree is not present).

  13. MULTI-ANCHOR / 0.23.1 REDESIGN (live pin dev148
      0.23.1rc1.dev148+gb4c80ec0f): the #45171 parser-unification refactor
      moved three of the five serving anchors. accumulator_decl lost its
      "Always track previous_texts" comment (the dev491 variant — the bare
      ``previous_texts`` line + ``\n\n        try:`` — is the one that
      resolves on dev148). The stream + full prompt_tokens_details guard
      blocks were replaced by a ``_make_prompt_tokens_details(...)`` helper
      call and the ``self.reasoning_parser_cls`` gate was removed in favour
      of the per-choice ``Parser.reasoning_parser`` (the dev101 attach
      variants). Each moved site carries dev259 + dev491 (+ dev101 for the
      two attach sites) anchor variants with required-at-least-one
      semantics (PN32/P18B convention); the variants are mutually exclusive
      so exactly one fires per pin (count==1 in its target tree, count==0
      in the others). On dev148 the ACTIVE set is accum-decl-dev491 +
      stream/full-attach-dev101; the two dev101 attach variants are
      ``required=True`` so a future silent drift on the active pin SKIPs
      loudly instead of dropping the reasoning count. The retained
      dev259/dev491-attach variants (``required=False``) soft-skip on
      dev148 and are kept for the rollback window. protocol.py and the two
      non-moved serving sites (import, accumulator-extend) stay byte-stable
      across all three pin forms.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Unit tests patch fresh tmp files; the Layer-0 cache must never satisfy
# apply() from a previous run's state.
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.serving import (  # noqa: E402
    p89_reasoning_tokens_usage as m,
)

# ── Fake targets ─────────────────────────────────────────────────────
# Pin-form (g303916e93) byte-faithful copies of the anchor regions.

PIN_PROTOCOL = (
    "# fake vllm/entrypoints/openai/engine/protocol.py (pin g303916e93)\n"
    "class PromptTokenUsageInfo(OpenAIBaseModel):\n"
    "    cached_tokens: int | None = None\n"
    "\n"
    "\n"
    "class UsageInfo(OpenAIBaseModel):\n"
    "    prompt_tokens: int = 0\n"
    "    total_tokens: int = 0\n"
    "    completion_tokens: int | None = 0\n"
    "    prompt_tokens_details: PromptTokenUsageInfo | None = None\n"
    "\n"
    "\n"
    "class RequestResponseMetadata(BaseModel):\n"
    "    request_id: str\n"
)

# The byte-exact anchor regions are interleaved with a minimal scaffold
# of nested defs/blocks so the fake file compiles as real Python (the
# real anchors live deep inside two async methods). The scaffold uses
# the same indentation depth the pristine pin uses at each anchor so the
# byte-faithful anchor lines are reproduced verbatim.
#
# 0.23.1 REDESIGN (pin 0.23.1rc1.dev148+gb4c80ec0f): the #45171
# parser-unification refactor (a) deleted the "Always track
# previous_texts" comment so the accumulator-decl anchor is now the bare
# ``previous_texts`` line immediately followed by ``\n\n        try:``
# (the dev491 accum-decl variant), and (b) replaced the inline
# prompt_tokens_details guard block with a ``_make_prompt_tokens_details(
# ...)`` helper call and removed the ``self.reasoning_parser_cls`` gate.
# The reasoning parser is now reached via the per-choice ``parsers:
# list[Parser | None]`` (streaming) / the ``parser: Parser | None`` param
# (non-streaming), whose ``.reasoning_parser`` exposes the unchanged
# ``count_reasoning_tokens`` walk. This fixture is the byte-faithful
# dev148 form, so the ``required=True`` dev101 stream/full attach anchors
# resolve (count==1, verified against the live pristine dev148 tree).
PIN_SERVING = (
    "# fake vllm/entrypoints/openai/chat_completion/serving.py "
    "(pin dev148 gb4c80ec0f)\n"
    "from vllm.entrypoints.openai.engine.protocol import (\n"
    "    DeltaMessage,\n"
    "    ErrorResponse,\n"
    "    FunctionCall,\n"
    "    PromptTokenUsageInfo,\n"
    "    RequestResponseMetadata,\n"
    "    ToolCall,\n"
    "    UsageInfo,\n"
    ")\n"
    "\n"
    "\n"
    "async def chat_completion_stream_generator(self, request):\n"
    "    if True:\n"
    "        parsers: list = [None] * num_choices\n"
    "        previous_texts = [\"\"] * num_choices\n"
    "\n"
    "        try:\n"
    "            for i, output in enumerate(res.outputs):\n"
    "                if True:\n"
    "                    previous_texts[i] += delta_text\n"
    "\n"
    "                    # set the previous values for the next iteration\n"
    "                    previous_num_tokens[i] += len(output.token_ids)\n"
    "            if include_usage:\n"
    "                final_usage = UsageInfo()\n"
    "                final_usage.prompt_tokens_details = _make_prompt_tokens_details(\n"
    "                    self.enable_prompt_tokens_details,\n"
    "                    num_cached_tokens,\n"
    "                    mm_token_counts,\n"
    "                )\n"
    "\n"
    "                final_usage_chunk = ChatCompletionStreamResponse(\n"
    "                    id=request_id,\n"
    "                )\n"
    "        finally:\n"
    "            pass\n"
    "\n"
    "\n"
    "async def chat_completion_full_generator(\n"
    "    self, request, parser=None\n"
    "):\n"
    "        usage = UsageInfo()\n"
    "        usage.prompt_tokens_details = _make_prompt_tokens_details(\n"
    "            self.enable_prompt_tokens_details,\n"
    "            final_res.num_cached_tokens,\n"
    "            mm_token_counts,\n"
    "        )\n"
    "\n"
    "        request_metadata.final_usage_info = usage\n"
)

# #45471 merged form: the PR's verbatim hunks land in the pin files.
# P89 must self-skip on this (drift marker fires).
MERGED_PROTOCOL = PIN_PROTOCOL.replace(
    "class UsageInfo(OpenAIBaseModel):\n",
    "class CompletionTokenUsageInfo(OpenAIBaseModel):\n"
    "    reasoning_tokens: int = 0\n"
    "\n"
    "\n"
    "class UsageInfo(OpenAIBaseModel):\n",
).replace(
    "    prompt_tokens_details: PromptTokenUsageInfo | None = None\n",
    "    prompt_tokens_details: PromptTokenUsageInfo | None = None\n"
    "    completion_tokens_details: CompletionTokenUsageInfo | None = None\n",
)

# Live PROD pin is dev148 (0.23.1rc1.dev148+gb4c80ec0f), which carries the
# #45171 / #45171-redesign serving form: the accumulator-decl comment is
# deleted (dev491 accum-decl variant active) and the stream/full attach
# sites use the ``_make_prompt_tokens_details(...)`` helper with the
# parser-unification gate (dev101 attach variants active). The dev259 and
# dev491-stream/full variants are RETAINED in the patch (required=False)
# for the rollback window but are count==0 on dev148. The opportunistic
# invariants below run against the real pristine dev148 tree when it is
# present on this host (full dump preferred; the partial
# candidate_pin_current snapshot lacks the entrypoints subtree, so it is
# only a fallback that self-skips the file-gated classes).
_PIN_TREE_CANDIDATES = (
    Path("/private/tmp/vllm_pristine_b4c80ec0f/vllm"),
    Path("/private/tmp/candidate_pin_current/vllm"),
)
PIN_TREE = next(
    (
        p
        for p in _PIN_TREE_CANDIDATES
        if (p / "entrypoints/openai/chat_completion/serving.py").is_file()
    ),
    _PIN_TREE_CANDIDATES[0],
)
PROTOCOL_REL = "entrypoints/openai/engine/protocol.py"
SERVING_REL = "entrypoints/openai/chat_completion/serving.py"

# Serving sub-patch names grouped by their state on the live dev148 tree.
# ACTIVE: exactly these anchors resolve count==1 on dev148 (so the
# TextPatcher applies them). INACTIVE: the retained dev259/dev491 attach
# variants kept for the rollback window — count==0 on dev148 (soft-skip).
_DEV148_ACTIVE_SERVING_NAMES = {
    "p89_serving_import",
    "p89_serving_accumulator_decl_dev491",
    "p89_serving_accumulator_extend",
    "p89_serving_stream_attach_dev101",
    "p89_serving_full_attach_dev101",
}
_DEV148_INACTIVE_SERVING_NAMES = {
    "p89_serving_accumulator_decl",  # dev259 variant (comment-bearing)
    "p89_serving_stream_attach",  # dev259 inline-guard variant
    "p89_serving_stream_attach_dev491",  # dev491 inline-guard variant
    "p89_serving_full_attach",  # dev259 inline-guard variant
    "p89_serving_full_attach_dev491",  # dev491 inline-guard variant
}


# ── Helpers ──────────────────────────────────────────────────────────


def _install_fakes(tmp_path, monkeypatch, protocol_text, serving_text):
    proto = tmp_path / "protocol.py"
    serv = tmp_path / "serving.py"
    proto.write_text(protocol_text, encoding="utf-8")
    serv.write_text(serving_text, encoding="utf-8")

    def _resolve(rel):
        if rel == PROTOCOL_REL:
            return str(proto)
        if rel == SERVING_REL:
            return str(serv)
        return None

    monkeypatch.setattr(m, "resolve_vllm_file", _resolve)
    import sndr.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return proto, serv


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_bundle_targets_both_protocol_and_serving(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING)
        txn = m._make_transaction()
        assert txn is not None
        targets = {os.path.basename(p.target_file) for p in txn.patchers}
        assert targets == {"protocol.py", "serving.py"}

    def test_protocol_patcher_adds_completion_token_usage_model(
        self, tmp_path, monkeypatch
    ):
        _install_fakes(tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING)
        txn = m._make_transaction()
        proto = next(
            p for p in txn.patchers
            if os.path.basename(p.target_file) == "protocol.py"
        )
        repl = "\n".join(sp.replacement for sp in proto.sub_patches)
        assert "class CompletionTokenUsageInfo(OpenAIBaseModel):" in repl
        assert "reasoning_tokens: int = 0" in repl
        # Genesis-extended OpenAI-spec-aligned fields the PR defers.
        assert "accepted_prediction_tokens" in repl
        assert "rejected_prediction_tokens" in repl
        assert "completion_tokens_details" in repl

    def test_serving_count_uses_existing_count_reasoning_tokens(
        self, tmp_path, monkeypatch
    ):
        _install_fakes(tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING)
        txn = m._make_transaction()
        serv = next(
            p for p in txn.patchers
            if os.path.basename(p.target_file) == "serving.py"
        )
        repl = "\n".join(sp.replacement for sp in serv.sub_patches)
        assert "count_reasoning_tokens" in repl
        assert "reasoning_parser_cls" in repl

    def test_module_documents_extension_and_per_request_gap(self):
        doc = m.__doc__ or ""
        assert "45471" in doc
        assert "reasoning_tokens" in doc
        # The honest verified finding: per-request MTP accept counts are
        # NOT plumbed onto RequestOutput in this pin.
        assert "RequestStateStats" in doc or "per-request" in doc

    def test_module_references_registry_env_flag(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_P89_REASONING_TOKENS_USAGE" in src

    def test_transaction_none_when_a_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        assert m._make_transaction() is None


# ── Apply semantics ──────────────────────────────────────────────────


class TestApply:
    def test_apply_pin_form_patches_both_files(self, tmp_path, monkeypatch):
        proto, serv = _install_fakes(
            tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING
        )
        status, reason = m.apply()
        assert status == "applied", reason

        proto_out = proto.read_text(encoding="utf-8")
        serv_out = serv.read_text(encoding="utf-8")

        # protocol.py: model + field wired.
        assert "class CompletionTokenUsageInfo(OpenAIBaseModel):" in proto_out
        assert (
            "completion_tokens_details: CompletionTokenUsageInfo | None = None"
            in proto_out
        )
        # serving.py: import + accumulator + both attach sites.
        assert proto_out.count("class CompletionTokenUsageInfo") == 1
        assert "CompletionTokenUsageInfo" in serv_out
        assert "count_reasoning_tokens" in serv_out
        # Both files still compile after the splices.
        compile(proto_out, str(proto), "exec")
        compile(serv_out, str(serv), "exec")

    def test_attach_runs_only_when_reasoning_parser_configured(
        self, tmp_path, monkeypatch
    ):
        _proto, serv = _install_fakes(
            tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING
        )
        status, reason = m.apply()
        assert status == "applied", reason
        serv_out = serv.read_text(encoding="utf-8")
        # The attach is gated on the reasoning parser being present. The
        # 0.23.1 #45171 redesign removed self.reasoning_parser_cls and
        # reaches the parser via the per-choice Parser's .reasoning_parser
        # (streaming) / the parser param (non-streaming); both attach sites
        # only run when that reasoning parser is not None.
        assert ".reasoning_parser" in serv_out
        assert "if any(p89_reasoning_parsers)" in serv_out
        assert "parser.reasoning_parser is not None" in serv_out

    def test_second_apply_is_idempotent(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING)
        first_status, first_reason = m.apply()
        assert first_status == "applied", first_reason
        second_status, second_reason = m.apply()
        assert second_status in ("applied", "skipped")
        # Idempotent re-run must not duplicate the model or attach blocks.

    def test_idempotent_no_duplicate_model(self, tmp_path, monkeypatch):
        proto, _serv = _install_fakes(
            tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING
        )
        m.apply()
        m.apply()
        proto_out = proto.read_text(encoding="utf-8")
        assert proto_out.count("class CompletionTokenUsageInfo") == 1

    def test_self_skips_on_45471_merged_form(self, tmp_path, monkeypatch):
        proto, serv = _install_fakes(
            tmp_path, monkeypatch, MERGED_PROTOCOL, PIN_SERVING
        )
        status, reason = m.apply()
        assert status == "skipped"
        assert "upstream_merged" in reason
        # Self-skip must not modify either file.
        assert proto.read_text(encoding="utf-8") == MERGED_PROTOCOL

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        proto = tmp_path / "protocol.py"
        serv = tmp_path / "serving.py"
        proto.write_text(PIN_PROTOCOL, encoding="utf-8")
        serv.write_text(PIN_SERVING, encoding="utf-8")

        def _resolve(rel):
            if rel == PROTOCOL_REL:
                return str(proto)
            if rel == SERVING_REL:
                return str(serv)
            return None

        monkeypatch.setattr(m, "resolve_vllm_file", _resolve)
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        monkeypatch.delenv(
            "GENESIS_ENABLE_P89_REASONING_TOKENS_USAGE", raising=False
        )
        status, _reason = m.apply()
        assert status == "skipped"
        assert proto.read_text(encoding="utf-8") == PIN_PROTOCOL
        assert serv.read_text(encoding="utf-8") == PIN_SERVING

    def test_apply_skips_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(m, "resolve_vllm_file", lambda rel: None)
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (True, "test override")
        )
        status, _reason = m.apply()
        assert status == "skipped"


# ── Lint contract (tools/lint_drift_markers.py) ──────────────────────


class TestDriftMarkerSelfCollision:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install_fakes(tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING)
        txn = m._make_transaction()
        for patcher in txn.patchers:
            marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
            assert patcher.upstream_drift_markers, "drift markers must exist"
            for dm in patcher.upstream_drift_markers:
                if dm.startswith("[Genesis"):
                    continue
                for sp in patcher.sub_patches:
                    assert dm not in sp.replacement, (
                        f"drift marker {dm!r} collides with {sp.name} "
                        "replacement — would false-fire Layer 3"
                    )
                assert dm not in marker_line

    def test_markers_match_45471_merged_form(self, tmp_path, monkeypatch):
        _install_fakes(tmp_path, monkeypatch, PIN_PROTOCOL, PIN_SERVING)
        txn = m._make_transaction()
        proto = next(
            p for p in txn.patchers
            if os.path.basename(p.target_file) == "protocol.py"
        )
        assert any(
            dm in MERGED_PROTOCOL for dm in proto.upstream_drift_markers
        )


# ── Pristine dev148 pin invariants (opportunistic) ───────────────────
# Live PROD pin is dev148 (0.23.1rc1.dev148+gb4c80ec0f). The #45171
# parser-unification redesign moved the accumulator-decl + both attach
# sites; on dev148 the ACTIVE serving anchors are import + accum-extend +
# accum-decl-dev491 + stream-attach-dev101 + full-attach-dev101 (count==1
# each), and the retained dev259/dev491-attach variants are count==0
# (kept ``required=False`` for the rollback window so they soft-skip).
# These invariants pin that exact dev148 anchor topology so a future
# silent drift on the active pin is caught, NOT papered over.
@pytest.mark.skipif(
    not (PIN_TREE / SERVING_REL).is_file(),
    reason="pristine dev148 pin tree not present on this machine",
)
class TestAnchorsAgainstPristineDev148Pin:
    def test_protocol_anchor_unique_and_markers_absent(self):
        """#45171 left engine/protocol.py byte-stable — the single
        protocol anchor resolves count==1 on dev148."""
        src = (PIN_TREE / PROTOCOL_REL).read_text(encoding="utf-8")
        for sp in m._protocol_sub_patches():
            assert src.count(sp.anchor) == 1, sp.name
            assert sp.replacement not in src
        for dm in m._PROTOCOL_DRIFT_MARKERS:
            assert dm not in src

    def test_serving_active_anchors_unique_inactive_absent(self):
        # dev148 tree: each ACTIVE serving anchor (import, accum-extend,
        # accum-decl-dev491, stream-attach-dev101, full-attach-dev101)
        # matches count==1; each retained INACTIVE variant (dev259
        # accum-decl, dev259/dev491 stream + full attach) matches
        # count==0. Exactly one variant fires per site on this pin.
        src = (PIN_TREE / SERVING_REL).read_text(encoding="utf-8")
        for sp in m._serving_sub_patches():
            count = src.count(sp.anchor)
            if sp.name in _DEV148_ACTIVE_SERVING_NAMES:
                assert count == 1, f"{sp.name} should be active on dev148"
            elif sp.name in _DEV148_INACTIVE_SERVING_NAMES:
                assert count == 0, f"{sp.name} should be absent on dev148"
            else:  # pragma: no cover - guards a stray sub-patch name
                raise AssertionError(f"unclassified sub-patch {sp.name}")
            assert sp.replacement not in src
        for dm in m._SERVING_DRIFT_MARKERS:
            assert dm not in src

    def test_exactly_one_attach_variant_fires_per_site(self):
        """On dev148 exactly the dev101 variant of each moved attach site
        resolves (the retained dev259/dev491 variants soft-skip)."""
        src = (PIN_TREE / SERVING_REL).read_text(encoding="utf-8")
        for base in ("p89_serving_stream_attach", "p89_serving_full_attach"):
            variants = {
                sp.name: sp.anchor
                for sp in m._serving_sub_patches()
                if sp.name in (base, base + "_dev491", base + "_dev101")
            }
            assert src.count(variants[base]) == 0, base
            assert src.count(variants[base + "_dev491"]) == 0, base + "_dev491"
            assert src.count(variants[base + "_dev101"]) == 1, base + "_dev101"
        # accumulator-decl: dev491 variant active, dev259 variant absent.
        decl = {
            sp.name: sp.anchor
            for sp in m._serving_sub_patches()
            if sp.name in (
                "p89_serving_accumulator_decl",
                "p89_serving_accumulator_decl_dev491",
            )
        }
        assert src.count(decl["p89_serving_accumulator_decl"]) == 0
        assert src.count(decl["p89_serving_accumulator_decl_dev491"]) == 1

    def test_required_dev101_attach_anchors_present(self):
        """The two ``required=True`` dev101 attach anchors must resolve
        on the active pin — if either is count==0 the patch SKIPs and the
        reasoning count is silently dropped (the drift this fixture
        update guards against)."""
        src = (PIN_TREE / SERVING_REL).read_text(encoding="utf-8")
        for sp in m._serving_sub_patches():
            if sp.name in (
                "p89_serving_stream_attach_dev101",
                "p89_serving_full_attach_dev101",
            ):
                assert sp.required is True, sp.name
                assert src.count(sp.anchor) == 1, sp.name

    def test_apply_on_real_dev148_tree_compiles(self, tmp_path, monkeypatch):
        """Apply the serving + protocol patchers against COPIES of the
        real dev148 pristine tree and assert the spliced result compiles
        with exactly the dev101/dev491-active variant of each moved site
        applied once."""
        proto_src = (PIN_TREE / PROTOCOL_REL).read_text(encoding="utf-8")
        serv_src = (PIN_TREE / SERVING_REL).read_text(encoding="utf-8")
        proto, serv = _install_fakes(
            tmp_path, monkeypatch, proto_src, serv_src
        )
        status, reason = m.apply()
        assert status == "applied", reason

        serv_out = serv.read_text(encoding="utf-8")
        proto_out = proto.read_text(encoding="utf-8")
        # Both spliced files still compile.
        compile(serv_out, str(serv), "exec")
        compile(proto_out, str(proto), "exec")
        # The active variant of each moved site applied exactly once.
        assert serv_out.count("per_choice_token_ids: list[list[int]]") == 1
        assert "per_choice_token_ids[i].extend(output.token_ids)" in serv_out
        assert serv_out.count(
            "final_usage.completion_tokens_details = ("
        ) == 1
        assert serv_out.count(
            "usage.completion_tokens_details = CompletionTokenUsageInfo("
        ) == 1
        # The dev101 redesign gate (parser.reasoning_parser) is emitted.
        assert "if any(p89_reasoning_parsers)" in serv_out
        assert "parser.reasoning_parser is not None" in serv_out
        # protocol model + field wired exactly once.
        assert proto_out.count("class CompletionTokenUsageInfo") == 1
        assert (
            "completion_tokens_details: CompletionTokenUsageInfo | None = None"
            in proto_out
        )

    def test_count_reasoning_tokens_exists_in_pin(self):
        """The zero-GPU reasoning-token walk P89 relies on already exists
        on the abstract reasoning parser in the dev148 pin."""
        abs_parser = (
            PIN_TREE / "reasoning" / "abs_reasoning_parsers.py"
        ).read_text(encoding="utf-8")
        assert "def count_reasoning_tokens(" in abs_parser


# ── Dispatcher reachability contract ─────────────────────────────────
# Regression guard for the review's MAJOR finding: a passing apply()
# test that monkeypatches should_apply hides whether the dispatcher can
# actually REACH P89. These tests query the REAL dispatcher (no
# monkeypatch) so a missing/malformed registry entry fails loudly.
#
# The P89 registry entry was added to sndr/dispatcher/registry.py by the
# batch-3 registry-integration step (2026-06-13); these reachability
# assertions now pass directly. The xfail(strict=True) marker that
# guarded the pre-registration window has been removed — these tests are
# the live signal that P89 stays reachable through the real dispatcher.
class TestRegistryReachability:
    def test_p89_is_registered_and_strict_opt_in_by_default(self):
        """P89 must resolve through the real dispatcher to the canonical
        strict-opt-in decision — NOT 'unknown patch_id', which means the
        patch is unreachable even with the env flag exported."""
        from sndr.dispatcher import should_apply

        decision, reason = should_apply("P89")
        assert "unknown patch_id" not in reason, (
            "P89 is not registered in sndr/dispatcher/registry.py — apply() "
            "is unreachable. Add the P89 entry (family=serving, env_flag="
            "GENESIS_ENABLE_P89_REASONING_TOKENS_USAGE, default_on=False, "
            "apply_module=sndr.engines.vllm.patches.serving."
            "p89_reasoning_tokens_usage)."
        )
        # Default OFF: the gate is closed until the env flag is set.
        assert decision is False
        assert "GENESIS_ENABLE_P89_REASONING_TOKENS_USAGE" in reason

    def test_p89_env_flag_engages_the_gate(self, monkeypatch):
        """With the env flag exported, the real dispatcher must OPEN the
        gate for P89 (proves the registry env_flag matches the module)."""
        from sndr.dispatcher import should_apply

        monkeypatch.setenv(
            "GENESIS_ENABLE_P89_REASONING_TOKENS_USAGE", "1"
        )
        decision, reason = should_apply("P89")
        assert "unknown patch_id" not in reason
        assert decision is True, reason
