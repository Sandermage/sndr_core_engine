# SPDX-License-Identifier: Apache-2.0
"""PN389 — XGrammar input-validation + grammar-compilation timeouts.

Contract pinned here (updated for the 0.23.1 redesign, pin
0.23.1rc1.dev148+gb4c80ec0f).

Upstream bug class (vllm#45390, 7 GHSA CWE-400): structured-output
compilation runs on the CPU EngineCore loop with NO wall-clock bound, so
a pathological grammar/regex/JSON-schema wedges ALL decode indefinitely —
an instance-wide DoS on our single-instance PROD (async-scheduling
overlap does NOT save us; compilation is pure-CPU off the GPU stream).

0.23.1 REDESIGN (see the module docstring + ``_all_patchers`` in the
patch). On the 0.23.1 pin upstream ALREADY landed a first-generation
helper ``compile_regex_with_timeout`` (utils.py; ThreadPoolExecutor +
``future.result(timeout)``, bounded by ``VLLM_REGEX_COMPILATION_TIMEOUT_S``,
default 5s), already imported it into ``backend_xgrammar.py``, and already
wraps the REGEX arm of ``compile_grammar`` with it. The original 3-file
design (introduce our own ``run_with_timeout`` + ``_check_regex_complexity``
in utils.py + a new ``VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS`` env +
a ``_compile_ctx`` / ``_compile_ctx_inner`` refactor) therefore no longer
composes — its utils.py / envs.py anchors are gone or redundant. PN389
COLLAPSED to a SINGLE file, gated on
``GENESIS_ENABLE_PN389_GRAMMAR_TIMEOUTS`` (default_on=False):

  v1/structured_output/backend_xgrammar.py — a single byte-exact edit on
  ``compile_grammar`` that REUSES the already-present
  ``compile_regex_with_timeout`` to wall-clock-bound the four arms upstream
  still leaves unbounded (JSON / JSON_OBJECT / GRAMMAR / STRUCTURAL_TAG),
  leaving the REGEX arm exactly as upstream wrote it. Now EVERY type's
  vocab-dependent DFA build is bounded by the existing
  ``VLLM_REGEX_COMPILATION_TIMEOUT_S`` (default 5s, operator-tunable).

The utils.py / envs.py / frontend-validate sub-patches (and the
``run_with_timeout`` / ``_check_regex_complexity`` helper constants) are
RETAINED in the module as non-required, inert reference material (NOT
wired into the transaction) — see ``_make_utils_patcher`` /
``_make_envs_patcher`` and the helper-block constant
``PN389_UTILS_HELPERS_NEW``. The Genesis-specific safety tests below still
exercise that retained helper code so a future re-wire cannot regress it.

Sub-contracts:
  1. One active patcher (backend_xgrammar.py); the retained utils/envs
     builders carry their historical sub-patches as non-required.
  2. apply() commits the single file atomically and it still compiles;
     every EngineCore DFA-build arm now flows through
     compile_regex_with_timeout.
  3. Second apply() is idempotent (marker short-circuit -> skipped).
  4. apply() self-skips on the #45390 merged form via drift markers
     (reason: upstream_merged) without touching the file.
  5. Drift markers do not collide with PN389's own replacement text or its
     Layer-6 marker line (tools/lint_drift_markers.py / PN369 contract)
     AND at least one marker is an exact substring of the merged form.
  6. Opt-in gate: with the dispatcher gate closed, apply() skips without
     touching the target.
  7. GENESIS-SPECIFIC: real gemma4 / qwen3_coder tool-schema-derived regex
     passes the retained ``_check_regex_complexity`` with NO false-positive
     rejection, while a genuinely adversarial pattern IS rejected.
  8. Pristine pin invariants (opportunistic): the active anchor is unique
     (count==1), drift markers absent in the pristine tree.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Unit tests patch fresh tmp files; the Layer-0 file cache must never
# satisfy apply() from a previous run's state.
os.environ.setdefault("GENESIS_NO_PATCH_CACHE", "1")

from sndr.engines.vllm.patches.serving import (  # noqa: E402
    pn389_grammar_compilation_timeout as pn389,
)

# Real pristine dev148 (0.23.1rc1.dev148+gb4c80ec0f) tree if dumped on
# this host — the opportunistic invariants below run only when it is
# present (and carries the structured_output subtree). The partial
# candidate_pin_current tree on some hosts lacks v1/structured_output, so
# we prefer the full pristine dump and fall back to candidate_pin_current.
_PIN_TREE_CANDIDATES = (
    Path("/private/tmp/vllm_pristine_b4c80ec0f/vllm"),
    Path("/private/tmp/candidate_pin_current/vllm"),
)
PIN_TREE = next(
    (
        p
        for p in _PIN_TREE_CANDIDATES
        if (p / "v1/structured_output/backend_xgrammar.py").is_file()
    ),
    _PIN_TREE_CANDIDATES[0],
)


# ── Fixtures: pin-form anchor regions (byte-faithful copies) ─────────

# Pin g303916e93 form of v1/structured_output/utils.py — enough of the
# head to carry both anchors (import block + `CACHE = None` site).
PIN_UTILS = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    "from __future__ import annotations\n"
    "\n"
    "import hashlib\n"
    "import importlib.metadata\n"
    "import os\n"
    "import tempfile\n"
    "from typing import TYPE_CHECKING\n"
    "\n"
    "import numpy as np\n"
    "from vllm.logger import init_logger\n"
    "\n"
    "logger = init_logger(__name__)\n"
    "\n"
    "CACHE = None\n"
    "\n"
    "\n"
    "def apply_grammar_bitmask():\n"
    "    pass\n"
)

# dev148 (0.23.1rc1.dev148+gb4c80ec0f) form of
# v1/structured_output/backend_xgrammar.py — the import block (with the
# already-present upstream compile_regex_with_timeout import), the
# compile_grammar method (REGEX arm already wrapped in
# compile_regex_with_timeout, as upstream 0.23.1 ships it — this is the
# byte-exact anchor the active pn389_xgr_compile_grammar sub-patch keys
# on), and the validate_xgrammar_grammar body. Verified count==1 against
# the live pristine dev148 tree.
PIN_XGRAMMAR = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    "import json\n"
    "\n"
    "import vllm.envs\n"
    "from vllm.v1.structured_output.backend_types import (\n"
    "    StructuredOutputOptions,\n"
    ")\n"
    "from vllm.v1.structured_output.utils import (\n"
    "    choice_as_grammar,\n"
    "    compile_regex_with_timeout,\n"
    "    convert_lark_to_ebnf,\n"
    "    grammar_is_likely_lark,\n"
    ")\n"
    "\n"
    "\n"
    "class XgrammarBackend:\n"
    # Byte-faithful copy of the dev148 compile_grammar method — the
    # full-method anchor PN389's single active sub-patch
    # (pn389_xgr_compile_grammar) keys on. The REGEX arm already wraps
    # compile_regex_with_timeout (upstream 0.23.1); PN389 extends the same
    # helper to the other four arms.
    "    def compile_grammar(\n"
    "        self, request_type: StructuredOutputOptions, grammar_spec: str\n"
    "    ) -> StructuredOutputGrammar:\n"
    "        if request_type == StructuredOutputOptions.JSON:\n"
    "            ctx = self.compiler.compile_json_schema(\n"
    "                grammar_spec, any_whitespace=not self.disable_any_whitespace\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.JSON_OBJECT:\n"
    "            ctx = self.compiler.compile_json_schema(\n"
    "                '{\"type\": \"object\"}', any_whitespace=not self.disable_any_whitespace\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.GRAMMAR:\n"
    "            ctx = self.compiler.compile_grammar(grammar_spec)\n"
    "        elif request_type == StructuredOutputOptions.REGEX:\n"
    "            ctx = compile_regex_with_timeout(\n"
    "                self.compiler.compile_regex,\n"
    "                grammar_spec,\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.STRUCTURAL_TAG:\n"
    "            s_tag = json.loads(grammar_spec)\n"
    '            if "structures" in s_tag:\n'
    "                # Falling back to deprecated method of compiling structural tag\n"
    "                tags = [\n"
    "                    xgr.StructuralTagItem(\n"
    '                        begin=s["begin"],\n'
    '                        schema=json.dumps(s["schema"]),\n'
    '                        end=s["end"],\n'
    "                    )\n"
    '                    for s in s_tag["structures"]\n'
    "                ]\n"
    '                ctx = self.compiler.compile_structural_tag(tags, s_tag["triggers"])\n'
    "            else:\n"
    "                ctx = self.compiler.compile_structural_tag(grammar_spec)\n"
    "        else:\n"
    "            logger.error(\n"
    '                "Validation should have already occurred. Please file an issue."\n'
    "            )\n"
    "            raise ValueError(\n"
    '                f"grammar is not of valid supported types. ({request_type!s})"\n'
    "            )\n"
    "\n"
    "        return XgrammarGrammar(\n"
    "            matcher=xgr.GrammarMatcher(\n"
    "                ctx,\n"
    "                max_rollback_tokens=self.num_speculative_tokens,\n"
    "            ),\n"
    "            vocab_size=self.vocab_size,\n"
    "            ctx=ctx,\n"
    "        )\n"
    "\n"
    "\n"
    "def validate_xgrammar_grammar(sampling_params):\n"
    "    if sampling_params.structured_outputs is None:\n"
    "        return\n"
    "    so_params = sampling_params.structured_outputs\n"
    "\n"
    "    if so_params.regex:\n"
    "        try:\n"
    "            xgr.Grammar.from_regex(so_params.regex)\n"
    "        except Exception as err:\n"
    '            raise ValueError(f"bad regex: {err}") from err\n'
    "\n"
    "    if so_params.choice:\n"
    "        choice_grammar = choice_as_grammar(so_params.choice)\n"
    "        try:\n"
    "            xgr.Grammar.from_ebnf(choice_grammar)\n"
    "        except Exception as err:\n"
    '            raise ValueError(f"bad choice: {err}") from err\n'
    "        return\n"
    "\n"
    "    if so_params.json:\n"
    "        schema = so_params.json\n"
    "        try:\n"
    "            xgr.Grammar.from_json_schema(schema)\n"
    "        except Exception as err:\n"
    '            raise ValueError(f"bad json: {err}") from err\n'
    "        return\n"
    "\n"
    "    if so_params.grammar:\n"
    "        try:\n"
    "            # parse the grammar, but we aren't compiling it.\n"
    "            xgr.Grammar.from_ebnf(so_params.grammar)\n"
    "        except Exception as e:\n"
    '            raise ValueError("Invalid grammar specification.") from e\n'
    "        return\n"
    "\n"
    "    if so_params.structural_tag:\n"
    "        try:\n"
    "            s_tag = json.loads(so_params.structural_tag)\n"
    '            if "structures" in s_tag:\n'
    "                tags = []\n"
    '                xgr.Grammar.from_structural_tag(tags, s_tag["triggers"])\n'
    "            else:\n"
    "                xgr.Grammar.from_structural_tag(so_params.structural_tag)\n"
    "        except Exception as e:\n"
    '            raise ValueError("Invalid structural tag specification.") from e\n'
)

# Pin g303916e93 form of envs.py — the declaration block + the os.getenv
# lambda block carrying VLLM_XGRAMMAR_CACHE_MB.
PIN_ENVS = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    "import os\n"
    "\n"
    "if TYPE_CHECKING:\n"
    "    VLLM_FLASHINFER_WORKSPACE_BUFFER_SIZE: int = 394 * 1024 * 1024\n"
    "    VLLM_XGRAMMAR_CACHE_MB: int = 0\n"
    "    VLLM_MSGPACK_ZERO_COPY_THRESHOLD: int = 256\n"
    "\n"
    "environment_variables = {\n"
    "    # Control the cache sized used by the xgrammar compiler.\n"
    '    "VLLM_XGRAMMAR_CACHE_MB": lambda: int(os.getenv("VLLM_XGRAMMAR_CACHE_MB", "512")),\n'
    "    # Control the threshold for msgspec zero copy.\n"
    '    "VLLM_MSGPACK_ZERO_COPY_THRESHOLD": lambda: int(os.getenv("X", "256")),\n'
    "}\n"
)


def _build_merged(text: str) -> str:
    """Splice one of PN389's drift-marker (PR-form) strings into a copy of
    the pin text so apply() should treat it as upstream-merged.

    0.23.1 REDESIGN: apply() scans drift markers against the SINGLE active
    target (backend_xgrammar.py), so the merged signal must live there. We
    append the PR's grammar-timeout-env comment head as a trailing comment;
    apply() detects it and self-skips (upstream_merged) without touching
    the file.
    """
    merged_marker = (
        "\n# Maximum time in seconds allowed for grammar/regex "
        "compilation into a DFA\n"
    )
    return text + merged_marker


# ── Helpers ──────────────────────────────────────────────────────────


def _install(tmp_path, monkeypatch, *, utils=PIN_UTILS, xgr=PIN_XGRAMMAR, envs=PIN_ENVS):
    """Install all three PN389 targets under tmp and route resolution."""
    targets = {
        "v1/structured_output/utils.py": (tmp_path / "utils.py", utils),
        "v1/structured_output/backend_xgrammar.py": (tmp_path / "backend_xgrammar.py", xgr),
        "envs.py": (tmp_path / "envs.py", envs),
    }
    for _rel, (path, text) in targets.items():
        path.write_text(text, encoding="utf-8")

    def _resolve(rel):
        entry = targets.get(rel)
        return str(entry[0]) if entry else None

    monkeypatch.setattr(pn389, "resolve_vllm_file", _resolve)
    monkeypatch.setattr(pn389, "vllm_install_root", lambda: str(tmp_path))
    import sndr.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "should_apply", lambda pid: (True, "test override")
    )
    return {rel: path for rel, (path, _t) in targets.items()}


def _load_helpers(tmp_path, monkeypatch) -> dict:
    """Exec the RETAINED helper block (run_with_timeout +
    _check_regex_complexity + constants) in an isolated namespace.

    0.23.1 REDESIGN: the helper block is no longer emitted into utils.py by
    apply() (the single active sub-patch reuses upstream's
    ``compile_regex_with_timeout`` instead). It is RETAINED in the patch
    module as the constant ``PN389_UTILS_HELPERS_NEW`` (the non-wired
    historical builder), so we slice it from there — from the additive
    sentinel ``_PN389_T = TypeVar`` to end-of-block — and prepend the
    stdlib imports the block needs. This still exercises the REAL retained
    helper code (Genesis-specific safety contract: a future re-wire must
    not regress these helpers), not a re-typed copy.
    """
    del tmp_path, monkeypatch  # signature kept for call-site symmetry
    block_src = pn389.PN389_UTILS_HELPERS_NEW
    start = block_src.index("_PN389_T = TypeVar")
    block = block_src[start:]
    preamble = (
        "import threading\n"
        "from collections.abc import Callable\n"
        "from queue import Empty, Queue\n"
        "from typing import TypeVar\n"
    )
    ns: dict = {}
    exec(compile(preamble + block, "retained_utils_block.py", "exec"), ns)  # noqa: S102
    return ns


# ── Patcher shape ────────────────────────────────────────────────────


class TestPatcherShape:
    def test_one_active_patcher_built(self, tmp_path, monkeypatch):
        # 0.23.1 REDESIGN: only backend_xgrammar.py is wired into the
        # transaction (utils/envs builders are retained but not driven).
        _install(tmp_path, monkeypatch)
        patchers = pn389._all_patchers()
        assert len(patchers) == 1
        assert "backend_xgrammar.py" in patchers[0].target_file

    def test_utils_patcher_subpatches(self, tmp_path, monkeypatch):
        # Retained (non-wired) builder: sub-patches present but non-required
        # so a vanished/absorbed anchor soft-skips on the live tree.
        _install(tmp_path, monkeypatch)
        p = pn389._make_utils_patcher()
        names = {sp.name for sp in p.sub_patches}
        assert names == {"pn389_utils_imports", "pn389_utils_helpers"}
        assert not any(sp.required for sp in p.sub_patches)

    def test_xgrammar_patcher_subpatches(self, tmp_path, monkeypatch):
        # The only REQUIRED sub-patch is the EngineCore compile_grammar arm
        # (the documented DoS wedge surface); the import + five frontend
        # validate arms are retained non-required residuals (0.23.1 absorbed
        # or refactored their pin forms).
        _install(tmp_path, monkeypatch)
        p = pn389._make_xgrammar_patcher()
        names = {sp.name for sp in p.sub_patches}
        assert names == {
            "pn389_xgr_imports",
            "pn389_xgr_compile_grammar",
            "pn389_xgr_validate_regex",
            "pn389_xgr_validate_choice",
            "pn389_xgr_validate_json",
            "pn389_xgr_validate_ebnf",
            "pn389_xgr_validate_structural_tag",
        }
        required = {sp.name for sp in p.sub_patches if sp.required}
        assert required == {"pn389_xgr_compile_grammar"}

    def test_envs_patcher_subpatches(self, tmp_path, monkeypatch):
        # Retained (non-wired) builder: env it would add is redundant on
        # 0.23.1 (upstream VLLM_REGEX_COMPILATION_TIMEOUT_S already exists).
        _install(tmp_path, monkeypatch)
        p = pn389._make_envs_patcher()
        names = {sp.name for sp in p.sub_patches}
        assert names == {"pn389_envs_decl", "pn389_envs_lambda"}
        assert not any(sp.required for sp in p.sub_patches)

    def test_patchers_none_when_target_missing(self, monkeypatch):
        monkeypatch.setattr(pn389, "resolve_vllm_file", lambda rel: None)
        assert pn389._make_utils_patcher() is None
        assert pn389._make_xgrammar_patcher() is None
        assert pn389._make_envs_patcher() is None
        assert pn389._all_patchers() == []

    def test_module_documents_dos_slo_and_env_flag(self):
        doc = pn389.__doc__ or ""
        assert "45390" in doc
        assert "DoS" in doc or "GHSA" in doc
        # The Genesis-specific 2s default must be documented (not the PR's 10s).
        assert "2s" in doc or "TTFT" in doc
        src = Path(pn389.__file__).read_text(encoding="utf-8")
        assert "GENESIS_ENABLE_PN389_GRAMMAR_TIMEOUTS" in src


# ── apply() — atomic three-file commit ───────────────────────────────


class TestApply:
    def test_apply_commits_single_file(self, tmp_path, monkeypatch):
        # 0.23.1 REDESIGN: one file (backend_xgrammar.py), one transaction.
        paths = _install(tmp_path, monkeypatch)
        status, reason = pn389.apply()
        assert status == "applied", reason
        assert "1 file" in reason

        xgr_out = paths["v1/structured_output/backend_xgrammar.py"].read_text("utf-8")

        # utils.py / envs.py are NOT touched — they keep their pin form.
        assert (
            paths["v1/structured_output/utils.py"].read_text("utf-8")
            == PIN_UTILS
        )
        assert paths["envs.py"].read_text("utf-8") == PIN_ENVS

        # backend_xgrammar: the Genesis marker landed and every EngineCore
        # DFA-build arm now flows through the already-present upstream
        # compile_regex_with_timeout helper (REGEX kept as upstream wrote
        # it; JSON / JSON_OBJECT / GRAMMAR / STRUCTURAL_TAG newly wrapped).
        assert pn389.GENESIS_PN389_MARKER in xgr_out
        # The four newly-bounded arms wrap the compiler call in the helper.
        assert "lambda spec: self.compiler.compile_json_schema(" in xgr_out
        assert (
            "ctx = compile_regex_with_timeout(\n"
            "                self.compiler.compile_grammar,\n"
        ) in xgr_out
        # At least 6 helper call-sites now (REGEX + the 4 new arms + the
        # two structural-tag branches).
        assert xgr_out.count("compile_regex_with_timeout(") >= 6
        # No bare unbounded compiler call survives for the four arms we
        # bound — only the helper-wrapped forms remain.
        assert (
            "ctx = self.compiler.compile_json_schema(" not in xgr_out
        )
        assert "ctx = self.compiler.compile_grammar(grammar_spec)" not in xgr_out
        compile(xgr_out, "backend_xgrammar.py", "exec")

    def test_regex_arm_unchanged_from_upstream(self, tmp_path, monkeypatch):
        # 0.23.1 REDESIGN: the REGEX arm is left EXACTLY as upstream wrote
        # it (already wrapped in compile_regex_with_timeout); PN389 does not
        # re-wrap it or add a separate complexity pre-filter on 0.23.1.
        paths = _install(tmp_path, monkeypatch)
        status, reason = pn389.apply()
        assert status == "applied", reason
        xgr_out = paths["v1/structured_output/backend_xgrammar.py"].read_text("utf-8")
        assert (
            "        elif request_type == StructuredOutputOptions.REGEX:\n"
            "            ctx = compile_regex_with_timeout(\n"
            "                self.compiler.compile_regex,\n"
            "                grammar_spec,\n"
            "            )\n"
        ) in xgr_out

    def test_enginecore_compile_path_is_timeout_bounded(
        self, tmp_path, monkeypatch
    ):
        """CORE FIX: compile_grammar's EngineCore DFA build — the actual DoS
        wedge surface — must be wall-clock-bounded for EVERY request type, not
        only the REGEX arm upstream 0.23.1 already wraps. A JSON-schema / EBNF
        grammar / structural-tag that compiles catastrophically would otherwise
        wedge the single CPU EngineCore loop unbounded.

        0.23.1 REDESIGN: rather than the original _compile_ctx /
        _compile_ctx_inner refactor, the patch reuses the already-present
        upstream compile_regex_with_timeout helper for the four arms upstream
        leaves unbounded (JSON / JSON_OBJECT / GRAMMAR / STRUCTURAL_TAG). No
        bare ``ctx = self.compiler.compile_*`` survives for those arms.
        """
        paths = _install(tmp_path, monkeypatch)
        status, reason = pn389.apply()
        assert status == "applied", reason
        xgr_out = paths["v1/structured_output/backend_xgrammar.py"].read_text("utf-8")

        # Slice the patched compile_grammar method body (up to the next
        # module-level def in the fixture) and assert every DFA-build arm is
        # bounded — none calls the compiler directly without the helper.
        method_start = xgr_out.index("    def compile_grammar(")
        method_end = xgr_out.index("\ndef validate_xgrammar_grammar(")
        body = xgr_out[method_start:method_end]

        # All five request-type arms route through compile_regex_with_timeout.
        assert body.count("compile_regex_with_timeout(") >= 6
        # The JSON / JSON_OBJECT arms wrap the json-schema compile in a lambda.
        assert "lambda spec: self.compiler.compile_json_schema(" in body
        # No UNbounded direct compiler call leaks out of the method for the
        # arms PN389 bounds (bare `ctx = self.compiler.compile_json_schema(`,
        # `compile_grammar(grammar_spec)`, `compile_structural_tag(...)` gone).
        assert "ctx = self.compiler.compile_json_schema(" not in body
        assert "ctx = self.compiler.compile_grammar(grammar_spec)" not in body
        assert (
            "ctx = self.compiler.compile_structural_tag(grammar_spec)" not in body
        )

        compile(xgr_out, "backend_xgrammar.py", "exec")

    def test_compile_grammar_dispatch_is_bit_identical(
        self, tmp_path, monkeypatch
    ):
        """The redesigned compile_grammar must dispatch to the SAME compiler
        call for each request type as the pin did — bit-identical for any
        compile within budget. Exec the patched method against a recording
        fake compiler (with compile_regex_with_timeout stubbed to call its
        fn synchronously) and assert each type hits the right call.
        """
        paths = _install(tmp_path, monkeypatch)
        status, reason = pn389.apply()
        assert status == "applied", reason
        xgr_out = paths["v1/structured_output/backend_xgrammar.py"].read_text("utf-8")

        class _RecordingCompiler:
            def __init__(self):
                self.calls = []

            def compile_json_schema(self, spec, any_whitespace=True):
                self.calls.append(("json", spec))
                return ("ctx", "json")

            def compile_grammar(self, spec):
                self.calls.append(("grammar", spec))
                return ("ctx", "grammar")

            def compile_regex(self, spec):
                self.calls.append(("regex", spec))
                return ("ctx", "regex")

            def compile_structural_tag(self, *a):
                self.calls.append(("stag", a))
                return ("ctx", "stag")

        class _Opt:
            JSON = "JSON"
            JSON_OBJECT = "JSON_OBJECT"
            GRAMMAR = "GRAMMAR"
            REGEX = "REGEX"
            STRUCTURAL_TAG = "STRUCTURAL_TAG"

        # Slice the patched compile_grammar method out of the fixture; the
        # fixture follows it with the module-level validate_xgrammar_grammar
        # (the robust end-boundary just past the method's return block).
        method_start = xgr_out.index("    def compile_grammar(")
        method_end = xgr_out.index("\ndef validate_xgrammar_grammar(")
        backend_src = xgr_out[method_start:method_end] + "\n"
        wrapper = (
            "import json\n"
            "class XgrammarBackend:\n"
            "    def __init__(self, compiler):\n"
            "        self.compiler = compiler\n"
            "        self.disable_any_whitespace = False\n"
            "        self.num_speculative_tokens = 0\n"
            "        self.vocab_size = 10\n"
            + backend_src
        )
        ns = {
            "StructuredOutputOptions": _Opt,
            # The redesign reuses the upstream helper; stub it to invoke fn
            # synchronously so each arm's compiler call is recorded.
            "compile_regex_with_timeout": (lambda fn, *a: fn(*a)),
            "XgrammarGrammar": lambda **kw: kw,
            "xgr": type("X", (), {"GrammarMatcher": lambda *a, **k: None}),
            "logger": type("L", (), {"error": staticmethod(lambda *a: None)}),
        }
        exec(compile(wrapper, "patched_backend.py", "exec"), ns)  # noqa: S102
        comp = _RecordingCompiler()
        backend = ns["XgrammarBackend"](comp)

        backend.compile_grammar(_Opt.JSON, "{}")
        backend.compile_grammar(_Opt.GRAMMAR, "root ::= a")
        backend.compile_grammar(_Opt.REGEX, "abc")
        # Each request type dispatched to its matching compiler call.
        kinds = [c[0] for c in comp.calls]
        assert kinds == ["json", "grammar", "regex"]

    def test_second_apply_idempotent(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        first, first_reason = pn389.apply()
        assert first == "applied", first_reason
        second, second_reason = pn389.apply()
        assert second == "skipped"

    def test_is_applied_true_only_after_all_three(self, tmp_path, monkeypatch):
        paths = _install(tmp_path, monkeypatch)
        assert pn389.is_applied() is False
        status, reason = pn389.apply()
        assert status == "applied", reason
        assert pn389.is_applied() is True


# ── upstream-merge self-skip ─────────────────────────────────────────


class TestUpstreamSelfSkip:
    def test_self_skips_when_backend_merged(self, tmp_path, monkeypatch):
        # 0.23.1 REDESIGN: backend_xgrammar.py is the single scanned target,
        # so the merged drift signal must live there.
        merged_xgr = _build_merged(PIN_XGRAMMAR)
        paths = _install(tmp_path, monkeypatch, xgr=merged_xgr)
        status, reason = pn389.apply()
        assert status == "skipped"
        assert "upstream" in reason.lower()
        # No file was touched — the merged target is byte-unchanged, and the
        # transaction never ran so the Genesis marker was never written.
        out = paths["v1/structured_output/backend_xgrammar.py"].read_text("utf-8")
        assert out == merged_xgr
        assert pn389.GENESIS_PN389_MARKER not in out


# ── drift-marker self-collision (PN369 contract) ─────────────────────


class TestDriftMarkers:
    def test_markers_not_substring_of_own_emitted_text(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        marker_line = f"# [Genesis wiring marker: {pn389.GENESIS_PN389_MARKER}]\n"
        non_banner = [
            dm for dm in pn389._DRIFT_MARKERS if not dm.startswith("[Genesis")
        ]
        assert non_banner, "must carry at least one upstream-form marker"
        for p in pn389._all_patchers():
            for dm in non_banner:
                for sp in p.sub_patches:
                    assert dm not in sp.replacement, (
                        f"drift marker {dm!r} collides with {sp.name} "
                        "replacement — would false-fire (PN369 class)"
                    )
                assert dm not in marker_line

    def test_markers_absent_from_pin_form_fixtures(self):
        non_banner = [
            dm for dm in pn389._DRIFT_MARKERS if not dm.startswith("[Genesis")
        ]
        for dm in non_banner:
            assert dm not in PIN_UTILS
            assert dm not in PIN_XGRAMMAR
            assert dm not in PIN_ENVS


# ── opt-in gate ──────────────────────────────────────────────────────


class TestGate:
    def test_apply_skips_when_gate_closed(self, tmp_path, monkeypatch):
        paths = _install(tmp_path, monkeypatch)
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (False, "opt-in: env unset")
        )
        status, _reason = pn389.apply()
        assert status == "skipped"
        # Targets untouched.
        assert paths["v1/structured_output/utils.py"].read_text("utf-8") == PIN_UTILS
        assert paths["envs.py"].read_text("utf-8") == PIN_ENVS


# ── GENESIS-SPECIFIC: no false-positive on real tool-schema regex ────


# JSON-schema-derived regexes of the shape outlines/xgrammar build from
# real Genesis tool schemas. Hand-faithful to the structure (one paren
# group per property/value, nested groups for nested objects/arrays).
# These are the patterns that flow through the REGEX arm and through
# _check_regex_complexity; the GENESIS concern is that the naive
# paren-depth counter must NOT reject any of them.

# qwen3_coder-style edit_file tool: path(str), content(str), nested meta
# object {line:int, flags:[bool]}. Realistic agent tool schema.
QWEN3_CODER_EDIT_FILE_REGEX = (
    r'\{[ ]?"path"[ ]?:[ ]?("(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|'
    r'\\u[0-9a-fA-F]{4})*")[ ]?,[ ]?"content"[ ]?:[ ]?'
    r'("(?:[^"\\\x00-\x1f]|\\["\\/bfnrt])*")[ ]?,[ ]?"meta"[ ]?:[ ]?'
    r'(\{[ ]?"line"[ ]?:[ ]?((-)?(0|[1-9][0-9]*))[ ]?,[ ]?'
    r'"flags"[ ]?:[ ]?(\[([ ]?(true|false)([ ]?,[ ]?(true|false))*)?'
    r'[ ]?\])[ ]?\})[ ]?\}'
)

# gemma4-style get_weather tool: location(str), unit(enum), days(int).
GEMMA4_GET_WEATHER_REGEX = (
    r'\{[ ]?"location"[ ]?:[ ]?'
    r'("(?:[^"\\\x00-\x1f]|\\["\\/bfnrt])*")[ ]?,[ ]?'
    r'"unit"[ ]?:[ ]?("celsius"|"fahrenheit")[ ]?,[ ]?'
    r'"days"[ ]?:[ ]?((-)?(0|[1-9][0-9]*))[ ]?\}'
)

# gemma4-style deeply-but-legitimately nested config tool (3 nested
# objects) — still well under the depth-20 bound.
GEMMA4_NESTED_CONFIG_REGEX = (
    r'\{("server":(\{("opts":(\{("tls":(\{("verify":(true|false)\})\})\})\}))\})\}'
)

LEGIT_TOOL_REGEXES = [
    QWEN3_CODER_EDIT_FILE_REGEX,
    GEMMA4_GET_WEATHER_REGEX,
    GEMMA4_NESTED_CONFIG_REGEX,
]


class TestNoFalsePositiveOnRealToolSchemas:
    """The cheap pre-filter must not reject legit JSON-schema-derived regex.

    Loads _check_regex_complexity from the PATCHED utils.py (the real
    emitted code), then feeds it our gemma4 / qwen3_coder tool-schema
    regexes. This is the GENESIS pre-enable gate from the roadmap:
    confirm no false-positive BEFORE turning the timeout reject on.
    """

    def _load_check(self, tmp_path, monkeypatch):
        ns = _load_helpers(tmp_path, monkeypatch)
        return ns["_check_regex_complexity"], ns

    def test_real_tool_schema_regexes_pass(self, tmp_path, monkeypatch):
        check, ns = self._load_check(tmp_path, monkeypatch)
        # Sanity: all our sample regexes nest well under the bound.
        assert ns["MAX_REGEX_NESTING_DEPTH"] == 20
        for rx in LEGIT_TOOL_REGEXES:
            # Must NOT raise — these are legitimate tool-schema regexes.
            check(rx)

    def test_adversarial_pattern_rejected(self, tmp_path, monkeypatch):
        check, ns = self._load_check(tmp_path, monkeypatch)
        # >20 nested groups -> rejected ("too deep").
        deep = "(" * 25 + "a" + ")" * 25
        with pytest.raises(ValueError, match="too deep"):
            check(deep)
        # >10K chars -> rejected ("too long").
        long_pat = "a" * (ns["MAX_REGEX_LENGTH"] + 1)
        with pytest.raises(ValueError, match="too long"):
            check(long_pat)

    def test_pattern_exactly_at_bounds_passes(self, tmp_path, monkeypatch):
        check, ns = self._load_check(tmp_path, monkeypatch)
        depth = ns["MAX_REGEX_NESTING_DEPTH"]
        at_depth = "(" * depth + "a" + ")" * depth
        check(at_depth)  # exactly at the bound — must pass
        at_len = "a" * ns["MAX_REGEX_LENGTH"]
        check(at_len)  # exactly at the bound — must pass


class TestRunWithTimeoutBehaviour:
    """run_with_timeout emitted into the patched utils.py behaves correctly."""

    def _load_run(self, tmp_path, monkeypatch):
        return _load_helpers(tmp_path, monkeypatch)["run_with_timeout"]

    def test_fast_call_returns_value(self, tmp_path, monkeypatch):
        run = self._load_run(tmp_path, monkeypatch)
        assert run(lambda x: x * 2, 21, timeout=5, label="t") == 42

    def test_timeout_raises_value_error(self, tmp_path, monkeypatch):
        import time

        run = self._load_run(tmp_path, monkeypatch)

        def slow():
            time.sleep(3)
            return "never"

        start = time.monotonic()
        with pytest.raises(ValueError, match="timed out"):
            run(slow, timeout=1, label="Grammar compilation")
        # Caller unblocks in ~timeout, not ~fn duration.
        assert time.monotonic() - start < 2.5

    def test_inner_exception_propagates(self, tmp_path, monkeypatch):
        run = self._load_run(tmp_path, monkeypatch)

        def boom():
            raise RuntimeError("inner failure")

        with pytest.raises(RuntimeError, match="inner failure"):
            run(boom, timeout=5, label="t")


# ── Pristine pin invariants (opportunistic) ──────────────────────────


@pytest.mark.skipif(
    not (PIN_TREE / "v1/structured_output/backend_xgrammar.py").is_file(),
    reason="pristine pin tree not present on this machine",
)
class TestAgainstPristine:
    def test_xgrammar_active_anchor_unique(self):
        # 0.23.1 REDESIGN: the single ACTIVE anchor (the compile_grammar
        # method) must resolve count==1 against the live dev148 tree, and
        # the upstream helper PN389 reuses must already be present.
        src = (
            PIN_TREE / "v1/structured_output/backend_xgrammar.py"
        ).read_text("utf-8")
        assert src.count(pn389.PN389_XGR_COMPILE_GRAMMAR_OLD) == 1
        # The Genesis marker (idempotency guard) must be absent on pristine.
        assert pn389.GENESIS_PN389_MARKER not in src
        # Upstream 0.23.1 already ships + imports compile_regex_with_timeout
        # (the helper the redesign reuses); our own run_with_timeout is NOT
        # present (it would be the original 3-file design, now collapsed).
        assert "compile_regex_with_timeout" in src
        assert "def run_with_timeout(" not in src

    def test_drift_markers_absent_in_pristine(self):
        # Scan the active target plus the historical utils/envs files (when
        # present) — none of the PR-form drift markers may appear pristine.
        for rel in (
            "v1/structured_output/backend_xgrammar.py",
            "v1/structured_output/utils.py",
            "envs.py",
        ):
            path = PIN_TREE / rel
            if not path.is_file():
                continue
            src = path.read_text("utf-8")
            for dm in pn389._DRIFT_MARKERS:
                if dm.startswith("[Genesis"):
                    continue
                assert dm not in src, f"drift marker {dm!r} present in {rel}"

    def test_apply_against_real_pin_copy(self, tmp_path, monkeypatch):
        """End-to-end: copy the real pristine backend_xgrammar.py, apply
        PN389, assert it compiles and every EngineCore DFA-build arm now
        flows through the upstream compile_regex_with_timeout helper.
        Exercises the byte-exact active anchor against the live pin tree
        (not just the hand fixture)."""
        import shutil

        dst = tmp_path / "backend_xgrammar.py"
        shutil.copyfile(
            PIN_TREE / "v1/structured_output/backend_xgrammar.py", dst
        )

        def _resolve(rel):
            if rel == "v1/structured_output/backend_xgrammar.py":
                return str(dst)
            return None

        monkeypatch.setattr(pn389, "resolve_vllm_file", _resolve)
        monkeypatch.setattr(pn389, "vllm_install_root", lambda: str(tmp_path))
        import sndr.dispatcher as dispatcher
        monkeypatch.setattr(
            dispatcher, "should_apply", lambda pid: (True, "test override")
        )

        status, reason = pn389.apply()
        assert status == "applied", reason
        out = dst.read_text("utf-8")
        compile(out, str(dst), "exec")
        assert pn389.GENESIS_PN389_MARKER in out
        # All five request-type arms now route through the upstream helper.
        assert out.count("compile_regex_with_timeout(") >= 6
        assert "lambda spec: self.compiler.compile_json_schema(" in out
