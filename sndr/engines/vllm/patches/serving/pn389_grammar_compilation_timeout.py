# SPDX-License-Identifier: Apache-2.0
"""PN389 — XGrammar input-validation + grammar-compilation timeouts.

Vendor of OPEN vllm#45390 (jperezdealgaba, "fix(security): add input
validation and compilation timeouts for DoS mitigations"; studied via
``gh pr view`` + ``gh pr diff`` 2026-06-13). Backports the seven-GHSA
DoS-hardening bundle, scoped to the XGrammar grammar-compilation hot
path that EVERY Genesis tool-call traverses.

================================================================
0.23.1 REDESIGN (dev491 -> 0.23.1 migration; pin
0.23.1rc1.dev101+g4c6266331)
================================================================

The prose below describes the ORIGINAL 3-file design (introduce our own
``run_with_timeout`` + ``_check_regex_complexity`` in utils.py, a new
``VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS`` env in envs.py, and a
``compile_grammar -> _compile_ctx -> _compile_ctx_inner`` refactor in
backend_xgrammar.py). On the 0.23.1 pin that design no longer composes:
upstream ALREADY landed a first-generation helper
``compile_regex_with_timeout`` (utils.py; ThreadPoolExecutor +
``future.result(timeout)``, bounded by the env
``VLLM_REGEX_COMPILATION_TIMEOUT_S``, default 5s), already imported it
into backend_xgrammar.py, and already wraps the REGEX arm of
``compile_grammar`` with it. The original utils.py / envs.py anchors are
therefore gone (count==0) or redundant, and re-adding our own helper/env
would collide with the upstream ones.

The ACTIVE patch (see the patcher builders + ``_all_patchers`` + the
constants ``PN389_XGR_COMPILE_GRAMMAR_OLD`` / ``..._NEW`` below) is a
single byte-exact edit on backend_xgrammar.py ``compile_grammar`` that
REUSES the already-present ``compile_regex_with_timeout`` to wall-clock-
bound the four arms upstream still leaves unbounded (JSON / JSON_OBJECT /
GRAMMAR / STRUCTURAL_TAG), leaving the REGEX arm exactly as upstream
wrote it. The utils.py / envs.py / frontend-validate sub-patches are
retained as non-required, inert no-ops (NOT wired into the transaction)
for historical reference. Effective budget is now the existing
``VLLM_REGEX_COMPILATION_TIMEOUT_S`` (default 5s), not the original 2s
intent — operator-tunable via that env.

================================================================
UPSTREAM BUG CLASS (7 GHSA, CWE-400 uncontrolled resource consumption)
================================================================

The OpenAI-compatible structured-output path compiles a user-supplied
grammar/regex/JSON-schema into a DFA on the CPU engine loop with NO
wall-clock bound. A pathological grammar (catastrophic-backtracking
regex, exponential JSON schema) consumes unbounded CPU during
compilation — and because compilation runs on the single EngineCore
thread, it wedges ALL decode for every concurrent request. Our PROD is
single-instance and single-user-low-latency: async-scheduling overlap
does NOT save us (overlap hides GPU latency behind the scheduler, but
grammar compilation is pure-CPU on the engine loop, off the GPU
stream). One adversarial tool schema therefore stalls the whole engine
indefinitely — an instance-wide DoS.

vllm#45390 closes this with a generic ``run_with_timeout`` (daemon
thread + ``Queue`` hand-off + bounded ``Semaphore`` so timed-out
compilations cannot accumulate) wrapping every XGrammar entrypoint, plus
a cheap ``_check_regex_complexity`` pre-filter (length + paren-nesting
bound) that rejects the obviously-adversarial regex BEFORE the compiler
is even called. The PR also adds protocol/engine input bounds
(logit_bias / stop_token_ids / allowed_token_ids / bad_words); those are
deliberately OUT OF SCOPE here — they edit ``sampling_params.py`` and the
split ``protocol.py`` files that P109 / PN387 already touch, and they are
tracked as a separate batch-2 wave-2 item to keep PN389's anchors
collision-free and the patch reviewable. PN389 vendors the
grammar-timeout core only.

================================================================
WHAT THIS PATCH DOES (three files, one atomic transaction)
================================================================

(1) ``v1/structured_output/utils.py`` — ADDITIVE: introduces
    ``run_with_timeout`` (daemon-thread + ``Queue`` + module-level
    ``Semaphore(4)``) and ``_check_regex_complexity`` plus their
    constants (``MAX_REGEX_LENGTH=10_000``, ``MAX_REGEX_NESTING_DEPTH``
    ``=20``, ``_MAX_CONCURRENT_COMPILATIONS=4``). New symbols only — no
    pin function is rewritten, so there is no anchor inside an existing
    body. Our pin g303916e93 has NO compilation timeout AT ALL (it lacks
    even the first-generation ``compile_regex_with_timeout`` the PR
    refactors), so these helpers are brand-new to the tree.

(2) ``v1/structured_output/backend_xgrammar.py`` — two distinct surfaces,
    both bounded:

      (2a) THE ENGINECORE COMPILE PATH (the actual DoS wedge surface):
      ``XgrammarBackend.compile_grammar`` is refactored — exactly as the PR
      does — into ``compile_grammar`` -> ``_compile_ctx`` ->
      ``run_with_timeout(self._compile_ctx_inner, ...)``. ``_compile_ctx_inner``
      holds the pin's original ``self.compiler.compile_*`` dispatch verbatim
      (only ``ctx = ...`` becomes ``return ...``), so EVERY type's vocab-
      dependent DFA build (JSON / JSON_OBJECT / GRAMMAR / REGEX /
      STRUCTURAL_TAG) now runs on a daemon thread under the wall-clock
      timeout. This is what bounds the single CPU EngineCore loop: a
      pathological compile bounces as a ``ValueError`` instead of wedging
      decode for every concurrent request. The REGEX arm keeps the cheap
      ``_check_regex_complexity`` pre-filter (inside the timed thread).

      (2b) THE FRONTEND VALIDATION PRE-FLIGHT: EVERY ``xgr.Grammar.from_*``
      call inside ``validate_xgrammar_grammar`` (regex / choice / json_schema
      / ebnf / structural_tag — ALL XGrammar types, matching the PR) is also
      wrapped in ``run_with_timeout``. ``validate_xgrammar_grammar`` runs in
      the FRONTEND process (it PARSES the schema into a Grammar object — a
      different, cheaper xgrammar API than the EngineCore compiler's
      vocab-dependent DFA build) and is the pre-flight every Genesis
      tool-call JSON schema flows through; bounding it rejects an
      adversarial *parse* before the request reaches the engine. Both
      surfaces are bounded so neither a slow parse (frontend) nor a slow
      compile (EngineCore) can hang unbounded.

(3) ``envs.py`` — ADDITIVE: registers
    ``VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS`` (declaration + os.getenv
    lambda). The PR renames the older ``VLLM_REGEX_COMPILATION_TIMEOUT_S``
    to this name; our pin has neither, so we add the new env fresh.

================================================================
GENESIS DIVERGENCE FROM THE PR (documented per iron rule #10)
================================================================

  • DEFAULT TIMEOUT = 2s, not the PR's 10s. A 10s compilation budget
    would let a single slow schema blow our 70-160ms TTFT SLO by ~60x
    before the timeout even fires. 2s is the largest budget that still
    bounds the worst-case wedge below a human-perceptible stall while
    leaving generous headroom over a healthy tool-schema compile
    (sub-millisecond on Qwen 152K-vocab in our offline timing). The env
    is operator-tunable; ``VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS=10``
    restores the PR default.

  • The constants block, the ``run_with_timeout`` docstring, the
    ``_check_regex_complexity`` docstring and the envs.py comment are
    re-worded vs the PR. This is the lint_drift_markers self-collision
    contract (PN369): the drift markers below are exact substrings of the
    PR's emitted text (its docstrings / comments), and our emitted text
    deliberately never reproduces them, so the markers can flag an
    upstream merge without ever matching our own replacement.

================================================================
SAFETY MODEL
================================================================

  • run_with_timeout is BIT-IDENTICAL for any compilation that finishes
    inside the budget — it returns the inner result unchanged; the only
    behavioural change is that a >2s compile/parse now raises a clean
    ``ValueError`` instead of running unbounded.
  • COMPILE vs VALIDATE (the surface distinction that matters): the
    EngineCore wedge is the ``compile_grammar`` DFA build in the engine
    subprocess — that is the path PN389 refactors through
    ``run_with_timeout`` so a schema that PARSES fast but COMPILES
    catastrophically (the worst case) is bounded too, not just rejected
    at the frontend ``from_*`` parse pre-flight. Bounding ONLY the
    frontend validation would leave the documented engine-wedge open;
    PN389 bounds both, so the ``ValueError`` (-> 400 / engine non-wedge)
    claim holds for the catastrophic-compile case.
  • _check_regex_complexity only fires on >10K-char or >20-deep-paren
    patterns. The GENESIS-SPECIFIC false-positive concern (legit
    JSON-schema-derived regex tripping the naive paren-depth counter) is
    pinned by a unit test that feeds our real gemma4 / qwen3_coder tool
    schemas' JSON-schema-derived regex through ``_check_regex_complexity``
    and asserts NO rejection — see tests (red-first).
  • The bounded ``Semaphore(4)`` caps concurrent compilation threads so a
    burst of slow grammars cannot spawn unbounded daemon threads; the
    5th concurrent compile is rejected (400), not queued.
  • Default OFF (``default_on=False``): the timeout reject is a new
    failure mode for legitimate-but-slow grammars, so we gate it behind
    ``GENESIS_ENABLE_PN389_GRAMMAR_TIMEOUTS`` until a server A/B confirms
    the 2s budget never trips a real tool-schema compile. STRONG
    RECOMMENDATION to enable on single-instance PROD once validated — the
    unguarded path is a one-request engine wedge.
  • Synergy with PN386 (#45389): both harden the same XGrammar tool-call
    hot path every Genesis model uses; disjoint files (PN386 edits the
    tool-parser streaming helper, PN389 edits the grammar backend), no
    anchor overlap. No collision with P62 / PN58 (spec-decode grammar
    mask timing / reasoning boundary — different files entirely).

Author backport: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
Vendor target: vllm-project/vllm#45390 (OPEN as of 2026-06-13).
"""
from __future__ import annotations

