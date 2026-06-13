# SPDX-License-Identifier: Apache-2.0
"""PN387 — reject degenerate ``structured_outputs`` (vendor of vllm#45346).

Contract pinned here (TDD, written before the implementation):

Upstream bug class (vllm#45346): a single request with
``structured_outputs={"json_object": false}`` or ``{"json": ""}`` crashes
the EngineCore process. ``StructuredOutputsParams.__post_init__`` counts
constraints with ``is not None``, so ``json_object=False``
(``False is not None``) and ``json=""`` (``"" is not None``) pass the
exclusivity check and a request is built and sent to the engine. But
``get_structured_output_key`` only returns ``JSON_OBJECT`` when
``json_object`` is truthy, so ``False`` falls through to
``raise ValueError`` and an empty ``json`` schema fails in the xgrammar
compiler — both inside the EngineCore step loop, which has NO per-request
isolation, so one bad request kills the engine (instance-wide DoS on our
single-instance PROD).

PN387 vendors TWO layers, both gated on the SAME opt-in flag
``GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS``
(default_on=False — pure safety reject, gated so we can A/B the rejection
criteria before flipping on):

  Layer 1 — SOURCE OVERLAY (this is the verbatim PR #45346 backport):
    two guards in ``SamplingParams._validate_structured_outputs`` inserted
    IMMEDIATELY AFTER the pin's existing empty-grammar guard
    (pristine line 888). ``json`` empty string → ValueError;
    ``json_object is False`` → ValueError. This converts the engine-side
    crash into a frontend 400.

  Layer 2 — GENESIS EDGE GUARD (the Genesis extra): a request-validation
    hook injected at the TOP of ``_create_chat_completion`` that inspects
    ``request.structured_outputs`` and returns an ``ErrorResponse`` (clean
    400 BadRequestError) BEFORE any engine work, so the reject happens at
    the gateway edge, not deep in the engine loop. Composes with the
    P68/P69 + PN16 hooks (all anchor on the ``# Streaming response`` pair
    and re-emit it).

Sub-contracts:
  1. Source-overlay patcher carries ONE required sub-patch: the two new
     guards appended after the empty-grammar guard. The anchor is the
     pin's empty-grammar guard block (byte-exact, count==1 in pristine).
  2. The two new guards land AFTER the empty-grammar guard and BEFORE the
     ``from vllm.v1.structured_output.backend_guidance import`` block.
  3. The patched file still compiles.
  4. Second apply() is idempotent (marker short-circuit → skipped).
  5. apply() self-skips on the #45346 merged form via drift markers
     (reason: upstream_merged) without touching the file.
  6. Drift markers do not collide with PN387's own replacement text or its
     Layer-6 marker line (tools/lint_drift_markers.py / PN369 contract)
     AND at least one marker is an exact substring of the merged form.
  7. Opt-in gate: with the dispatcher gate closed, apply() skips without
     touching the target.
  8. Edge-guard module: ``reject_request`` returns an ErrorResponse-like
     object for json_object=False and for an empty json string, and
     None for a healthy request / when disabled.
  9. Edge-guard wiring patcher anchors on the ``# Streaming response``
     pair (composes with P68/P69 + PN16) and injects an early-return on
     the guard.
 10. Pristine pin invariants (opportunistic): anchors unique, drift
     markers absent in the pristine tree.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# Unit tests patch fresh tmp files; the Layer-0 file cache must never
# satisfy apply() from a previous run's state.
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.serving import (  # noqa: E402
    pn387_reject_degenerate_structured_outputs as src_overlay,
)
from sndr.engines.vllm.patches.middleware import (  # noqa: E402
    edge_guard_reject_degenerate_structured_outputs as edge_wiring,
)
from sndr.engines.vllm.middleware import (  # noqa: E402
    reject_degenerate_structured_outputs as guard,
)

PIN_TREE = Path("/private/tmp/candidate_pin_current/vllm")


# ── Fixtures: pin-form anchor regions (byte-faithful copies) ─────────

# Pin g303916e93 form of the relevant slice of
# SamplingParams._validate_structured_outputs: the empty-grammar guard
# followed by the backend-import block. PN387 inserts between them.
PIN_SAMPLING_PARAMS = (
    "# fake sampling_params.py (pin g303916e93 form)\n"
    "class SamplingParams:\n"
    "    def _validate_structured_outputs(self, structured_outputs_config, tokenizer):\n"
    "        # Request content validation\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.choice, list)\n"
    "            and not self.structured_outputs.choice\n"
    "        ):\n"
    "            # It is invalid for choice to be an empty list\n"
    "            raise ValueError(\n"
    '                f"Choice \'{self.structured_outputs.choice}\' cannot be an empty list"  # noqa: E501\n'
    "            )\n"
    "        # Reject empty string grammar early to avoid engine-side crashes\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.grammar, str)\n"
    '            and self.structured_outputs.grammar.strip() == ""\n'
    "        ):\n"
    '            raise ValueError("structured_outputs.grammar cannot be an empty string")\n'
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n"
    "            has_guidance_unsupported_json_features,\n"
    "            validate_guidance_grammar,\n"
    "        )\n"
)

# #45346 merged form: the two new guards land right after the grammar
# guard. Exact text from `gh pr diff 45346` (2026-06-13).
MERGED_SAMPLING_PARAMS = PIN_SAMPLING_PARAMS.replace(
    '            raise ValueError("structured_outputs.grammar cannot be an empty string")\n'
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n",
    '            raise ValueError("structured_outputs.grammar cannot be an empty string")\n'
    "        # Reject empty string json schema early to avoid engine-side crashes\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.json, str)\n"
    '            and self.structured_outputs.json.strip() == ""\n'
    "        ):\n"
    '            raise ValueError("structured_outputs.json cannot be an empty string")\n'
    "        # Reject json_object=False early to avoid engine-side crashes\n"
    "        if self.structured_outputs.json_object is False:\n"
    "            raise ValueError(\n"
    '                "structured_outputs.json_object must be True if set; omit "\n'
    '                "structured_outputs to disable structured outputs"\n'
    "            )\n"
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n",
).replace("(pin g303916e93 form)", "(post-vllm#45346 merged form)")

# Pin-form of the _create_chat_completion top, for the edge-guard wiring.
PIN_SERVING = (
    "# fake chat_completion/serving.py (pin g303916e93 form)\n"
    "class OpenAIServingChat:\n"
    "    async def _create_chat_completion(self, request, raw_request=None):\n"
    "        # Streaming response\n"
    "        tokenizer = self.renderer.tokenizer\n"
    "        assert tokenizer is not None\n"
)


# ── Helpers ──────────────────────────────────────────────────────────


def _install_src_overlay(tmp_path, monkeypatch, text, *, with_edge=True):
    """Install the sampling_params target for the Layer-1 source overlay.

    Layer-1 apply() drives BOTH files atomically, so it also resolves the
    serving.py edge target. By default install a real serving.py too so the
    2-file MultiFilePatchTransaction path is exercised; pass
    ``with_edge=False`` to make the edge target unresolvable (Layer-1-only).
    """
    target = tmp_path / "sampling_params.py"
    target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(src_overlay, "resolve_vllm_file", lambda rel: str(target))
    monkeypatch.setattr(src_overlay, "vllm_install_root", lambda: str(tmp_path))
    if with_edge:
        edge_target = tmp_path / "serving.py"
        edge_target.write_text(PIN_SERVING, encoding="utf-8")
        monkeypatch.setattr(
            edge_wiring, "resolve_vllm_file", lambda rel: str(edge_target)
        )
        monkeypatch.setattr(edge_wiring, "vllm_install_root", lambda: str(tmp_path))
    else:
        monkeypatch.setattr(edge_wiring, "resolve_vllm_file", lambda rel: None)
    import sndr.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


def _install_edge_wiring(tmp_path, monkeypatch, text):
    target = tmp_path / "serving.py"
    target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(edge_wiring, "resolve_vllm_file", lambda rel: str(target))
    monkeypatch.setattr(edge_wiring, "vllm_install_root", lambda: str(tmp_path))
    import sndr.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


def _make_request(*, json_object=None, json=None, grammar=None, regex=None):
    """Mimic a ChatCompletionRequest carrying StructuredOutputsParams."""
    so = SimpleNamespace(
        json=json,
        regex=regex,
        choice=None,
        grammar=grammar,
        json_object=json_object,
        structural_tag=None,
    )
    return SimpleNamespace(structured_outputs=so)


# ── Layer 1: source-overlay patcher shape ────────────────────────────


class TestSourceOverlayShape:
    def test_single_required_subpatch(self, tmp_path, monkeypatch):
        _install_src_overlay(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        patcher = src_overlay._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert set(by_name) == {"pn387_degenerate_guards"}
        assert by_name["pn387_degenerate_guards"].required is True

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(src_overlay, "resolve_vllm_file", lambda rel: None)
        assert src_overlay._make_patcher() is None

    def test_module_documents_dos_and_env_flag(self):
        doc = src_overlay.__doc__ or ""
        assert "45346" in doc
        assert "EngineDeadError" in doc or "EngineCore" in doc
        src = Path(src_overlay.__file__).read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS" in src


class TestSourceOverlayApply:
    def test_apply_pin_form_inserts_both_guards(self, tmp_path, monkeypatch):
        target = _install_src_overlay(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        status, reason = src_overlay.apply()
        assert status == "applied", reason
        out = target.read_text(encoding="utf-8")
        # Both upstream guards present, exactly once each.
        assert out.count("structured_outputs.json cannot be an empty string") == 1
        assert out.count("structured_outputs.json_object must be True if set") == 1
        # Ordering: grammar guard -> json guard -> json_object guard ->
        # backend import.
        assert (
            out.index("structured_outputs.grammar cannot be an empty string")
            < out.index("structured_outputs.json cannot be an empty string")
            < out.index("structured_outputs.json_object must be True if set")
            < out.index("from vllm.v1.structured_output.backend_guidance import")
        )
        compile(out, str(target), "exec")

    def test_apply_commits_both_files_atomically(self, tmp_path, monkeypatch):
        """The single PN387 entrypoint applies BOTH the source overlay
        (sampling_params.py) and the gateway-edge wiring (serving.py) in
        one transaction."""
        target = _install_src_overlay(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        status, reason = src_overlay.apply()
        assert status == "applied", reason
        assert "2 layers" in reason
        # Source overlay landed.
        sp_out = target.read_text(encoding="utf-8")
        assert "structured_outputs.json cannot be an empty string" in sp_out
        # Edge wiring landed in serving.py.
        serving_out = (tmp_path / "serving.py").read_text(encoding="utf-8")
        assert "_genesis_pn387_reject_request(self, request)" in serving_out
        assert "return _genesis_pn387_error" in serving_out
        compile(serving_out, str(tmp_path / "serving.py"), "exec")

    def test_apply_layer1_only_when_edge_unresolvable(self, tmp_path, monkeypatch):
        """If serving.py is unresolvable, Layer 1 (the load-bearing DoS
        fix) still applies alone — the edge guard is defence-in-depth."""
        target = _install_src_overlay(
            tmp_path, monkeypatch, PIN_SAMPLING_PARAMS, with_edge=False
        )
        status, reason = src_overlay.apply()
        assert status == "applied", reason
        assert "Layer 1 only" in reason
        assert "structured_outputs.json cannot be an empty string" in (
            target.read_text(encoding="utf-8")
        )

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install_src_overlay(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        first, first_reason = src_overlay.apply()
        assert first == "applied", first_reason
        second, second_reason = src_overlay.apply()
        assert second == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_merged_form(self, tmp_path, monkeypatch):
        target = _install_src_overlay(
            tmp_path, monkeypatch, MERGED_SAMPLING_PARAMS
        )
        status, reason = src_overlay.apply()
        assert status == "skipped"
        assert "upstream" in reason.lower()
        assert target.read_text(encoding="utf-8") == MERGED_SAMPLING_PARAMS

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        target = tmp_path / "sampling_params.py"
        target.write_text(PIN_SAMPLING_PARAMS, encoding="utf-8")
        monkeypatch.setattr(src_overlay, "resolve_vllm_file", lambda rel: str(target))
        monkeypatch.setattr(src_overlay, "vllm_install_root", lambda: str(tmp_path))
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        status, _reason = src_overlay.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_SAMPLING_PARAMS


# ── Layer 1: drift-marker self-collision (PN369 contract) ────────────


class TestSourceOverlayDriftMarkers:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install_src_overlay(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        patcher = src_overlay._make_patcher()
        marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
        assert patcher.upstream_drift_markers, "drift markers must exist"
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement, (
                    f"drift marker {dm!r} collides with {sp.name} "
                    "replacement — would false-fire (PN369 class)"
                )
            assert dm not in marker_line

    def test_markers_fire_on_merged_form(self):
        """At least one non-banner drift marker must be an exact substring
        of #45346's merged form, so apply() self-skips once it lands."""
        non_banner = [
            dm for dm in src_overlay._DRIFT_MARKERS if not dm.startswith("[Genesis")
        ]
        assert non_banner, "must carry at least one upstream-form marker"
        assert any(dm in MERGED_SAMPLING_PARAMS for dm in non_banner)


