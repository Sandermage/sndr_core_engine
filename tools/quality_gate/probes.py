# SPDX-License-Identifier: Apache-2.0
"""Genesis quality-gate probe generation + verdict logic (engine-agnostic core).

This is the unit-testable heart of the Genesis quality-gate harness. The bash
drivers (`scripts/verify_stress.sh`, `scripts/soak_continuous.sh`) call into the
functions here to build request payloads and to turn raw HTTP responses into a
PASS / WARN / FAIL verdict with a Genesis-specific diagnostic.

Why a standalone module (not inline heredocs like the bash drivers could use):
the probe shapes and the verdict thresholds are the part that is easy to get
subtly wrong, so they are extracted here and exercised by
`tests/unit/quality_gate/test_quality_gate_probes.py` without needing a live
rig. A full live run still needs the GPU rig; the request-generation and
verdict-parsing logic does not, and that is what the unit tests pin.

Provenance — adapted and extended from club-3090's public test harness
(github.com/noonghunna/club-3090, MIT): `scripts/verify-stress.sh` (8-probe
NIAH ladder + tool-prefill OOM probe + IDE-agent / multi-turn shapes + the
ceiling ladder with per-rung VRAM-margin capture and false-ceiling detection)
and `scripts/soak-helper.py` (continuous multi-turn ramp + the soak verdict).
See docs/QUALITY_GATE.md for the full adaptation notes and credit.

Genesis extensions over the upstream harness:
  * `CLIFF_MAP` — every failure signature is cross-referenced to the Genesis
    cliff taxonomy (docs/TROUBLESHOOTING.md, "Named cliffs") AND the responsible
    Genesis patch ID (PN17 / P103 / PN59 / P67 / ...), so a red probe points the
    operator at the exact Genesis code path and mitigation instead of a generic
    "check docker logs".
  * Probe shapes target our bug classes directly: GDN OOM (Cliff 2 / 2a),
    Cliff 2b multi-turn accretion, silent-empty (HTTP 200 + 0 tokens), and
    tool-call corruption (Cliff 3 / 4).
  * Verdict objects are structured (probe id, http code, cliff id, patch id,
    remediation) rather than colour-coded prints, so they can be asserted on,
    serialised to JSON, and consumed by the soak attribution diff.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Genesis cliff taxonomy <-> patch ID cross-reference.
#
# Keyed by a short stable id. `signature` is the human description; `cliff` and
# `patch` point at docs/TROUBLESHOOTING.md "Named cliffs" and the owning patch.
# `remediation` is the operator's next action. This is the Genesis-specific
# layer the upstream club-3090 harness does not have — there, a 500 just says
# "check logs"; here it says "this is Cliff 2 (GDN fwd_h), owned by P103, lower
# --gpu-memory-utilization or route to dual/TP=2".
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CliffRef:
    cliff: str
    patch: str
    signature: str
    remediation: str


CLIFF_MAP: dict[str, CliffRef] = {
    # Long-context single-prompt OOM at the FA2 layer.
    "fa2_softmax_lse": CliffRef(
        cliff="Cliff 1",
        patch="PN17",
        signature="FA2 softmax_lse over-allocation at long context (>50K, high max-model-len)",
        remediation=(
            "Enable PN17 (FA2 lse runtime clamp). On 24 GB consumer Ampere also "
            "disable PN19 (costs ~120 MiB KV pool). See docs/TROUBLESHOOTING.md "
            "Cliff 1."
        ),
    ),
    # GDN forward h-tensor blow-up on a single long prompt.
    "gdn_fwd_h": CliffRef(
        cliff="Cliff 2 / 2a",
        patch="P103",
        signature="GDN chunk_gated_delta_rule_fwd_h (B,NT,H,V,K) blow-up on a single >50K prompt",
        remediation=(
            "Enable P103 (chunked fwd_h+fwd_o, GENESIS_ENABLE_P103=1, "
            "GENESIS_FLA_FWD_H_MAX_T=16384) and lower --gpu-memory-utilization "
            "to ~0.85. For prompts >60K on a single card route to a TP=2 / dual "
            "preset or llama.cpp. See docs/TROUBLESHOOTING.md Cliff 2 + the "
            "club-3090 #22 OOM recipe."
        ),
    ),
    # Multi-turn accumulating-context accretion OOM.
    "gdn_multiturn_accretion": CliffRef(
        cliff="Cliff 2b",
        patch="PN59",
        signature="GDN multi-turn VRAM accretion OOM after ~4-5 ramping turns (hermes/openhands shape)",
        remediation=(
            "Enable PN59 streaming-GDN (GENESIS_ENABLE_PN59_STREAMING_GDN=1) — the "
            "only mitigation that survives continuous soak. Pair with allocator "
            "hardening (PYTORCH_CUDA_ALLOC_CONF expandable_segments + "
            "garbage_collection_threshold:0.85) and mem-util 0.85. TP=2 presets "
            "structurally escape this. See docs/TROUBLESHOOTING.md Cliff 2b."
        ),
    ),
    # Tool-call cascade / garbage tokens.
    "tq_specverify_cudagraph": CliffRef(
        cliff="Cliff 3 / 4",
        patch="P67",
        signature="TurboQuant + spec-verify K+1 + FULL cudagraph tool-call cascade / garbage tokens",
        remediation=(
            "Ensure P67 (multi-query Triton kernel) compiles — on Qwen3.6-27B "
            "GQA=6 needs the non-pow-2 generalisation (Cliff 4). Verify the boot "
            "log shows P67 applied, not the PIECEWISE-cudagraph P65 fallback. "
            "See docs/TROUBLESHOOTING.md Cliff 3 + Cliff 4."
        ),
    ),
    # HTTP 200 but nothing came back.
    "silent_empty": CliffRef(
        cliff="silent-empty",
        patch="P67/PN30",
        signature="HTTP 200 with zero completion tokens after the model engaged (>=1s)",
        remediation=(
            "Silent prefill truncation or empty decode. Causes: xgrammar mask "
            "rejecting every candidate, spec-decode empty-draft return, or "
            "<think> exhausting max_tokens. Check P67/P30 tool-call paths and "
            "the grammar backend. See docs/QUALITY_GATE.md 'silent-empty'."
        ),
    ),
    # Engine no longer answering.
    "engine_dead": CliffRef(
        cliff="engine-down",
        patch="-",
        signature="No HTTP response (timeout / container OOM-killed / crash)",
        remediation=(
            "Engine hung or was OOM-killed. Inspect logs, then re-run after "
            "restart. If this fired on a long-context probe it is most likely a "
            "Cliff 1 / Cliff 2 OOM that took the worker down."
        ),
    ),
}


# Which cliff a 5xx maps to, keyed by probe kind. Default is the GDN fwd_h
# class (Cliff 2 / P103) since most heavy probes that 500 are GDN-bound.
_PROBE_5XX_CLIFF: dict[str, str] = {
    "tool_prefill": "fa2_softmax_lse",  # tool-message prefill OOM = FA2 / FFN
    "ide_agent": "fa2_softmax_lse",
    "longctx_large": "gdn_fwd_h",
    "ceiling": "gdn_fwd_h",
    "lcb_coding": "gdn_fwd_h",
    "reasoning": "gdn_fwd_h",
    "multiturn": "gdn_multiturn_accretion",  # Cliff 2b
    "soak_multiturn": "gdn_multiturn_accretion",
}


# Map an (probe-kind, http-code) observation to the most-likely cliff id. The
# bash driver passes the probe kind; this keeps the cliff attribution in one
# place and unit-testable.
def classify_failure(probe_kind: str, http_code: int) -> CliffRef | None:
    """Return the Genesis cliff/patch reference for a failing probe observation.

    `probe_kind` is one of: longctx_small, longctx_large, ceiling, tool_prefill,
    ide_agent, multiturn, lcb_coding, reasoning, soak_multiturn.
    `http_code` is the observed HTTP status (0 == no response / timeout).
    Returns None for a healthy (200) observation.
    """
    if http_code == 200:
        return None
    if http_code == 0:
        return CLIFF_MAP["engine_dead"]
    if http_code in (500, 502, 503):
        return CLIFF_MAP[_PROBE_5XX_CLIFF.get(probe_kind, "gdn_fwd_h")]
    # 4xx other than the expected 400 (over-ctx) handled by callers.
    return None


# ---------------------------------------------------------------------------
# Probe payload generation.
#
# Each builder returns a plain dict (an OpenAI /v1/chat/completions body). The
# bash driver writes it to a temp file and POSTs it. Keeping generation in
# Python means the NIAH secret, the filler sizing, and the message shapes are
# all unit-testable.
# ---------------------------------------------------------------------------

# NIAH vocabulary — deliberately distinctive multi-token phrases so a recall
# check is robust to tokenizer quirks. Matches club-3090's needle vocabulary.
_NIAH_ANIMALS = [
    "otter",
    "falcon",
    "platypus",
    "iguana",
    "narwhal",
    "chinchilla",
    "capybara",
    "axolotl",
]
_NIAH_COLORS = [
    "crimson",
    "turquoise",
    "amber",
    "violet",
    "emerald",
    "sapphire",
    "silver",
    "golden",
]
_NIAH_BLOCK = (
    "This section describes the history of computing in detail. "
    "Transistors were invented in 1947 at Bell Labs. The integrated circuit "
    "came a decade later. Microprocessors emerged in the 1970s and changed "
    "the world. Personal computing followed, then networking, then the web, "
    "then cloud and AI. "
)


def make_niah_secret(rng: random.Random | None = None) -> str:
    """Generate a distinctive 3-token needle phrase, e.g. 'crimson otter 42'."""
    r = rng or random.Random()
    return f"{r.choice(_NIAH_COLORS)} {r.choice(_NIAH_ANIMALS)} {r.randint(10, 99)}"


def make_niah_request(
    model: str,
    filler_scale: int,
    *,
    secret: str | None = None,
    rng: random.Random | None = None,
    max_tokens: int = 30,
) -> dict[str, Any]:
    """Build a needle-in-a-haystack request at the given filler scale.

    The needle is placed at ~50% depth so recall exercises mid-context
    attention. `filler_scale` is the number of filler-block repetitions; the
    ceiling ladder calibrates scale->tokens against the live tokenizer rather
    than guessing (see verdict_ceiling and the bash driver's calibration probe).
    """
    if secret is None:
        secret = make_niah_secret(rng)
    half = filler_scale // 2
    before = _NIAH_BLOCK * half
    after = _NIAH_BLOCK * (filler_scale - half)
    content = (
        before
        + f"\n\nIMPORTANT MEMORY: The hidden phrase is '{secret}'. "
        + "Remember this exactly.\n\n"
        + after
        + "\n\nQuestion: In the middle of the document above I wrote "
        + "'The hidden phrase is ___'. What was the hidden phrase? Reply with "
        + "only the phrase, no other text."
    )
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }


# Financial-news blocks for the tool-prefill OOM probe (a ~25K-token mock tool
# message stresses the activation-memory peak — Cliff 1 territory).
_TOOL_PREFILL_BLOCKS = [
    "Federal Reserve Chair stated rates would remain steady amid mixed signals. "
    "Treasury yields responded modestly, with the 10-year note ticking down two "
    "basis points by late trading.",
    "European markets opened higher on a sharp rebound in German industrial "
    "output. The DAX gained 0.8% in morning trading while the Stoxx 600 added "
    "0.5% on improved manufacturing PMI readings.",
    "Tech earnings season kicked into high gear with several majors beating "
    "expectations. Cloud revenues grew across the board, with AI infrastructure "
    "demand the key catalyst; semiconductor margins stayed pressured.",
    "Crude oil edged higher after OPEC extended production cuts through Q3. "
    "Brent rose 1.2% to near $84 while WTI gained to $79 on continued "
    "geopolitical support despite weak China demand.",
    "Bond markets saw a mild curve flattening as investors weighed growth "
    "signals. The 2s10s spread narrowed to 35 bps from 42 a week prior on "
    "reduced near-term Fed expectations.",
    "Gold touched a three-week high at $2,415/oz on renewed safe-haven demand. "
    "Silver tracked higher and miners rallied broadly with the sector ETF up "
    "over 1.5% on heavier-than-average volume.",
]


def make_tool_prefill_request(
    model: str, target_chars: int = 100_000
) -> dict[str, Any]:
    """Build the tool-response prefill OOM probe.

    A multi-turn payload with a large (~25K-token at 100K chars) mock tool
    message + tool definition + tool_choice=auto. Catches the activation-memory
    peak class (Cliff 1) that passes at idle but OOMs when a real tool reply is
    loaded.
    """
    content = ""
    i = 0
    while len(content) < target_chars:
        content += _TOOL_PREFILL_BLOCKS[i % len(_TOOL_PREFILL_BLOCKS)] + "\n\n"
        i += 1
    tool_def = {
        "type": "function",
        "function": {
            "name": "fetch_news",
            "description": "Fetch latest news on a topic.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    }
    return {
        "model": model,
        "messages": [
            {"role": "user", "content": "What's happening in financial markets today?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_news_1",
                        "type": "function",
                        "function": {
                            "name": "fetch_news",
                            "arguments": json.dumps({"topic": "markets"}),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_news_1", "content": content},
            {
                "role": "user",
                "content": "Summarize the top 3 themes from this news data in about 100 words.",
            },
        ],
        "tools": [tool_def],
        "tool_choice": "auto",
        "max_tokens": 500,
        "temperature": 0.6,
        "chat_template_kwargs": {"enable_thinking": False},
    }


_IDE_TOOLS = [
    ("read_file", "Read the contents of a file at the given path."),
    ("write_file", "Write content to a file at the given path."),
    ("list_directory", "List files at the given path, optionally recursive."),
    ("search_code", "Search for a regex pattern across the codebase."),
    ("run_command", "Execute a shell command in the project directory."),
    ("get_file_metadata", "Get metadata for a file."),
    ("create_directory", "Create a directory."),
    ("delete_file", "Delete a file."),
    ("git_status", "Get the current git status."),
    ("git_diff", "Get the diff for current changes."),
]


def _ide_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "pattern": {"type": "string"},
                        "command": {"type": "string"},
                        "content": {"type": "string"},
                        "recursive": {"type": "boolean"},
                    },
                    "required": ["path"],
                },
            },
        }
        for name, desc in _IDE_TOOLS
    ]


def make_ide_agent_request(model: str) -> dict[str, Any]:
    """Synthetic Cline/OpenCode IDE-agent one-shot.

    ~5K-char system preamble + 10 tool schemas + a refactor request, with
    tool_choice=none to force the long-reasoning + code-emission path that
    surfaces the inductor FFN-intermediate leak (Cliff 1 mechanism B)
    deterministically rather than letting the model short-circuit with a
    tool_call.
    """
    sys_text = (
        "You are a helpful AI coding assistant operating inside an IDE. You have "
        "access to a set of tools to read, write, search, and execute commands in "
        "the user's project. Always use the appropriate tool when the user requests "
        "file operations or code execution. Be concise in your reasoning, prefer "
        "minimal edits, and verify your changes by reading the file back after "
        "writing. When refactoring, preserve existing behavior unless explicitly "
        "asked to change it. Never modify files outside the user's project root. "
        "Never run destructive commands without explicit confirmation. "
    ) * 5
    user_text = (
        "I have a Python function `compute_metrics` in `src/analytics/metrics.py` "
        "that re-iterates the entire data list every call. Refactor it to maintain "
        "a streaming aggregation state that updates incrementally. Preserve the "
        "public API. Show me the diff before applying it."
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_text},
            {"role": "user", "content": user_text},
        ],
        "tools": _ide_tool_schemas(),
        "tool_choice": "none",
        "max_tokens": 2000,
        "temperature": 0.0,
        "stream": False,
    }


def make_multiturn_request(model: str) -> dict[str, Any]:
    """Multi-turn agent: sys + tools + user -> assistant(tool_call) -> tool reply
    -> user follow-up. A different inductor compile path than the single-turn
    IDE-agent probe (the assistant + tool messages reshape the compiled prefill).
    """
    sys_text = (
        "You are a coding assistant inside an IDE. Use the provided tools to read "
        "and edit files. Be concise. After each tool call, verify the result before "
        "proceeding to the next step. "
    ) * 8
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "pattern": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        }
        for name, desc in [
            ("read_file", "Read a file."),
            ("write_file", "Write a file."),
            ("search_code", "Search for a regex pattern."),
            ("list_directory", "List a directory."),
        ]
    ]
    mock_file = "\n".join(
        f"def function_{i}(arg{i}): return arg{i} * {i + 1}  # line {i}"
        for i in range(80)
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_text},
            {
                "role": "user",
                "content": "Read src/utils.py and tell me what functions are defined.",
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "src/utils.py"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_read_1", "content": mock_file},
            {
                "role": "user",
                "content": "Now refactor function_5 to use a different multiplier.",
            },
        ],
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 1500,
        "temperature": 0.6,
        "top_p": 0.95,
        "stream": False,
    }


def make_lcb_coding_request(model: str) -> dict[str, Any]:
    """LeetCode-style problem + structured plan request, max_tokens=4096.

    Catches the DS conv-state crash class (Cliff 3-adjacent): on configs with
    VLLM_SSM_CONV_STATE_LAYOUT=DS + spec-decode + AL>1 this shape can trip a
    NotImplementedError in the mamba state path.
    """
    problem = (
        "You are given an integer array nums. Return the length of the longest "
        "subarray with a sum equal to a target value k. If no such subarray "
        "exists, return 0.\n\n"
        "Plan your approach in the format:\n"
        "GOAL: <one-line restatement>\nSTATE: <data structures>\n"
        "ALGO: <key steps>\nEDGE: <edge cases>\nVERIFY: <how to test>\n\n"
        "Then implement `class Solution: def maxSubArrayLen(...)`."
    )
    return {
        "model": model,
        "messages": [{"role": "user", "content": problem}],
        "max_tokens": 4096,
        "temperature": 0.0,
        "stream": False,
    }


def make_reasoning_request(model: str) -> dict[str, Any]:
    """Reasoning-heavy math proof, max_tokens=8192.

    Stresses spec-decode acceptance-length collapse and mamba cache-mode
    interactions over a long generation; catches regressions where generation
    completes but AL collapses past a certain decode depth.
    """
    problem = (
        "Prove that for any positive integer n, the sum 1^3 + 2^3 + ... + n^3 "
        "equals (n(n+1)/2)^2. Show the base case, the inductive hypothesis, the "
        "full algebraic inductive step, and verify for n=1..5. Then derive a "
        "closed form for 1^4 + 2^4 + ... + n^4 by the same technique and verify "
        "for n=1,2,3. Show every algebraic step."
    )
    return {
        "model": model,
        "messages": [{"role": "user", "content": problem}],
        "max_tokens": 8192,
        "temperature": 0.0,
        "stream": False,
    }


# ---------------------------------------------------------------------------
# Ladder construction.
# ---------------------------------------------------------------------------
def ceiling_ladder_rungs(
    n_ctx: int,
    *,
    start_tokens: int = 95_000,
    step_tokens: int = 30_000,
    fraction: float = 0.92,
) -> list[int]:
    """Build the context-ceiling ladder: target token counts from `start_tokens`
    up to `fraction * n_ctx` in `step_tokens` increments, inclusive of the top.

    Returns [] when the top target is at or below `start_tokens` (the small/large
    NIAH probes already cover that range). The bash driver scales each target to
    a filler scale using a calibrated tok/scale ratio, then captures VRAM per
    rung — staggering NIAH so the verdict is a margin curve, not a single
    pass/fail. This is the false-ceiling detector: the first failing rung IS the
    real fillable ceiling (catches the "boots/advertises 262K but only fills
    ~125K" class).
    """
    if n_ctx <= 0:
        return []
    top = int(n_ctx * fraction)
    if top <= start_tokens:
        return []
    rungs = list(range(start_tokens, top, step_tokens))
    if not rungs or rungs[-1] != top:
        rungs.append(top)
    return rungs


def scale_for_target_tokens(target_tokens: int, tok_per_scale_unit: float) -> int:
    """Convert a target token count to a filler scale using the calibrated
    tokens-per-scale-unit ratio. Floored at 100 so a tiny ratio cannot produce a
    degenerate prompt. Mirrors the calibration the upstream ceiling ladder does
    against the live tokenizer (their hardcoded /3.5 heuristic was ~18x off)."""
    if tok_per_scale_unit <= 0:
        raise ValueError("tok_per_scale_unit must be > 0")
    return max(100, int(target_tokens / tok_per_scale_unit))


# ---------------------------------------------------------------------------
# Recall + verdict logic.
# ---------------------------------------------------------------------------
def recall_ok(secret: str, content: str) -> bool:
    """True iff every whitespace token of the needle appears (case-insensitive)
    in the model's content. Token-wise (not substring of the whole phrase) so a
    correct answer with different spacing/punctuation still passes."""
    low = content.lower()
    return all(tok.lower() in low for tok in secret.split())


@dataclass
class ProbeVerdict:
    """Structured outcome of a single probe observation.

    `status` is one of PASS / WARN / FAIL / SKIP. When not PASS/SKIP, `cliff` /
    `patch` / `remediation` carry the Genesis attribution from CLIFF_MAP.
    """

    probe: str
    status: str
    http_code: int = 0
    detail: str = ""
    cliff: str = ""
    patch: str = ""
    remediation: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _attach_cliff(verdict: ProbeVerdict, ref: CliffRef | None) -> ProbeVerdict:
    if ref is not None:
        verdict.cliff = ref.cliff
        verdict.patch = ref.patch
        verdict.remediation = ref.remediation
    return verdict


def verdict_longctx_rung(
    probe_kind: str,
    http_code: int,
    secret: str,
    content: str,
    prompt_tokens: int = 0,
) -> ProbeVerdict:
    """Verdict for one NIAH rung (small/large/ceiling).

    Distinguishes:
      * 400 with no further info -> SKIP (engine rejected above max-model-len;
        the caller is responsible for the target<n_ctx sizing-bug check).
      * 200 + recall -> PASS.
      * 200 + recall miss -> WARN (attention-quality ceiling, NOT a system fault;
        the system filled the context).
      * 500 / 0 / other -> FAIL with the GDN / engine-dead cliff reference.
    """
    if http_code == 400:
        return ProbeVerdict(
            probe=probe_kind,
            status="SKIP",
            http_code=400,
            detail="exceeds --max-model-len (clean engine rejection)",
        )
    if http_code == 200:
        if recall_ok(secret, content):
            return ProbeVerdict(
                probe=probe_kind,
                status="PASS",
                http_code=200,
                detail=f"recalled '{secret}'",
                extra={"prompt_tokens": prompt_tokens},
            )
        return ProbeVerdict(
            probe=probe_kind,
            status="WARN",
            http_code=200,
            detail=(
                f"recall MISS (expected '{secret}') — attention quality ceiling, "
                "system filled the context"
            ),
            extra={"prompt_tokens": prompt_tokens},
        )
    ref = classify_failure(probe_kind, http_code)
    v = ProbeVerdict(
        probe=probe_kind,
        status="FAIL",
        http_code=http_code,
        detail="system-level failure (non-200, not a recall miss)",
        extra={"prompt_tokens": prompt_tokens},
    )
    return _attach_cliff(v, ref)


def verdict_oversize_400(
    probe_kind: str, target_tokens: int, n_ctx: int
) -> ProbeVerdict:
    """Disambiguate an HTTP 400 on a ceiling rung.

    target < n_ctx -> our filler sizing overshot (harness BUG, FAIL).
    target >= n_ctx -> legitimate engine rejection (SKIP).
    """
    if target_tokens < n_ctx:
        return ProbeVerdict(
            probe=probe_kind,
            status="FAIL",
            http_code=400,
            detail=(
                f"target={target_tokens} < n_ctx={n_ctx} but HTTP 400 — filler "
                "sizing overshot (harness calibration bug, not an engine fault)"
            ),
        )
    return ProbeVerdict(
        probe=probe_kind,
        status="SKIP",
        http_code=400,
        detail=f"target={target_tokens} >= n_ctx={n_ctx} (clean engine rejection)",
    )


def verdict_http_probe(
    probe_kind: str,
    http_code: int,
    *,
    content_len: int = 0,
    tool_calls: int = 0,
    completion_tokens: int = 0,
    finish_reason: str = "",
    min_tokens: int = 0,
) -> ProbeVerdict:
    """Verdict for the non-NIAH HTTP probes (tool_prefill, ide_agent, multiturn,
    lcb_coding, reasoning).

    PASS when the engine answered with real output (text, a tool_call, or enough
    completion tokens). The silent-empty case (HTTP 200 but no output at all) is
    a FAIL with the silent-empty cliff. 500 / 0 map through classify_failure to
    the relevant GDN / FA2 / engine-dead reference. `min_tokens` (reasoning
    probe) flags an unexpectedly short generation as a spec-decode-collapse WARN.
    """
    if http_code == 200:
        if content_len >= 50 or tool_calls >= 1:
            if min_tokens and completion_tokens < min_tokens:
                return ProbeVerdict(
                    probe=probe_kind,
                    status="WARN",
                    http_code=200,
                    detail=(
                        f"only {completion_tokens} tokens (<{min_tokens}) — "
                        "possible spec-decode acceptance-length collapse or early stop"
                    ),
                    extra={"completion_tokens": completion_tokens},
                )
            return ProbeVerdict(
                probe=probe_kind,
                status="PASS",
                http_code=200,
                detail=(
                    f"text={content_len} chars, tool_calls={tool_calls}, "
                    f"completion={completion_tokens}, finish={finish_reason or 'n/a'}"
                ),
                extra={"completion_tokens": completion_tokens},
            )
        # HTTP 200 but nothing came back.
        v = ProbeVerdict(
            probe=probe_kind,
            status="FAIL",
            http_code=200,
            detail=(
                f"HTTP 200 but empty response (text={content_len}, "
                f"tool_calls={tool_calls}, finish={finish_reason or '?'})"
            ),
        )
        return _attach_cliff(v, CLIFF_MAP["silent_empty"])
    ref = classify_failure(probe_kind, http_code)
    v = ProbeVerdict(
        probe=probe_kind,
        status="FAIL",
        http_code=http_code,
        detail=f"unexpected HTTP {http_code}",
    )
    return _attach_cliff(v, ref)


if __name__ == "__main__":  # pragma: no cover - manual smoke aid
    import argparse

    ap = argparse.ArgumentParser(
        description="Genesis quality-gate probe core (request/verdict logic)."
    )
    ap.add_argument(
        "--demo",
        action="store_true",
        help="print one of each probe payload + a sample ceiling ladder",
    )
    ap.add_argument("--model", default="qwen3.6-27b")
    ap.add_argument("--n-ctx", type=int, default=262_144)
    args = ap.parse_args()
    if args.demo:
        rng = random.Random(0)
        print(f"# ceiling ladder for n_ctx={args.n_ctx}:")
        print(ceiling_ladder_rungs(args.n_ctx))
        print("# NIAH (scale=150) prompt-char-length:")
        print(
            len(make_niah_request(args.model, 150, rng=rng)["messages"][0]["content"])
        )
        print(
            "# tool-prefill messages:",
            len(make_tool_prefill_request(args.model)["messages"]),
        )
        print("# ide-agent tools:", len(make_ide_agent_request(args.model)["tools"]))