import logging
import os

from sndr.engines.vllm.detection.guards import resolve_vllm_file, vllm_install_root
from sndr.kernel import TextPatch, TextPatcher

log = logging.getLogger("genesis.wiring.pn389_grammar_compilation_timeout")

GENESIS_PN389_MARKER = (
    "Genesis PN389 XGrammar input-validation + grammar-compilation "
    "timeouts (vendor of vllm#45390) v1"
)

# Genesis default grammar/regex compilation budget. The PR ships 10s; we
# clamp to 2s because a 10s wedge blows our 70-160ms TTFT SLO by ~60x
# before the timeout fires. Spelled here as the source-of-truth default
# that the envs.py os.getenv lambda reads.
PN389_DEFAULT_TIMEOUT_SECONDS = 2

_TARGET_UTILS = "v1/structured_output/utils.py"
_TARGET_XGRAMMAR = "v1/structured_output/backend_xgrammar.py"
_TARGET_ENVS = "envs.py"


# ─────────────────────────────────────────────────────────────────────
# Drift markers — exact substrings of vllm#45390's emitted text (from
# `gh pr diff 45390`, 2026-06-13). Each is ABSENT in the pristine pin
# tree g303916e93 (byte-verified count==0) and is deliberately NOT a
# substring of any PN389 replacement below: we re-word our docstrings,
# comments and constants so these PR-form strings only ever match an
# actual upstream merge (lint_drift_markers self-collision contract,
# PN369). The `[Genesis PN389` banner is the defended convention entry.
# ─────────────────────────────────────────────────────────────────────
_DRIFT_MARKERS = (
    # The PR's run_with_timeout docstring head (we re-word ours).
    "Run *fn(*args)* in a daemon thread with a hard wall-clock timeout.",
    # The PR's _check_regex_complexity docstring head (we re-word ours).
    "Reject patterns that are obviously too complex before compilation.",
    # The PR's envs.py comment head for the renamed timeout env.
    "Maximum time in seconds allowed for grammar/regex compilation into a",
    # Defended convention entry (our own banner) — exempt from the
    # collision lint; keeps residue coverage if the PR comments change.
    "[Genesis PN389",
)