# ── Layer 2: edge-guard logic ────────────────────────────────────────


class TestEdgeGuardLogic:
    def test_json_object_false_rejected(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS", "1"
        )
        serving = _FakeServing()
        req = _make_request(json_object=False)
        err = guard.reject_request(serving, req)
        assert err is not None
        assert serving.last_status_is_bad_request()

    def test_empty_json_string_rejected(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS", "1"
        )
        serving = _FakeServing()
        req = _make_request(json="")
        err = guard.reject_request(serving, req)
        assert err is not None

    def test_whitespace_only_json_rejected(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS", "1"
        )
        serving = _FakeServing()
        req = _make_request(json="   ")
        assert guard.reject_request(serving, req) is not None

    def test_healthy_request_passes(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS", "1"
        )
        serving = _FakeServing()
        # json_object=True is the legitimate selector — must pass.
        assert guard.reject_request(serving, _make_request(json_object=True)) is None
        # A non-empty json schema is fine.
        assert guard.reject_request(
            serving, _make_request(json='{"type":"object"}')
        ) is None
        # No structured_outputs at all → pass.
        assert guard.reject_request(
            serving, SimpleNamespace(structured_outputs=None)
        ) is None

    def test_disabled_by_default(self, monkeypatch):
        # Flag unset → guard must be a no-op even on a degenerate request.
        monkeypatch.delenv(
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS",
            raising=False,
        )
        serving = _FakeServing()
        assert guard.reject_request(serving, _make_request(json_object=False)) is None

    def test_never_raises_on_malformed_request(self, monkeypatch):
        monkeypatch.setenv(
            "GENESIS_ENABLE_PN387_REJECT_DEGENERATE_STRUCTURED_OUTPUTS", "1"
        )
        serving = _FakeServing()
        # A request without the expected attribute must not raise.
        assert guard.reject_request(serving, object()) is None


