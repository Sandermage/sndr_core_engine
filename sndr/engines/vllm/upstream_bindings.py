# SPDX-License-Identifier: Apache-2.0
"""Static upstream-binding resolver for class-rebind / wiring patches.

The anchor-drift checker verifies *text-patch* patches by counting their
anchors in the pristine upstream tree. But roughly half the registry is
class-rebind / monkeypatch / middleware wiring with no text anchor — those
were reported ``needs_fixture`` ("covered by runtime self-test"), i.e. a
symbol they bind could be renamed or removed upstream and only blow up at
boot (the G4_09 × dev672 class of surprise).

Most of those wiring patches, however, IMPORT the upstream symbols they
rebind — commonly inside a function, e.g.::

    def apply():
        from vllm.model_executor.models import gemma4
        cls = getattr(gemma4, "Gemma4ForCausalLM")

Those imports are statically extractable (AST, at any nesting depth) and
resolvable against the pristine tree with zero import side-effects. This
module turns them into a real static drift signal:

  * every `vllm.*` import in the patch resolves → ``ok``
  * a module or symbol the patch imports is absent in the tree → ``symbol_drift``
    (genuine, previously-invisible drift — upstream moved/renamed it)
  * the patch binds nothing statically (fully reflective) → ``no_static_bindings``
    (honestly still runtime-only; never a false ``ok``)

Reflective `getattr(mod, runtime_string)` bindings cannot be resolved here —
a patch that wants those checked precisely declares an ``_upstream_bindings()``
accessor (see ``iter_declared_bindings``), the class-rebind analogue of the
``_parser_targets`` convention.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Binding:
    """One upstream symbol a patch depends on. `symbol` is None for a bare
    ``import vllm.x`` (only the module is asserted)."""
    module: str          # dotted, e.g. "vllm.model_executor.models.gemma4"
    symbol: str | None   # imported name, or None


def extract_vllm_imports(source: str) -> list[Binding]:
    """AST-extract every ``vllm.*`` import in `source`, at ANY nesting depth
    (module top-level, inside functions/classes/try-blocks). Non-vllm imports
    are ignored. Returns a de-duplicated, order-stable list. A syntax error
    yields ``[]`` (the caller's import-failed path already covers that)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    seen: set[tuple[str, str | None]] = set()
    out: list[Binding] = []

    def _add(module: str, symbol: str | None) -> None:
        key = (module, symbol)
        if key not in seen:
            seen.add(key)
            out.append(Binding(module=module, symbol=symbol))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Skip relative imports (node.level > 0) — never upstream.
            mod = node.module or ""
            if node.level or not (mod == "vllm" or mod.startswith("vllm.")):
                continue
            for alias in node.names:
                if alias.name == "*":
                    _add(mod, None)  # star import → assert the module only
                else:
                    _add(mod, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "vllm" or alias.name.startswith("vllm."):
                    _add(alias.name, None)
    return out


def _module_file(tree_root: Path, dotted: str) -> Path | None:
    """Map ``vllm.a.b`` → ``<tree>/vllm/a/b.py`` or ``.../a/b/__init__.py``."""
    rel = dotted.replace(".", "/")
    file_py = tree_root / (rel + ".py")
    if file_py.is_file():
        return file_py
    file_pkg = tree_root / rel / "__init__.py"
    if file_pkg.is_file():
        return file_pkg
    return None


def _symbol_defined(path: Path, symbol: str) -> bool:
    """True iff `symbol` is a top-level def / class / assignment / import in
    `path` (AST — no import side-effects). Covers the forms an upstream module
    exposes: class, function, module-level binding, or a re-export."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol:
                return True
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == symbol:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                return True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if name == symbol:
                    return True
    return False


def resolve_binding(tree_root: Path, module: str, symbol: str | None) -> str:
    """Resolve one binding against the pristine tree.

    Returns ``"ok"`` | ``"module_missing"`` | ``"symbol_missing"``. When the
    imported name is itself a submodule (``from vllm.a import b`` where
    ``vllm/a/b.py`` exists) that also counts as resolved.
    """
    src = _module_file(tree_root, module)
    if src is None:
        return "module_missing"
    if symbol is None:
        return "ok"
    if _symbol_defined(src, symbol):
        return "ok"
    # `from vllm.a import b` where b is a submodule/subpackage, not a name.
    if _module_file(tree_root, f"{module}.{symbol}") is not None:
        return "ok"
    return "symbol_missing"


def check_module_bindings(source: str, tree_root: Path) -> dict:
    """Aggregate binding check for one patch module's source.

    - ``no_static_bindings`` — no ``vllm.*`` imports found (honestly runtime-only)
    - ``symbol_drift``       — at least one binding does not resolve
    - ``ok``                 — every binding resolves
    """
    binds = extract_vllm_imports(source)
    if not binds:
        return {"status": "no_static_bindings", "checked": 0, "unresolved": []}
    unresolved: list[str] = []
    for b in binds:
        verdict = resolve_binding(tree_root, b.module, b.symbol)
        if verdict != "ok":
            sym = f".{b.symbol}" if b.symbol else ""
            unresolved.append(f"{b.module}{sym} [{verdict}]")
    if unresolved:
        return {"status": "symbol_drift", "checked": len(binds), "unresolved": unresolved}
    return {"status": "ok", "checked": len(binds), "unresolved": []}


def iter_declared_bindings(mod) -> list[Binding]:
    """Opt-in precise-binding contract: a wiring patch may expose
    ``_upstream_bindings()`` returning ``(module, symbol)`` tuples (or
    ``Binding`` objects) for reflective bindings its imports don't reveal —
    the class-rebind analogue of ``_parser_targets``. Returns ``[]`` when the
    module declares none."""
    fn = getattr(mod, "_upstream_bindings", None)
    if fn is None:
        return []
    try:
        raw = fn()
    except Exception:  # noqa: BLE001 — treat a raising accessor as "none declared"
        return []
    out: list[Binding] = []
    for item in raw or []:
        if isinstance(item, Binding):
            out.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 1:
            out.append(Binding(module=str(item[0]), symbol=(str(item[1]) if len(item) > 1 and item[1] else None)))
    return out