# ══════════════════════════════════════════════════════════════════════
# File 1 — v1/structured_output/utils.py (ADDITIVE)
# ══════════════════════════════════════════════════════════════════════
#
# Two insertions, both keyed on byte-exact pin anchors (count==1):
#   (a) the import block — add `threading` and `Queue`;
#   (b) right after `CACHE = None` — the run_with_timeout +
#       _check_regex_complexity helpers and their constants.
# These are NEW symbols; no existing pin function body is rewritten.

# (a) import block. Pin head: importlib.metadata / os / tempfile / typing.
PN389_UTILS_IMPORTS_OLD = (
    "import importlib.metadata\n"
    "import os\n"
    "import tempfile\n"
    "from typing import TYPE_CHECKING\n"
)

PN389_UTILS_IMPORTS_NEW = (
    "import importlib.metadata\n"
    "import os\n"
    "import tempfile\n"
    "import threading\n"
    "from collections.abc import Callable\n"
    "from queue import Empty, Queue\n"
    "from typing import TYPE_CHECKING, TypeVar\n"
)

# (b) helper block, inserted right after the `CACHE = None` line. The
# anchor pins the `logger = init_logger(__name__)` line + blank line +
# `CACHE = None` so the helpers land directly below the module constants.
PN389_UTILS_HELPERS_OLD = (
    "logger = init_logger(__name__)\n"
    "\n"
    "CACHE = None\n"
)

PN389_UTILS_HELPERS_NEW = (
    "logger = init_logger(__name__)\n"
    "\n"
    "CACHE = None\n"
    "\n"
    "# [Genesis PN389 vendor of vllm#45390] grammar/regex compilation DoS\n"
    "# guards. Our pin g303916e93 ships NO compilation timeout at all, so\n"
    "# these are brand-new helpers (not the PR's rename of an existing one).\n"
    "_PN389_T = TypeVar(\"_PN389_T\")\n"
    "# Upper bounds for the cheap pre-filter. A pattern longer than\n"
    "# MAX_REGEX_LENGTH chars or nested deeper than MAX_REGEX_NESTING_DEPTH\n"
    "# parentheses is rejected before the (expensive) compiler is called.\n"
    "MAX_REGEX_LENGTH = 10_000\n"
    "MAX_REGEX_NESTING_DEPTH = 20\n"
    "# Cap on simultaneously-alive compilation threads. A burst of slow\n"
    "# grammars therefore cannot spawn unbounded daemon threads; the 5th\n"
    "# concurrent compile is rejected, not queued.\n"
    "_MAX_CONCURRENT_COMPILATIONS = 4\n"
    "_compilation_semaphore = threading.Semaphore(_MAX_CONCURRENT_COMPILATIONS)\n"
    "\n"
    "\n"
    "def _check_regex_complexity(pattern: str) -> None:\n"
    "    # [Genesis PN389] Cheap O(n) pre-filter run BEFORE compilation:\n"
    "    # bound the pattern length and the maximum parenthesis nesting\n"
    "    # depth so an obviously-adversarial regex is bounced as a clean\n"
    "    # ValueError instead of detonating the DFA builder.\n"
    "    if len(pattern) > MAX_REGEX_LENGTH:\n"
    "        raise ValueError(\n"
    "            f\"Regex pattern too long ({len(pattern)} chars, \"\n"
    "            f\"max {MAX_REGEX_LENGTH}). Simplify the pattern or \"\n"
    "            \"split into smaller expressions.\"\n"
    "        )\n"
    "    depth = 0\n"
    "    max_depth = 0\n"
    "    for ch in pattern:\n"
    "        if ch == \"(\":\n"
    "            depth += 1\n"
    "            max_depth = max(max_depth, depth)\n"
    "        elif ch == \")\":\n"
    "            depth -= 1\n"
    "    if max_depth > MAX_REGEX_NESTING_DEPTH:\n"
    "        raise ValueError(\n"
    "            f\"Regex nesting too deep ({max_depth} levels, \"\n"
    "            f\"max {MAX_REGEX_NESTING_DEPTH}). Simplify the pattern.\"\n"
    "        )\n"
    "\n"
    "\n"
    "def run_with_timeout(\n"
    "    fn: Callable[..., _PN389_T],\n"
    "    *args: object,\n"
    "    timeout: int,\n"
    "    label: str = \"Operation\",\n"
    ") -> _PN389_T:\n"
    "    # [Genesis PN389] Execute fn(*args) on a daemon thread under a hard\n"
    "    # wall-clock timeout. A bounded semaphore caps live compilation\n"
    "    # threads; a timed-out thread is orphaned (daemon threads never\n"
    "    # block process exit) but the semaphore stops them piling up. The\n"
    "    # caller returns in ~timeout seconds on a hang, not fn's duration.\n"
    "    if not _compilation_semaphore.acquire(timeout=timeout):\n"
    "        raise ValueError(\n"
    "            \"Too many concurrent grammar compilations in progress. \"\n"
    "            \"Try again later or simplify the request.\"\n"
    "        )\n"
    "    result_queue: \"Queue[tuple[str, object]]\" = Queue()\n"
    "\n"
    "    def _worker() -> None:\n"
    "        try:\n"
    "            result_queue.put((\"ok\", fn(*args)))\n"
    "        except BaseException as exc:  # noqa: BLE001 — re-raised in caller\n"
    "            result_queue.put((\"error\", exc))\n"
    "        finally:\n"
    "            _compilation_semaphore.release()\n"
    "\n"
    "    thread = threading.Thread(target=_worker, daemon=True)\n"
    "    thread.start()\n"
    "    try:\n"
    "        status, value = result_queue.get(timeout=timeout)\n"
    "    except Empty:\n"
    "        raise ValueError(\n"
    "            f\"{label} timed out after {timeout}s. \"\n"
    "            \"The grammar may be too complex.\"\n"
    "        ) from None\n"
    "    if status == \"error\":\n"
    "        raise value  # type: ignore[misc]\n"
    "    return value  # type: ignore[return-value]\n"
)