class _FakeServing:
    """Mimic the serving object's create_error_response contract."""

    def __init__(self):
        self._last = None

    def create_error_response(
        self, message, err_type="BadRequestError", status_code=400, param=None
    ):
        self._last = SimpleNamespace(
            message=message, err_type=err_type, status_code=status_code, param=param
        )
        return self._last

    def last_status_is_bad_request(self):
        return self._last is not None and self._last.err_type == "BadRequestError"


# ── Layer 2: edge-guard wiring shape ─────────────────────────────────


class TestEdgeWiringShape:
    def test_single_required_subpatch(self, tmp_path, monkeypatch):
        _install_edge_wiring(tmp_path, monkeypatch, PIN_SERVING)
        patcher = edge_wiring._make_patcher()
        assert patcher is not None
        assert len(patcher.sub_patches) == 1
        assert patcher.sub_patches[0].required is True

    def test_apply_injects_early_return(self, tmp_path, monkeypatch):
        target = _install_edge_wiring(tmp_path, monkeypatch, PIN_SERVING)
        status, reason = edge_wiring.apply()
        assert status == "applied", reason
        out = target.read_text(encoding="utf-8")
        # The hook calls reject_request and early-returns its ErrorResponse.
        assert "reject_request" in out
        assert "return " in out
        # The anchor pair is re-emitted so P68/P69 + PN16 still compose.
        assert out.count("# Streaming response\n") >= 1
        assert "tokenizer = self.renderer.tokenizer" in out
        compile(out, str(target), "exec")

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install_edge_wiring(tmp_path, monkeypatch, PIN_SERVING)
        first, first_reason = edge_wiring.apply()
        assert first == "applied", first_reason
        second, second_reason = edge_wiring.apply()
        assert second == "skipped"
        assert "already applied" in second_reason


