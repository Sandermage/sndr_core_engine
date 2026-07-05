# SPDX-License-Identifier: Apache-2.0
"""PN523 — reject empty ``structural_tag``/``regex`` (vendor of vllm#47450).

Contract pinned here (TDD, written before the implementation).

Upstream bug (vllm#47450, PN387/#45346 successor class): the merged #45346
guards cover ``grammar``/``json``/``json_object`` but NOT
``structural_tag``/``regex``. ``StructuredOutputsParams`` counts constraint
fields with ``is not None``, so ``structural_tag=""`` passes the
exclusivity check, reaches the engine, and ``json.loads("")`` in
``backend_xgrammar.compile_grammar`` raises JSONDecodeError inside the
per-request-isolation-free EngineCore step loop -> EngineDeadError = a
single request remotely bricks the single-instance PROD engine (the
xgrammar tool-call path is live on ALL our lanes). Empty ``regex`` is a
degenerate no-constraint request rejected for consistency (upstream's own
rationale — xgrammar tolerates ``compile_regex("")``).

PN523 vendors BOTH #47450 guards into
``SamplingParams._validate_structured_outputs`` with the upstream
ValueError messages VERBATIM (so client-visible behavior is identical
when #47450 merges) but Genesis-reworded comments (so #47450's exact
comment lines stay usable as SELF_COLLISION-safe drift markers).

Sub-contracts:
  1. One required sub-patch anchored on the #45346 close block (the
     json_object raise closer + blank line + backend_guidance import) —
     byte-verified count==1 in pristine dev748 (2dfaae752, gh api).
  2. Guards land AFTER the json_object guard and BEFORE the
     backend_guidance import; upstream order (regex, then structural_tag).
  3. Patched file still compiles; vendored guard logic behaves like the
     upstream test matrix (tests/v1/structured_output/test_validation.py
     cases ported below).
  4. Second apply() is idempotent (marker short-circuit).
  5. apply() self-skips on the #47450 merged form via drift markers
     without touching the file.
  6. Drift markers don't collide with PN523's own emitted text (PN369
     contract) AND at least one fires on the merged form.
  7. Dispatcher gate closed -> apply() skips without touching the target.
  8. default_on=True in the registry (remote single-request DoS on the
     xgrammar tool-call path every lane uses; PN252 precedent).
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.serving import (  # noqa: E402
    pn523_reject_empty_structural_tag_regex as overlay,
)

# ── Fixture: pin-form anchor region (byte-faithful, dev748 2dfaae752) ─

PIN_SAMPLING_PARAMS = (
    "# fake sampling_params.py (pin 2dfaae752 form — post-#45346 native)\n"
    "class SamplingParams:\n"
    "    def _validate_structured_outputs(self, structured_outputs_config, tokenizer):\n"
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
    "        from vllm.v1.structured_output.backend_guidance import (\n"
    "            has_guidance_unsupported_json_features,\n"
    "            validate_guidance_grammar,\n"
    "        )\n"
)

# #47450 merged form (exact hunk from `gh pr diff 47450`, 2026-07-05):
# both guards land between the json_object raise and the backend import.
MERGED_SAMPLING_PARAMS = PIN_SAMPLING_PARAMS.replace(
    "            )\n"
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n",
    "            )\n"
    '        # Reject empty string regex early. xgrammar tolerates compile_regex("")\n'
    "        # without crashing, but an empty regex provides no constraint and is a\n"
    "        # degenerate request; reject at the API layer for consistency.\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.regex, str)\n"
    '            and self.structured_outputs.regex.strip() == ""\n'
    "        ):\n"
    '            raise ValueError("structured_outputs.regex cannot be an empty string")\n'
    "        # Reject empty string structural_tag early to avoid engine-side crashes.\n"
    "        # `get_structured_output_key` checks `is not None`, so an empty string\n"
    '        # would otherwise reach `json.loads("")` in `compile_grammar` and raise\n'
    "        # JSONDecodeError -> EngineDeadError.\n"
    "        if (\n"
    "            isinstance(self.structured_outputs.structural_tag, str)\n"
    '            and self.structured_outputs.structural_tag.strip() == ""\n'
    "        ):\n"
    "            raise ValueError(\n"
    '                "structured_outputs.structural_tag cannot be an empty string"\n'
    "            )\n"
    "\n"
    "        from vllm.v1.structured_output.backend_guidance import (\n",
).replace("(pin 2dfaae752 form — post-#45346 native)", "(post-vllm#47450 merged form)")


# ── Helpers ──────────────────────────────────────────────────────────


def _install(tmp_path, monkeypatch, text):
    target = tmp_path / "sampling_params.py"
    target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
    monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
    from sndr import dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return target


def _validate_with_patched_guards(patched_source: str, structured_outputs):
    """Execute the patched validation slice against a fake request.

    Runs the method body up to (excluding) the backend_guidance import so
    the vendored guards are exercised as real Python, not string-matched.
    """
    body = patched_source.split(
        "        from vllm.v1.structured_output.backend_guidance import (", 1
    )[0]
    # Keep only the method body lines (drop the fake header/class/def).
    lines = body.splitlines()
    start = next(
        i for i, ln in enumerate(lines) if "def _validate_structured_outputs" in ln
    )
    method_body = "\n".join(ln[8:] for ln in lines[start + 1 :] if ln.strip())
    self_ns = SimpleNamespace(structured_outputs=structured_outputs)
    exec(  # noqa: S102 - test-only execution of the patched slice
        compile(method_body, "<pn523-patched-slice>", "exec"),
        {"self": self_ns},
    )


def _so(**kw):
    base = {
        "json": None, "regex": None, "choice": None, "grammar": None,
        "json_object": None, "structural_tag": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_single_required_subpatch(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        patcher = overlay._make_patcher()
        assert patcher is not None
        by_name = {sp.name: sp for sp in patcher.sub_patches}
        assert set(by_name) == {"pn523_empty_structural_tag_regex_guards"}
        assert by_name["pn523_empty_structural_tag_regex_guards"].required is True

    def test_patcher_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: None)
        assert overlay._make_patcher() is None

    def test_module_documents_dos_and_env_flag(self):
        doc = overlay.__doc__ or ""
        assert "47450" in doc
        assert "EngineDeadError" in doc or "EngineCore" in doc
        src = Path(overlay.__file__).read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_PN523_REJECT_EMPTY_STRUCTURAL_TAG_REGEX" in src


# ── Apply behavior ───────────────────────────────────────────────────


class TestApply:
    def test_apply_inserts_both_guards_in_upstream_order(
        self, tmp_path, monkeypatch
    ):
        target = _install(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        status, reason = overlay.apply()
        assert status == "applied", reason
        out = target.read_text(encoding="utf-8")
        # Upstream ValueError messages verbatim, exactly once each.
        assert out.count("structured_outputs.regex cannot be an empty string") == 1
        assert (
            out.count("structured_outputs.structural_tag cannot be an empty string")
            == 1
        )
        # Ordering matches #47450: json_object guard -> regex guard ->
        # structural_tag guard -> backend import.
        assert (
            out.index("structured_outputs.json_object must be True if set")
            < out.index("structured_outputs.regex cannot be an empty string")
            < out.index("structured_outputs.structural_tag cannot be an empty string")
            < out.index("from vllm.v1.structured_output.backend_guidance import")
        )
        compile(out, str(target), "exec")

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        first, first_reason = overlay.apply()
        assert first == "applied", first_reason
        second, second_reason = overlay.apply()
        assert second == "skipped"
        assert "already applied" in second_reason

    def test_self_skips_on_merged_form(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, MERGED_SAMPLING_PARAMS)
        status, reason = overlay.apply()
        assert status == "skipped"
        assert "upstream" in reason.lower()
        assert target.read_text(encoding="utf-8") == MERGED_SAMPLING_PARAMS

    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        target = tmp_path / "sampling_params.py"
        target.write_text(PIN_SAMPLING_PARAMS, encoding="utf-8")
        monkeypatch.setattr(overlay, "resolve_vllm_file", lambda rel: str(target))
        monkeypatch.setattr(overlay, "vllm_install_root", lambda: str(tmp_path))
        from sndr import dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "gate closed")
        )
        status, _reason = overlay.apply()
        assert status == "skipped"
        assert target.read_text(encoding="utf-8") == PIN_SAMPLING_PARAMS


# ── Ported upstream test matrix (#47450 test_validation.py cases) ────


class TestVendoredGuardBehavior:
    """The vendored guards, run as real Python, must reproduce the
    upstream parametrized rejection matrix."""

    @pytest.fixture
    def patched(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        status, reason = overlay.apply()
        assert status == "applied", reason
        return target.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        ("so_kwargs", "match"),
        [
            ({"json_object": False}, "json_object must be True"),
            ({"json": ""}, "json cannot be an empty string"),
            ({"regex": ""}, "regex cannot be an empty string"),
            ({"structural_tag": ""}, "structural_tag cannot be an empty string"),
            ({"regex": "   "}, "regex cannot be an empty string"),
            ({"structural_tag": " \t"}, "structural_tag cannot be an empty string"),
        ],
    )
    def test_degenerate_structured_outputs_rejected(
        self, patched, so_kwargs, match
    ):
        with pytest.raises(ValueError, match=match):
            _validate_with_patched_guards(patched, _so(**so_kwargs))

    @pytest.mark.parametrize(
        "so_kwargs",
        [
            {"structural_tag": '{"type": "structural_tag", "format": {}}'},
            {"regex": "[a-z]+"},
            {"json_object": True},
            {},
        ],
    )
    def test_valid_inputs_pass(self, patched, so_kwargs):
        _validate_with_patched_guards(patched, _so(**so_kwargs))


# ── Drift markers (PN369 contract) ───────────────────────────────────


class TestDriftMarkers:
    def test_markers_not_substring_of_own_emitted_text(
        self, tmp_path, monkeypatch
    ):
        _install(tmp_path, monkeypatch, PIN_SAMPLING_PARAMS)
        patcher = overlay._make_patcher()
        marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
        assert patcher.upstream_drift_markers, "drift markers must exist"
        for dm in patcher.upstream_drift_markers:
            if dm.startswith("[Genesis"):
                continue
            for sp in patcher.sub_patches:
                assert dm not in sp.replacement, (
                    f"drift marker {dm!r} collides with {sp.name} replacement "
                    "— would false-fire (PN369 class)"
                )
            assert dm not in marker_line

    def test_markers_fire_on_merged_form(self):
        non_banner = [
            dm for dm in overlay._DRIFT_MARKERS if not dm.startswith("[Genesis")
        ]
        assert non_banner, "must carry at least one upstream-form marker"
        assert any(dm in MERGED_SAMPLING_PARAMS for dm in non_banner)


# ── Registry / env wiring ────────────────────────────────────────────


class TestWiring:
    def test_registry_entry(self):
        from sndr.dispatcher.registry import PATCH_REGISTRY
        body = PATCH_REGISTRY["PN523"]
        assert body["family"] == "serving"
        assert body["env_flag"] == (
            "GENESIS_ENABLE_PN523_REJECT_EMPTY_STRUCTURAL_TAG_REGEX"
        )
        # Remote single-request DoS on the xgrammar tool-call path every
        # lane uses -> auto-apply (PN252 security precedent).
        assert body["default_on"] is True
        assert body["upstream_pr"] == 47450
        assert body["upstream_pr_relationship"] == "backport"
        assert body["apply_module"] == (
            "sndr.engines.vllm.patches.serving."
            "pn523_reject_empty_structural_tag_regex"
        )
        rng = body["applies_to"]["vllm_version_range"]
        assert any("0.23.1rc1.dev748" in str(p) for p in rng), (
            "lower bound must be dev748 (anchor depends on the native "
            "#45346 close block verified there)"
        )

    def test_env_flag_attribute(self):
        from sndr.env import Flags
        assert (
            Flags.PN523_REJECT_EMPTY_STRUCTURAL_TAG_REGEX
            == "PN523_REJECT_EMPTY_STRUCTURAL_TAG_REGEX"
        )


# ── Opportunistic pristine-tree invariants ───────────────────────────


# TestPristinePinInvariants RETIRED (audit #14 full drain, 2026-07-06): it
# byte-checked the anchor against the macOS-only
# Linux rig — so it executed on NO host (permanent green-by-skip). PN523 is
# not recorded in the committed anchor_sot manifest (90/329 gap, audit
# #6/#21), so the byte-check cannot be migrated onto it. The anchor +
# vendored-guard + drift-marker + wiring contracts stay covered in CI by the
# synthetic classes above.
