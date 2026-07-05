# SPDX-License-Identifier: Apache-2.0
"""TDD for PN385 — forced-named empty-params tool schema → JSON object.

Vendor of upstream vllm#45290 ("Constrain forced named tool choice with
empty parameters to a JSON object"). The public
``get_json_schema_from_tools`` in ``vllm/tool_parsers/utils.py`` has two
forced-named branches (Responses ``ToolChoiceFunction`` and
ChatCompletion ``ChatCompletionNamedToolChoiceParam``) that return the
tool's ``parameters`` verbatim. For a no-arg tool (end_turn / noop /
handoff) that value is ``None`` (no guided decoding → free-form text) or
``{}`` (unconstrained schema → any JSON value, not necessarily an
object). Either way the model can emit a bare string/number as the tool
arguments, which our agent loop's object-shaped parser cannot consume —
the LIVE parse-500 on parameterless tools for the qwen3_xml (35B/27B)
and gemma4 (26B/31B) PROD families.

PN385 normalizes BOTH forced-named branches the same way the
``tool_choice="required"`` path already normalizes via
``_get_tool_schema_from_tool`` — a falsey ``parameters`` becomes
``{"type": "object", "properties": {}}``.

Because the real vllm tree is not importable on the CI/Mac host, these
tests drive the patch the way it runs in production: apply the
``TextPatcher`` to a temp copy of the pristine pin source, then exec the
patched module and exercise the two forced-named branches with the
double objects the upstream test (``TestForcedNamedToolChoiceEmptyParams``)
uses. The pre-patch source is asserted to FAIL the same contract, so
this is a genuine red→green TDD test, not a post-hoc checkmark.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sndr.engines.vllm.detection.guards import resolve_vllm_file
from tests.unit.anchor_sot._pin_manifest_assert import assert_anchor_recorded

# Target file resolved from the INSTALLED vllm tree (the same call
# ``PN385.apply()`` makes) — NOT a fixed ``/tmp`` pristine path that exists on
# no CI host. The behavioral RED/GREEN tests exec this real upstream source,
# so they run as a documented container-gate (rig / vllm container) and skip
# honestly when vllm is absent. The anchor byte-exactness itself runs in CI
# against the committed per-pin anchor manifest (see the manifest test below).
_TARGET_REL = "tool_parsers/utils.py"
_resolved = resolve_vllm_file(_TARGET_REL)
_PRISTINE_UTILS = Path(_resolved) if _resolved else None

requires_vllm_source = pytest.mark.skipif(
    _PRISTINE_UTILS is None or not _PRISTINE_UTILS.is_file(),
    reason=(
        "container-gate: tool_parsers/utils.py not resolvable in the installed "
        "vllm tree (needs a vllm host such as the rig / container)"
    ),
)


# ─── Minimal stand-ins for the vllm protocol classes ──────────────────
#
# get_json_schema_from_tools only does isinstance() dispatch on the
# tool_choice argument and reads ``.name`` / ``.function.name`` plus
# ``.parameters`` / ``.function.parameters``. We feed it tiny shims with
# the exact attribute shape so we never need torch or the real vllm
# package to exercise the two forced-named branches.


class _FunctionTool:
    """Stand-in for openai.types.responses.FunctionTool (Responses)."""

    def __init__(self, name, parameters):
        self.name = name
        self.parameters = parameters


class _ToolChoiceFunction:
    """Stand-in for openai.types.responses.ToolChoiceFunction."""

    def __init__(self, name):
        self.name = name


class _ChatFn:
    def __init__(self, name, parameters):
        self.name = name
        self.parameters = parameters


class _ChatCompletionToolsParam:
    """Stand-in for the ChatCompletion tool wrapper (has .function)."""

    def __init__(self, name, parameters):
        self.function = _ChatFn(name, parameters)


class _ChatNamedFn:
    def __init__(self, name):
        self.name = name


class _ChatCompletionNamedToolChoiceParam:
    """Stand-in for ChatCompletionNamedToolChoiceParam (has .function)."""

    def __init__(self, name):
        self.function = _ChatNamedFn(name)


def _load_get_json_schema_from_tools(utils_path: Path):
    """Parse ``utils.py``, keep ONLY the pure-python schema functions we
    exercise (the two forced-named branches live in
    ``get_json_schema_from_tools`` plus the helpers it transitively
    calls), and exec them in a namespace where the protocol-class symbols
    the ``isinstance`` checks reference resolve to our shims.

    We use AST selection rather than line-stripping so multi-line
    parenthesized imports (vllm/openai/partial_json_parser — none
    importable here) are dropped cleanly without breaking indentation.
    The pythonic-AST tool-call helpers further down the file are excluded
    entirely; they are never reached by these tests.
    """
    import ast as _ast
    import types

    src = utils_path.read_text(encoding="utf-8")
    tree = _ast.parse(src)

    # Functions on the forced-named code path (and their callees). These
    # are all module-level, pure-python, and self-contained once the
    # isinstance() guard symbols are injected via the namespace below.
    wanted = {
        "get_json_schema_from_tools",
        "_get_tool_schema_from_tool",
        "_extract_tool_info",
        "_get_json_schema_from_tools",
        "_get_tool_schema_defs",
        # PN385 may factor a normalization helper; keep any private name
        # that starts with the conventional prefix so the selection is
        # robust to the exact helper the patch introduces.
    }
    kept_nodes = [
        node
        for node in tree.body
        if isinstance(node, _ast.FunctionDef)
        and (
            node.name in wanted
            or node.name.startswith(("_params", "_normalize"))
        )
    ]
    module_ast = _ast.Module(body=kept_nodes, type_ignores=[])

    ns: dict = {
        "FunctionTool": _FunctionTool,
        "ToolChoiceFunction": _ToolChoiceFunction,
        "ChatCompletionToolsParam": _ChatCompletionToolsParam,
        "ChatCompletionNamedToolChoiceParam": _ChatCompletionNamedToolChoiceParam,
        "Tool": object,
        "Any": object,
    }
    mod = types.ModuleType("pn385_utils_under_test")
    mod.__dict__.update(ns)
    exec(  # noqa: S102 — exec of vendored pin source in an isolated ns
        compile(module_ast, str(utils_path), "exec"), mod.__dict__
    )
    return mod.__dict__["get_json_schema_from_tools"]


def _patched_copy(tmp_path: Path) -> Path:
    """Copy the pristine utils.py into tmp and apply PN385 to it."""
    from sndr.engines.vllm.patches.tool_parsing import (
        pn385_forced_named_empty_params as pn385,
    )

    dst = tmp_path / "utils.py"
    shutil.copy2(_PRISTINE_UTILS, dst)

    patcher = pn385.build_patcher_for_target(str(dst))
    assert patcher is not None
    result, failure = patcher.apply()
    from sndr.kernel.text_patch import TextPatchResult

    assert result == TextPatchResult.APPLIED, (
        f"PN385 did not apply cleanly: {result} / {failure}"
    )
    return dst


_EMPTY_OBJECT = {"type": "object", "properties": {}}


# ─── Anchor byte-exactness: current-pin manifest (runs in CI) ─────────
# Both forced-named anchors are recorded in the committed per-pin anchor
# manifest, so tying the live patcher anchor CONSTANTS to the recorded
# pristine bytes RUNS on every CI host — no vllm install or /tmp tree
# needed. Replaces the uniqueness half of the old pristine byte-check that
# green-by-skipped on ``/private/tmp/candidate_pin_current``.


def test_pn385_anchors_recorded_in_current_pin_manifest():
    from sndr.engines.vllm.patches.tool_parsing import (
        pn385_forced_named_empty_params as pn385,
    )

    assert_anchor_recorded(
        "PN385", "pn385_responses_forced_named", pn385.PN385_RESPONSES_OLD
    )
    assert_anchor_recorded(
        "PN385", "pn385_chatcompletion_forced_named", pn385.PN385_CHAT_OLD
    )


# ─── RED baseline: pristine source must FAIL the contract ─────────────


@requires_vllm_source
@pytest.mark.parametrize("params", [None, {}])
def test_pristine_responses_branch_is_unconstrained(params):
    """Pre-patch, the Responses forced-named branch returns the raw
    (falsey) parameters — NOT a JSON object. Locks the bug in place so
    the green test below is meaningful."""
    fn = _load_get_json_schema_from_tools(_PRISTINE_UTILS)
    tool = _FunctionTool(name="ping", parameters=params)
    choice = _ToolChoiceFunction(name="ping")
    schema = fn(choice, [tool])
    assert schema != _EMPTY_OBJECT


@requires_vllm_source
@pytest.mark.parametrize("params", [None, {}])
def test_pristine_chat_branch_is_unconstrained(params):
    fn = _load_get_json_schema_from_tools(_PRISTINE_UTILS)
    tool = _ChatCompletionToolsParam(name="ping", parameters=params)
    choice = _ChatCompletionNamedToolChoiceParam(name="ping")
    schema = fn(choice, [tool])
    assert schema != _EMPTY_OBJECT


# ─── GREEN: after PN385 both branches constrain to a JSON object ──────


@requires_vllm_source
@pytest.mark.parametrize("params", [None, {}])
def test_patched_responses_branch_constrains_object(tmp_path, params):
    patched = _patched_copy(tmp_path)
    fn = _load_get_json_schema_from_tools(patched)
    tool = _FunctionTool(name="ping", parameters=params)
    choice = _ToolChoiceFunction(name="ping")
    schema = fn(choice, [tool])
    assert schema == _EMPTY_OBJECT


@requires_vllm_source
@pytest.mark.parametrize("params", [None, {}])
def test_patched_chat_branch_constrains_object(tmp_path, params):
    patched = _patched_copy(tmp_path)
    fn = _load_get_json_schema_from_tools(patched)
    tool = _ChatCompletionToolsParam(name="ping", parameters=params)
    choice = _ChatCompletionNamedToolChoiceParam(name="ping")
    schema = fn(choice, [tool])
    assert schema == _EMPTY_OBJECT


@requires_vllm_source
def test_patched_non_empty_params_preserved(tmp_path):
    """A real (non-falsey) parameters schema must pass through unchanged
    on both forced-named branches — PN385 only touches the falsey case."""
    patched = _patched_copy(tmp_path)
    fn = _load_get_json_schema_from_tools(patched)
    real = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }
    chat_tool = _ChatCompletionToolsParam(name="get_weather", parameters=real)
    chat_choice = _ChatCompletionNamedToolChoiceParam(name="get_weather")
    assert fn(chat_choice, [chat_tool]) == real

    resp_tool = _FunctionTool(name="get_weather", parameters=real)
    resp_choice = _ToolChoiceFunction(name="get_weather")
    assert fn(resp_choice, [resp_tool]) == real


# ─── Idempotency + drift-marker self-collision contract ───────────────


@requires_vllm_source
def test_apply_is_idempotent(tmp_path):
    """Second apply() on an already-patched file returns IDEMPOTENT,
    never a double-edit."""
    from sndr.engines.vllm.patches.tool_parsing import (
        pn385_forced_named_empty_params as pn385,
    )
    from sndr.kernel.text_patch import TextPatchResult

    patched = _patched_copy(tmp_path)
    patcher2 = pn385.build_patcher_for_target(str(patched))
    result, _ = patcher2.apply()
    assert result == TextPatchResult.IDEMPOTENT


def test_drift_markers_do_not_self_collide():
    """PN369 self-collision rule: no upstream drift marker may be a
    substring of the patch's own emitted replacement text or its
    idempotency marker line."""
    from sndr.engines.vllm.patches.tool_parsing import (
        pn385_forced_named_empty_params as pn385,
    )

    # Marker / drift-marker / sub-patch inspection needs only the patcher's
    # own metadata (not the target file contents), so build against the rel
    # path — this test runs in CI without a resolvable vllm source.
    patcher = pn385.build_patcher_for_target(_TARGET_REL)
    assert patcher is not None
    marker_line = f"# [Genesis wiring marker: {patcher.marker}]\n"
    for dm in patcher.upstream_drift_markers:
        assert dm not in marker_line, (
            f"drift marker self-collides with idempotency marker line: {dm!r}"
        )
        for sp in patcher.sub_patches:
            assert dm not in sp.replacement, (
                f"drift marker self-collides with sub-patch "
                f"{sp.name!r} replacement: {dm!r}"
            )