# ── Pristine pin invariants (opportunistic) ──────────────────────────


@pytest.mark.skipif(
    not (PIN_TREE / "sampling_params.py").is_file(),
    reason="pristine pin tree not present on this machine",
)
class TestSourceOverlayAgainstPristine:
    def test_anchor_unique_and_post_fix_text_absent(self):
        src = (PIN_TREE / "sampling_params.py").read_text(encoding="utf-8")
        assert src.count(src_overlay.PN387_GUARDS_OLD) == 1
        assert src_overlay.PN387_GUARDS_NEW not in src
        assert "structured_outputs.json cannot be an empty string" not in src
        assert "structured_outputs.json_object must be True if set" not in src
        for dm in src_overlay._DRIFT_MARKERS:
            if dm.startswith("[Genesis"):
                continue
            assert dm not in src


@pytest.mark.skipif(
    not (PIN_TREE / "entrypoints/openai/chat_completion/serving.py").is_file(),
    reason="pristine pin tree not present on this machine",
)
class TestEdgeWiringAgainstPristine:
    def test_anchor_unique_in_serving(self):
        src = (
            PIN_TREE / "entrypoints/openai/chat_completion/serving.py"
        ).read_text(encoding="utf-8")
        assert src.count(edge_wiring.PN387_EDGE_ANCHOR) == 1
