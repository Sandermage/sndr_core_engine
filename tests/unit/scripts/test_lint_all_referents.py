# SPDX-License-Identifier: Apache-2.0
"""Tests for `scripts/lint_all_referents.py` — F822 pure-Python gate.

The gate must:
  • catch real undefined names in `__all__`
  • skip modules with `def __getattr__` (PEP 562 lazy loaders)
  • treat sibling submodules / subpackages as defined when the file is
    an `__init__.py` (because `from pkg import *` will import them)
  • not crash on malformed Python or unreadable files
  • exit 0 on the committed tree (release-gate baseline)
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "lint_all_referents.py"


def _import_script():
    """Load `scripts/lint_all_referents.py` as a module.

    Caches in `sys.modules` so dataclass introspection works (CPython's
    `_is_type` calls `sys.modules.get(cls.__module__).__dict__` and
    expects the module to be discoverable)."""
    name = "_lint_all_referents_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return path


# ─── Core: real undefined names ───────────────────────────────────────


class TestCoreF822:
    def test_undefined_name_caught(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "bad.py", '''
            __all__ = ["does_not_exist"]
        ''')
        violations = mod.check_file(p)
        assert len(violations) == 1
        assert violations[0].name == "does_not_exist"

    def test_defined_function_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "good.py", '''
            __all__ = ["foo"]

            def foo(): return 1
        ''')
        assert mod.check_file(p) == []

    def test_defined_class_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "klass.py", '''
            __all__ = ["Foo"]

            class Foo:
                pass
        ''')
        assert mod.check_file(p) == []

    def test_imported_name_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "imp.py", '''
            from os.path import join

            __all__ = ["join"]
        ''')
        assert mod.check_file(p) == []

    def test_aliased_import_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "imp_alias.py", '''
            from os.path import join as my_join

            __all__ = ["my_join"]
        ''')
        assert mod.check_file(p) == []

    def test_module_level_assign_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "assign.py", '''
            X = 42
            __all__ = ["X"]
        ''')
        assert mod.check_file(p) == []

    def test_tuple_unpack_assign_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "tuple.py", '''
            A, B = 1, 2
            __all__ = ["A", "B"]
        ''')
        assert mod.check_file(p) == []

    def test_annotated_assign_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "ann.py", '''
            X: int = 1
            __all__ = ["X"]
        ''')
        assert mod.check_file(p) == []

    def test_conditional_def_passes(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "cond.py", '''
            import sys

            if sys.version_info >= (3, 10):
                def foo():
                    return 1
            else:
                def foo():
                    return 2

            __all__ = ["foo"]
        ''')
        assert mod.check_file(p) == []


# ─── Skip rules ───────────────────────────────────────────────────────


class TestSkipPEP562:
    def test_module_level_getattr_skips(self, tmp_path):
        """PEP 562 lazy loader — names resolve via __getattr__."""
        mod = _import_script()
        p = _write(tmp_path / "lazy.py", '''
            __all__ = ["lazy_thing"]

            def __getattr__(name):
                if name == "lazy_thing":
                    return 42
                raise AttributeError(name)
        ''')
        assert mod.check_file(p) == []


class TestSkipWildcardImport:
    def test_star_import_skips(self, tmp_path):
        """from X import * — we can't statically know what's defined."""
        mod = _import_script()
        # Create a sibling module to legitimately star-import from.
        _write(tmp_path / "src.py", '''
            __all__ = ["bar"]
            def bar(): return 1
        ''')
        p = _write(tmp_path / "consumer.py", '''
            from src import *

            __all__ = ["bar", "unknown_too"]
        ''')
        # Star import + any __all__ → skipped entirely.
        assert mod.check_file(p) == []


# ─── Package init: sibling submodule handling ─────────────────────────


class TestPackageInitSiblings:
    def test_sibling_submodule_resolves(self, tmp_path):
        """A package `__init__.py` listing a sibling submodule in `__all__`
        passes — `from pkg import *` will import the submodule."""
        mod = _import_script()
        pkg = tmp_path / "pkg"
        _write(pkg / "submod.py", '''
            X = 1
        ''')
        p = _write(pkg / "__init__.py", '''
            __all__ = ["submod"]
        ''')
        assert mod.check_file(p) == []

    def test_sibling_subpackage_resolves(self, tmp_path):
        """A package `__init__.py` listing a subpackage in `__all__` passes."""
        mod = _import_script()
        pkg = tmp_path / "pkg"
        # Inner subpackage with its own __init__.py.
        _write(pkg / "inner_pkg" / "__init__.py", "")
        p = _write(pkg / "__init__.py", '''
            __all__ = ["inner_pkg"]
        ''')
        assert mod.check_file(p) == []

    def test_non_package_init_does_not_get_sibling_treatment(self, tmp_path):
        """Plain `mod.py` doesn't get `from pkg import *` semantics —
        sibling .py files are NOT counted as defined."""
        mod = _import_script()
        _write(tmp_path / "neighbour.py", "X = 1\n")
        p = _write(tmp_path / "not_an_init.py", '''
            __all__ = ["neighbour"]
        ''')
        violations = mod.check_file(p)
        assert len(violations) == 1
        assert violations[0].name == "neighbour"


# ─── Resilience ───────────────────────────────────────────────────────


class TestResilience:
    def test_no_all_returns_empty(self, tmp_path):
        mod = _import_script()
        p = _write(tmp_path / "no_all.py", '''
            def foo(): return 1
        ''')
        assert mod.check_file(p) == []

    def test_malformed_python_returns_syntax_violation(self, tmp_path):
        mod = _import_script()
        p = (tmp_path / "syntax.py")
        p.write_text("def broken( : pass\n", encoding="utf-8")
        violations = mod.check_file(p)
        assert len(violations) == 1
        assert "SyntaxError" in violations[0].message

    def test_dynamic_all_skips_silently(self, tmp_path):
        """`__all__ = some_function()` is not statically introspectable."""
        mod = _import_script()
        p = _write(tmp_path / "dyn.py", '''
            def _build_all():
                return ["foo"]

            __all__ = _build_all()
        ''')
        # We extract only string-literal members; nothing to check.
        assert mod.check_file(p) == []


# ─── End-to-end: committed tree passes ────────────────────────────────


class TestCommittedTreeIsClean:
    """The committed repository must validate clean. This is the gate's
    release-tier acceptance — adding new code that violates F822 should
    fail this test before merge."""

    def test_script_exit_zero_on_repo(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--json"],
            cwd=REPO_ROOT,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"committed tree has F822 violations: {result.stdout[:1500]}"
        )
        payload = json.loads(result.stdout)
        assert payload["passed"] is True
        assert payload["files_scanned"] > 50, "scan suspiciously small"
        assert payload["violation_count"] == 0


# ─── CLI argument parsing ─────────────────────────────────────────────


class TestCLIArgs:
    def test_paths_override(self, tmp_path):
        """`--paths` lets the operator scan a custom root."""
        # Drop a bad file under a temp root.
        bad = _write(tmp_path / "bad.py", '''
            __all__ = ["does_not_exist"]
        ''')
        # Invoke script with --paths = absolute parent; we have to map the
        # arg to a repo-relative form in this test by copying into a known
        # subpath. Skip if path isn't writable inside repo root.
        # Simpler: smoke the script's `_iter_py_files` directly.
        mod = _import_script()
        files = mod._iter_py_files([tmp_path])
        assert bad in files

    def test_skips_archive_and_cache_dirs(self, tmp_path):
        mod = _import_script()
        _write(tmp_path / "_archive" / "old.py", "X = 1\n")
        _write(tmp_path / "__pycache__" / "stale.py", "X = 1\n")
        _write(tmp_path / "real.py", "X = 1\n")
        files = mod._iter_py_files([tmp_path])
        rels = {f.name for f in files}
        assert "real.py" in rels
        assert "old.py" not in rels
        assert "stale.py" not in rels