# ══════════════════════════════════════════════════════════════════════
# File 2 — v1/structured_output/backend_xgrammar.py
# ══════════════════════════════════════════════════════════════════════
#
# Seven edits: import the two helpers; refactor compile_grammar so the
# EngineCore DFA build of EVERY type runs through run_with_timeout (the
# core fix — the actual wedge surface); and wrap each `xgr.Grammar.from_*`
# frontend validation call in run_with_timeout (the parse pre-flight).

# (a) pull the two new helpers in from utils alongside the existing imports.
PN389_XGR_IMPORTS_OLD = (
    "from vllm.v1.structured_output.utils import (\n"
    "    choice_as_grammar,\n"
    "    convert_lark_to_ebnf,\n"
    "    grammar_is_likely_lark,\n"
    ")\n"
)

PN389_XGR_IMPORTS_NEW = (
    "from vllm.v1.structured_output.utils import (\n"
    "    _check_regex_complexity,\n"
    "    choice_as_grammar,\n"
    "    convert_lark_to_ebnf,\n"
    "    grammar_is_likely_lark,\n"
    "    run_with_timeout,\n"
    ")\n"
)

# (b) compile_grammar — the EngineCore DFA-build path (THE wedge surface).
#
# REDESIGN for 0.23.1 (pin 0.23.1rc1.dev101+g4c6266331): the original
# anchor — a compile_grammar whose REGEX arm read
# `ctx = self.compiler.compile_regex(grammar_spec)` with NO timeout on ANY
# arm — was refactored away upstream. The live 0.23.1 tree already ships
# the first-generation helper `compile_regex_with_timeout` (utils.py;
# ThreadPoolExecutor + future.result(timeout), bounded by the existing
# env VLLM_REGEX_COMPILATION_TIMEOUT_S, default 5s) and already wires it
# into the REGEX arm of compile_grammar. It is also already imported in
# this file's `from vllm.v1.structured_output.utils import (...)` block.
#
# So the original 3-file design (introduce our own run_with_timeout +
# _check_regex_complexity in utils.py, + a new
# VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS env in envs.py, + a
# compile_grammar -> _compile_ctx -> _compile_ctx_inner refactor) no
# longer composes: its utils.py / envs.py anchors are gone (count==0 on
# live), and re-adding our own helper/env would collide with the
# already-present upstream ones.
#
# Per the task directive, we COMPOSE with upstream instead: a single
# byte-exact anchor on compile_grammar that reuses the already-imported
# `compile_regex_with_timeout(fn, spec)` for the four arms upstream still
# leaves UNbounded (JSON / JSON_OBJECT / GRAMMAR / STRUCTURAL_TAG),
# leaving the REGEX arm exactly as upstream already wrote it. Now EVERY
# type's vocab-dependent DFA build is wall-clock-bounded by the existing
# VLLM_REGEX_COMPILATION_TIMEOUT_S (default 5s, operator-tunable), and a
# pathological compile bounces as a ValueError instead of wedging the
# single CPU EngineCore loop. Bit-identical for any compile within budget.
#
# JSON / JSON_OBJECT carry the any_whitespace kwarg, so they are wrapped
# in a `lambda spec: ...` (single-str-arg callable, as the helper
# expects). GRAMMAR and the STRUCTURAL_TAG else-branch take a single
# positional str, so the bound method is passed directly. The
# STRUCTURAL_TAG structures-branch takes (tags, triggers), so it is
# wrapped in `lambda _spec: ...` with grammar_spec passed as the str
# pattern. The lambdas are invoked synchronously inside the helper with
# no enclosing loop, so there is no late-binding/loop-capture footgun.
#
# Anchor = the whole pin compile_grammar dispatch (count==1, byte-verified
# against the live 0.23.1 container backend_xgrammar.py). The trailing
# `return XgrammarGrammar(...)` block follows the anchor and is preserved
# untouched.
PN389_XGR_COMPILE_GRAMMAR_OLD = (
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
    "            if \"structures\" in s_tag:\n"
    "                # Falling back to deprecated method of compiling structural tag\n"
    "                tags = [\n"
    "                    xgr.StructuralTagItem(\n"
    "                        begin=s[\"begin\"],\n"
    "                        schema=json.dumps(s[\"schema\"]),\n"
    "                        end=s[\"end\"],\n"
    "                    )\n"
    "                    for s in s_tag[\"structures\"]\n"
    "                ]\n"
    "                ctx = self.compiler.compile_structural_tag(tags, s_tag[\"triggers\"])\n"
    "            else:\n"
    "                ctx = self.compiler.compile_structural_tag(grammar_spec)\n"
    "        else:\n"
    "            logger.error(\n"
    "                \"Validation should have already occurred. Please file an issue.\"\n"
    "            )\n"
    "            raise ValueError(\n"
    "                f\"grammar is not of valid supported types. ({request_type!s})\"\n"
    "            )\n"
)

