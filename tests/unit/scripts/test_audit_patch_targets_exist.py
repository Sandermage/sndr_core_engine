# SPDX-License-Identifier: Apache-2.0
"""Tests for the stranded-patch detector (scripts/audit_patch_targets_exist.py).

The detector answers: does a text-patch still have a target file to patch on the
current pin? A patch whose target upstream renamed/removed is silently inert —
the exact P12 class of failure — and the anchor-drift watcher cannot see it. The
key correctness property under test: a patch is only "fully stranded" when EVERY
static target is missing, so a patch that also targets a path that DOES exist
(e.g. the GDN patches that fall back to the new mamba/gdn/ split) is NOT flagged.

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "audit_patch_targets_exist", REPO / "scripts/audit_patch_targets_exist.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestModuleTargets:
    def test_extracts_string_literals(self):
        m = _load()
        src = 'x = resolve_vllm_file("reasoning/qwen3_reasoning_parser.py")\n'
        assert m._module_targets(ast.parse(src)) == ["reasoning/qwen3_reasoning_parser.py"]

    def test_resolves_module_level_constant(self):
        m = _load()
        src = '_T = "tool_parsers/qwen3coder_tool_parser.py"\ny = resolve_vllm_file(_T)\n'
        assert m._module_targets(ast.parse(src)) == ["tool_parsers/qwen3coder_tool_parser.py"]

    def test_dynamic_arg_becomes_sentinel(self):
        m = _load()
        src = 'y = resolve_vllm_file(f"a/{name}.py")\n'
        assert "<dynamic>" in m._module_targets(ast.parse(src))

    def test_multi_target_collects_all(self):
        m = _load()
        src = ('a = resolve_vllm_file("old/path.py")\n'
               'b = resolve_vllm_file("new/path.py")\n')
        got = m._module_targets(ast.parse(src))
        assert set(got) == {"old/path.py", "new/path.py"}


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


class TestScan:
    def test_all_targets_missing_is_fully_stranded(self, tmp_path):
        m = _load()
        patches = tmp_path / "patches"
        _write(patches, "gone.py", 'x = resolve_vllm_file("a/gone.py")\n')
        vllm = tmp_path / "vllm"
        vllm.mkdir()
        r = m.scan(patches, vllm)
        assert [stem for stem, _ in r["fully"]] == ["gone"]

    def test_fallback_target_present_is_not_fully_stranded(self, tmp_path):
        """A patch that ALSO targets a path that exists (the GDN fallback
        pattern) must NOT be flagged fully stranded — only partial."""
        m = _load()
        patches = tmp_path / "patches"
        _write(patches, "gdn.py",
               'a = resolve_vllm_file("mamba/gdn_linear_attn.py")\n'
               'b = resolve_vllm_file("mamba/gdn/qwen_gdn_linear_attn.py")\n')
        vllm = tmp_path / "vllm"
        _write(vllm, "mamba/gdn/qwen_gdn_linear_attn.py", "# exists\n")
        r = m.scan(patches, vllm)
        assert not r["fully"]
        assert [stem for stem, *_ in r["partial"]] == ["gdn"]

    def test_dynamic_target_prevents_fully_stranded_verdict(self, tmp_path):
        m = _load()
        patches = tmp_path / "patches"
        _write(patches, "dyn.py",
               'a = resolve_vllm_file("a/gone.py")\n'
               'b = resolve_vllm_file(some_var)\n')
        vllm = tmp_path / "vllm"
        vllm.mkdir()
        r = m.scan(patches, vllm)
        # has a dynamic target we can't check -> never declared fully stranded
        assert not r["fully"]

    def test_all_present_not_flagged(self, tmp_path):
        m = _load()
        patches = tmp_path / "patches"
        _write(patches, "ok.py", 'x = resolve_vllm_file("a/here.py")\n')
        vllm = tmp_path / "vllm"
        _write(vllm, "a/here.py", "# exists\n")
        r = m.scan(patches, vllm)
        assert not r["fully"]
        assert not r["partial"]

    def test_known_stranded_allowlist_excuses(self, tmp_path):
        m = _load()
        patches = tmp_path / "patches"
        _write(patches, "excused.py", 'x = resolve_vllm_file("a/gone.py")\n')
        vllm = tmp_path / "vllm"
        vllm.mkdir()
        m.KNOWN_STRANDED["excused"] = "test allowlist"
        try:
            r = m.scan(patches, vllm)
            assert not r["fully"]
        finally:
            del m.KNOWN_STRANDED["excused"]


class TestPinOutOfRange:
    def test_pin_above_upper_cap_is_out_of_range(self):
        m = _load()
        # dev714 (0.23.1rc1) is above a <0.23.0 cap -> out of range (excused)
        assert m._pin_out_of_range("0.23.1rc1.dev714+g09663abde", (">=0.20.0", "<0.23.0")) is True

    def test_pin_inside_range_is_not_out(self):
        m = _load()
        assert m._pin_out_of_range("0.23.1rc1.dev714+g09663abde", (">=0.20.0", "<0.24.0")) is False

    def test_no_range_is_not_out(self):
        m = _load()
        assert m._pin_out_of_range("0.23.1rc1.dev714+g09663abde", None) is False

    def test_unparseable_pin_is_conservatively_not_excused(self):
        m = _load()
        assert m._pin_out_of_range("not-a-version", (">=0.20.0", "<0.23.0")) is False