PN389_XGR_COMPILE_GRAMMAR_NEW = (
    "    def compile_grammar(\n"
    "        self, request_type: StructuredOutputOptions, grammar_spec: str\n"
    "    ) -> StructuredOutputGrammar:\n"
    "        # [Genesis PN389 vendor of vllm#45390] wall-clock-bound EVERY\n"
    "        # EngineCore DFA build, not just REGEX. compile_grammar runs on\n"
    "        # the single CPU EngineCore loop; upstream 0.23.1 only wraps the\n"
    "        # REGEX arm in compile_regex_with_timeout, so a pathological\n"
    "        # JSON-schema / EBNF grammar / structural-tag still compiles\n"
    "        # unbounded and wedges ALL decode. We compose with the existing\n"
    "        # compile_regex_with_timeout helper (single-arg callable + spec\n"
    "        # string, bounded by VLLM_REGEX_COMPILATION_TIMEOUT_S) for the\n"
    "        # remaining arms so every type bounces as a ValueError instead\n"
    "        # of wedging the engine. Bit-identical for compiles within budget.\n"
    "        if request_type == StructuredOutputOptions.JSON:\n"
    "            ctx = compile_regex_with_timeout(\n"
    "                lambda spec: self.compiler.compile_json_schema(\n"
    "                    spec, any_whitespace=not self.disable_any_whitespace\n"
    "                ),\n"
    "                grammar_spec,\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.JSON_OBJECT:\n"
    "            ctx = compile_regex_with_timeout(\n"
    "                lambda spec: self.compiler.compile_json_schema(\n"
    "                    spec, any_whitespace=not self.disable_any_whitespace\n"
    "                ),\n"
    "                '{\"type\": \"object\"}',\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.GRAMMAR:\n"
    "            ctx = compile_regex_with_timeout(\n"
    "                self.compiler.compile_grammar,\n"
    "                grammar_spec,\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.REGEX:\n"
    "            ctx = compile_regex_with_timeout(\n"
    "                self.compiler.compile_regex,\n"
    "                grammar_spec,\n"
    "            )\n"
    "        elif request_type == StructuredOutputOptions.STRUCTURAL_TAG:\n"
    "            s_tag = json.loads(grammar_spec)\n"
    "            if \"structures\" in s_tag:\n"
    "                # Falling back to deprecated method of compiling structural tag\n"
    "                tags = [\n"
    "                    xgr.StructuralTagItem(\n"
    "                        begin=s[\"begin\"],\n"
    "                        schema=json.dumps(s[\"schema\"]),\n"
    "                        end=s[\"end\"],\n"
    "                    )\n"
    "                    for s in s_tag[\"structures\"]\n"
    "                ]\n"
    "                ctx = compile_regex_with_timeout(\n"
    "                    lambda _spec: self.compiler.compile_structural_tag(\n"
    "                        tags, s_tag[\"triggers\"]\n"
    "                    ),\n"
    "                    grammar_spec,\n"
    "                )\n"
    "            else:\n"
    "                ctx = compile_regex_with_timeout(\n"
    "                    self.compiler.compile_structural_tag,\n"
    "                    grammar_spec,\n"
    "                )\n"
    "        else:\n"
    "            logger.error(\n"
    "                \"Validation should have already occurred. Please file an issue.\"\n"
    "            )\n"
    "            raise ValueError(\n"
    "                f\"grammar is not of valid supported types. ({request_type!s})\"\n"
    "            )\n"
)

# (c) validate_xgrammar_grammar — regex arm. Add the pre-filter and wrap
# from_regex in run_with_timeout (the env timeout is read inline).
PN389_XGR_VALIDATE_REGEX_OLD = (
    "    if so_params.regex:\n"
    "        try:\n"
    "            xgr.Grammar.from_regex(so_params.regex)\n"
    "        except Exception as err:\n"
)

PN389_XGR_VALIDATE_REGEX_NEW = (
    "    if so_params.regex:\n"
    "        try:\n"
    "            # [Genesis PN389 vendor of vllm#45390] complexity pre-filter\n"
    "            # + wall-clock-bounded grammar build.\n"
    "            _check_regex_complexity(so_params.regex)\n"
    "            run_with_timeout(\n"
    "                xgr.Grammar.from_regex,\n"
    "                so_params.regex,\n"
    "                timeout=vllm.envs.VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,\n"
    "                label=\"Regex grammar validation\",\n"
    "            )\n"
    "        except ValueError:\n"
    "            raise\n"
    "        except Exception as err:\n"
)

# (d) validate_xgrammar_grammar — choice arm (from_ebnf).
PN389_XGR_VALIDATE_CHOICE_OLD = (
    "        choice_grammar = choice_as_grammar(so_params.choice)\n"
    "        try:\n"
    "            xgr.Grammar.from_ebnf(choice_grammar)\n"
    "        except Exception as err:\n"
)

PN389_XGR_VALIDATE_CHOICE_NEW = (
    "        choice_grammar = choice_as_grammar(so_params.choice)\n"
    "        try:\n"
    "            # [Genesis PN389 vendor of vllm#45390] bounded grammar build.\n"
    "            run_with_timeout(\n"
    "                xgr.Grammar.from_ebnf,\n"
    "                choice_grammar,\n"
    "                timeout=vllm.envs.VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,\n"
    "                label=\"Choice grammar validation\",\n"
    "            )\n"
    "        except Exception as err:\n"
)

# (e) validate_xgrammar_grammar — json_schema arm (from_json_schema).
# This is THE hot path: every Genesis tool-call JSON schema lands here.
PN389_XGR_VALIDATE_JSON_OLD = (
    "        try:\n"
    "            xgr.Grammar.from_json_schema(schema)\n"
    "        except Exception as err:\n"
)

PN389_XGR_VALIDATE_JSON_NEW = (
    "        try:\n"
    "            # [Genesis PN389 vendor of vllm#45390] bounded grammar build\n"
    "            # — the tool-call JSON-schema hot path every model traverses.\n"
    "            run_with_timeout(\n"
    "                xgr.Grammar.from_json_schema,\n"
    "                schema,\n"
    "                timeout=vllm.envs.VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,\n"
    "                label=\"JSON schema grammar validation\",\n"
    "            )\n"
    "        except Exception as err:\n"
)

# (f) validate_xgrammar_grammar — ebnf grammar arm (from_ebnf, the
# `we aren't compiling it` comment is unique to this site).
PN389_XGR_VALIDATE_EBNF_OLD = (
    "        try:\n"
    "            # parse the grammar, but we aren't compiling it.\n"
    "            xgr.Grammar.from_ebnf(so_params.grammar)\n"
    "        except Exception as e:\n"
)

PN389_XGR_VALIDATE_EBNF_NEW = (
    "        try:\n"
    "            # parse the grammar, but we aren't compiling it.\n"
    "            # [Genesis PN389 vendor of vllm#45390] bounded grammar build.\n"
    "            run_with_timeout(\n"
    "                xgr.Grammar.from_ebnf,\n"
    "                so_params.grammar,\n"
    "                timeout=vllm.envs.VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,\n"
    "                label=\"EBNF grammar validation\",\n"
    "            )\n"
    "        except Exception as e:\n"
)

# (g) validate_xgrammar_grammar — structural_tag arm (both from_structural_tag
# calls). Wrap each in run_with_timeout.
PN389_XGR_VALIDATE_STAG_OLD = (
    "                xgr.Grammar.from_structural_tag(tags, s_tag[\"triggers\"])\n"
    "            else:\n"
    "                xgr.Grammar.from_structural_tag(so_params.structural_tag)\n"
)

PN389_XGR_VALIDATE_STAG_NEW = (
    "                # [Genesis PN389 vendor of vllm#45390] bounded build.\n"
    "                run_with_timeout(\n"
    "                    xgr.Grammar.from_structural_tag,\n"
    "                    tags,\n"
    "                    s_tag[\"triggers\"],\n"
    "                    timeout=vllm.envs.VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,\n"
    "                    label=\"Structural tag grammar validation\",\n"
    "                )\n"
    "            else:\n"
    "                # [Genesis PN389 vendor of vllm#45390] bounded build.\n"
    "                run_with_timeout(\n"
    "                    xgr.Grammar.from_structural_tag,\n"
    "                    so_params.structural_tag,\n"
    "                    timeout=vllm.envs.VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,\n"
    "                    label=\"Structural tag grammar validation\",\n"
    "                )\n"
)


# ══════════════════════════════════════════════════════════════════════
# File 3 — envs.py (ADDITIVE: new VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS)
# ══════════════════════════════════════════════════════════════════════

# (a) type-annotation declaration block (after VLLM_XGRAMMAR_CACHE_MB).
PN389_ENVS_DECL_OLD = "    VLLM_XGRAMMAR_CACHE_MB: int = 0\n"

PN389_ENVS_DECL_NEW = (
    "    VLLM_XGRAMMAR_CACHE_MB: int = 0\n"
    "    # [Genesis PN389 vendor of vllm#45390] grammar/regex compile budget.\n"
    "    VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS: int = 2\n"
)

# (b) the os.getenv lambda block (after the VLLM_XGRAMMAR_CACHE_MB lambda).
# Genesis default = 2s (PR ships 10s — would blow our TTFT SLO ~60x).
PN389_ENVS_LAMBDA_OLD = (
    '    "VLLM_XGRAMMAR_CACHE_MB": lambda: int(os.getenv("VLLM_XGRAMMAR_CACHE_MB", "512")),\n'
)

PN389_ENVS_LAMBDA_NEW = (
    '    "VLLM_XGRAMMAR_CACHE_MB": lambda: int(os.getenv("VLLM_XGRAMMAR_CACHE_MB", "512")),\n'
    "    # [Genesis PN389 vendor of vllm#45390] max seconds for a grammar/regex\n"
    "    # DFA compile. Genesis default 2s (the PR ships 10s, which would blow\n"
    "    # our 70-160ms TTFT SLO ~60x before the timeout fires). Operator may\n"
    "    # raise it back to 10 via the env var.\n"
    '    "VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS": lambda: int(\n'
    '        os.getenv("VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS", "2")\n'
    "    ),\n"
)


# ─────────────────────────────────────────────────────────────────────
# Patcher builders (one per target file). Driven atomically by apply().
# ─────────────────────────────────────────────────────────────────────


def _make_utils_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_UTILS)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN389 v1/structured_output/utils.py — run_with_timeout + "
            "_check_regex_complexity (vendor of vllm#45390)"
        ),
        target_file=str(target),
        marker=GENESIS_PN389_MARKER,
        sub_patches=[
            # REDESIGN (0.23.1): both anchors are GONE (count==0 on live).
            # 0.23.1 already ships compile_regex_with_timeout in utils.py;
            # the import block and the `CACHE = None` helper-insertion
            # point our anchors keyed on were refactored away, and the
            # redesigned compile_grammar reuses the upstream helper rather
            # than introducing run_with_timeout. Non-required so each soft-
            # skips; this whole patcher is no longer wired into apply()'s
            # transaction (see _all_patchers / _make_xgrammar_patcher).
            TextPatch(
                name="pn389_utils_imports",
                anchor=PN389_UTILS_IMPORTS_OLD,
                replacement=PN389_UTILS_IMPORTS_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_utils_helpers",
                anchor=PN389_UTILS_HELPERS_OLD,
                replacement=PN389_UTILS_HELPERS_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def _make_xgrammar_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_XGRAMMAR)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN389 v1/structured_output/backend_xgrammar.py — wrap all "
            "XGrammar compile/validate calls in run_with_timeout "
            "(vendor of vllm#45390)"
        ),
        target_file=str(target),
        marker=GENESIS_PN389_MARKER,
        sub_patches=[
            # REDESIGN (0.23.1): the EngineCore compile_grammar arm is the
            # only REQUIRED edit — it is the documented wedge surface and
            # its new anchor is byte-verified count==1 on live 0.23.1.
            TextPatch(
                name="pn389_xgr_compile_grammar",
                anchor=PN389_XGR_COMPILE_GRAMMAR_OLD,
                replacement=PN389_XGR_COMPILE_GRAMMAR_NEW,
                required=True,
            ),
            # The remaining backend_xgrammar sub-patches target pin forms
            # that 0.23.1 already absorbed or refactored:
            #   - pn389_xgr_imports: upstream already imports
            #     compile_regex_with_timeout (the import block our anchor
            #     keyed on no longer exists; count==0 on live), and the
            #     redesigned compile_grammar above reuses that already-
            #     present import, so no import edit is needed.
            #   - the five validate_xgrammar_grammar arms key on pin forms
            #     that drifted on 0.23.1 (e.g. the REGEX validate arm now
            #     itself wraps compile_regex_with_timeout). They are a
            #     frontend-only residual, NOT the documented engine wedge.
            # All are made non-required so a missing/absorbed anchor soft-
            # skips instead of aborting the patcher. (They also reference
            # run_with_timeout / VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS,
            # which the collapsed single-file design no longer provides;
            # left here, non-required, as inert no-ops on 0.23.1 so the
            # historical anchors remain documented but cannot land.)
            TextPatch(
                name="pn389_xgr_imports",
                anchor=PN389_XGR_IMPORTS_OLD,
                replacement=PN389_XGR_IMPORTS_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_xgr_validate_regex",
                anchor=PN389_XGR_VALIDATE_REGEX_OLD,
                replacement=PN389_XGR_VALIDATE_REGEX_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_xgr_validate_choice",
                anchor=PN389_XGR_VALIDATE_CHOICE_OLD,
                replacement=PN389_XGR_VALIDATE_CHOICE_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_xgr_validate_json",
                anchor=PN389_XGR_VALIDATE_JSON_OLD,
                replacement=PN389_XGR_VALIDATE_JSON_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_xgr_validate_ebnf",
                anchor=PN389_XGR_VALIDATE_EBNF_OLD,
                replacement=PN389_XGR_VALIDATE_EBNF_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_xgr_validate_structural_tag",
                anchor=PN389_XGR_VALIDATE_STAG_OLD,
                replacement=PN389_XGR_VALIDATE_STAG_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def _make_envs_patcher() -> TextPatcher | None:
    target = resolve_vllm_file(_TARGET_ENVS)
    if target is None:
        return None
    return TextPatcher(
        patch_name=(
            "PN389 envs.py — VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS "
            "(Genesis default 2s; vendor of vllm#45390)"
        ),
        target_file=str(target),
        marker=GENESIS_PN389_MARKER,
        sub_patches=[
            # REDESIGN (0.23.1): although these two anchors still resolve
            # (count==1 on live), the env they add
            # (VLLM_GRAMMAR_COMPILATION_TIMEOUT_SECONDS) is now redundant:
            # the redesigned compile_grammar reuses the already-present
            # upstream env VLLM_REGEX_COMPILATION_TIMEOUT_S (default 5s)
            # and references no new env. Non-required so neither lands a
            # dead env nobody reads; this patcher is also no longer wired
            # into apply()'s transaction (see _all_patchers).
            TextPatch(
                name="pn389_envs_decl",
                anchor=PN389_ENVS_DECL_OLD,
                replacement=PN389_ENVS_DECL_NEW,
                required=False,
            ),
            TextPatch(
                name="pn389_envs_lambda",
                anchor=PN389_ENVS_LAMBDA_OLD,
                replacement=PN389_ENVS_LAMBDA_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=list(_DRIFT_MARKERS),
    )


def _all_patchers() -> list[TextPatcher]:
    """Build the PN389 target patcher(s); drop unresolvable ones.

    REDESIGN (0.23.1): collapsed from the original 3-file transaction
    (utils.py + backend_xgrammar.py + envs.py) to a SINGLE file. On pin
    0.23.1rc1.dev101+g4c6266331 upstream already ships
    ``compile_regex_with_timeout`` (utils.py) and
    ``VLLM_REGEX_COMPILATION_TIMEOUT_S`` (envs.py) and already imports the
    helper into backend_xgrammar.py, so the utils/envs arms have nothing
    to add (their anchors are gone or their env is redundant) — including
    them in the transaction would hard-fail it (a patcher with zero
    applicable sub-patches returns SKIPPED, which rolls the transaction
    back). The redesigned compile_grammar edit reuses the already-present
    upstream helper, so only ``backend_xgrammar.py`` is driven. The
    ``_make_utils_patcher`` / ``_make_envs_patcher`` builders and their
    constants are retained for historical reference and for a future pin
    where the upstream helper might be absent, but are NOT wired here.
    """
    out: list[TextPatcher] = []
    for builder in (_make_xgrammar_patcher,):
        p = builder()
        if p is not None:
            out.append(p)
    return out


def apply() -> tuple[str, str]:
    """Apply PN389 — XGrammar grammar-compilation timeouts. Never raises.

    REDESIGN (0.23.1): drives a SINGLE target file
    (``v1/structured_output/backend_xgrammar.py``) in ONE
    ``MultiFilePatchTransaction`` (validate-all-then-write-all). On pin
    0.23.1rc1.dev101+g4c6266331 upstream already ships
    ``compile_regex_with_timeout`` (utils.py) + ``VLLM_REGEX_COMPILATION``
    ``_TIMEOUT_S`` (envs.py) and imports the helper here, so the patch
    collapses from the original 3-file transaction to a single
    ``compile_grammar`` edit that REUSES the upstream helper for the four
    arms upstream still leaves unbounded (JSON / JSON_OBJECT / GRAMMAR /
    STRUCTURAL_TAG). No utils.py / envs.py edits are wired (see
    ``_all_patchers``).

    Opt-in: gated through the dispatcher on
    ``GENESIS_ENABLE_PN389_GRAMMAR_TIMEOUTS`` (default_on=False in the
    registry — the timeout reject is a new failure mode for legitimate
    slow grammars; gated until a server A/B confirms the budget never
    trips a real tool-schema compile). NOTE: the effective budget is now
    the existing ``VLLM_REGEX_COMPILATION_TIMEOUT_S`` (default 5s), not
    the patch's original 2s intent; operator-tunable via that env.
    """
    from sndr.dispatcher import log_decision, should_apply

    decision, reason = should_apply("PN389")
    log_decision("PN389", decision, reason)
    if not decision:
        return "skipped", reason

    if vllm_install_root() is None:
        return "skipped", "vllm install root not discoverable"

    patchers = _all_patchers()
    if len(patchers) != 1:
        return (
            "skipped",
            "PN389: target not resolvable "
            f"({len(patchers)}/1 of backend_xgrammar found)",
        )

    # The single target must be unpatched and free of the upstream-merged
    # form before we commit. The transaction's dry-run re-checks anchors;
    # here we additionally (a) report a clean idempotent skip when the
    # marker is already present, and (b) self-skip if #45390 has landed
    # upstream.
    markers_present = 0
    for p in patchers:
        if not os.path.isfile(p.target_file):
            return "skipped", f"target disappeared: {p.target_file}"
        try:
            with open(p.target_file, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return "skipped", f"PN389: read error on {p.target_file}: {e}"
        if p.marker in content:
            markers_present += 1
            continue  # already applied — idempotent
        for m in p.upstream_drift_markers:
            if m.startswith("[Genesis"):
                continue
            if m in content:
                return (
                    "skipped",
                    f"upstream drift marker {m!r} present in "
                    f"{os.path.basename(p.target_file)} — upstream PR "
                    "#45390 (or equivalent) appears merged (upstream_merged)",
                )

    # Every target already carries the marker -> nothing to do. Report a
    # clean idempotent skip rather than letting the transaction re-report
    # an all-IDEMPOTENT commit as "applied".
    if markers_present == len(patchers):
        return "skipped", "PN389: already applied (marker present on target)"

    from sndr.kernel import MultiFilePatchTransaction

    txn = MultiFilePatchTransaction(patchers, name="PN389")
    status, txn_reason = txn.apply_or_skip()
    if status != "applied":
        return status, f"PN389: {txn_reason}"
    return (
        "applied",
        "PN389 applied (1 file, 0.23.1 redesign): backend_xgrammar.py "
        "compile_grammar now wraps EVERY EngineCore DFA-build arm "
        "(JSON / JSON_OBJECT / GRAMMAR / STRUCTURAL_TAG) in the already-"
        "present upstream compile_regex_with_timeout helper, in addition "
        "to the REGEX arm upstream already wrapped. Bounded by the "
        "existing VLLM_REGEX_COMPILATION_TIMEOUT_S (default 5s, operator-"
        "tunable). A pathological tool schema that compiles "
        "catastrophically now bounces as a ValueError instead of wedging "
        "the single-instance EngineCore loop (vllm#45390 DoS). "
        "Bit-identical for compiles within budget. "
        "(utils.py / envs.py arms collapsed — upstream 0.23.1 already "
        "ships the helper + VLLM_REGEX_COMPILATION_TIMEOUT_S.)",
    )


def is_applied() -> bool:
    """Return True iff the PN389 marker is present in the target file."""
    if vllm_install_root() is None:
        return False
    patchers = _all_patchers()
    if len(patchers) != 1:
        return False
    for p in patchers:
        try:
            with open(p.target_file, encoding="utf-8") as f:
                if p.marker not in f.read():
                    return False
        except OSError:
            return False
    return True
