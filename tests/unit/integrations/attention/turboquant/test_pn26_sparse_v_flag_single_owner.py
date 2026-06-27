# SPDX-License-Identifier: Apache-2.0
"""Integrity lock for the ``GENESIS_ENABLE_PN26_SPARSE_V`` flag — it must
have exactly ONE truthful behavior, owned by the real PN26b kernel.

Background (Class-3 silent-no-op + double-meaning flag)
-------------------------------------------------------
The PN26 master orchestrator (``pn26_tq_unified_perf``, env
``GENESIS_ENABLE_PN26_TQ_UNIFIED``) used to carry a dead "deferred"
sub-branch that ALSO read ``GENESIS_ENABLE_PN26_SPARSE_V`` and, when set,
logged "Sparse V tile-skip will be wired in next iteration" while doing
nothing. But ``GENESIS_ENABLE_PN26_SPARSE_V`` is the registry flag for
PN26b, whose REAL, tested kernel dispatcher lives in
``pn26_sparse_v_kernel.py``. The dead branch gave the flag a second,
no-op meaning.

Contract pinned here:
  * the master orchestrator source no longer references
    ``GENESIS_ENABLE_PN26_SPARSE_V`` nor the dead "deferred"/"next
    iteration" wording — the flag is owned solely by PN26b;
  * the master ``apply()`` status reflects only the centroids sub-patch
    (the work it actually does);
  * PN26b's real kernel apply() path is unchanged: it still SKIPS when
    the flag is off and is the sole consumer of the flag.

No torch/CUDA required for the source-level + skip-path checks.
"""
from __future__ import annotations

import importlib
import inspect

MASTER_PATH = (
    "sndr.engines.vllm.patches.attention.turboquant.pn26_tq_unified_perf"
)
KERNEL_PATH = (
    "sndr.engines.vllm.patches.attention.turboquant.pn26_sparse_v_kernel"
)


def _master_source() -> str:
    return inspect.getsource(importlib.import_module(MASTER_PATH))


def _strip_comments_and_docstrings(src: str) -> str:
    """Return only executable token text — drops comments and string
    literals (incl. docstrings) so we can assert the flag is never READ
    in code while still allowing prose that documents the boundary."""
    import io
    import tokenize

    out: list[str] = []
    toks = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok in toks:
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_master_does_not_read_sparse_v_flag_in_code():
    """The master orchestrator must NOT consume PN26b's flag in code — that
    flag has a single owner (the real kernel). Prose/comments documenting
    the boundary are allowed; an actual os.environ/getenv read is not."""
    code = _strip_comments_and_docstrings(_master_source())
    assert "GENESIS_ENABLE_PN26_SPARSE_V" not in code, (
        "PN26 master must not READ PN26b's flag in code (dead double-meaning)"
    )
    # Belt-and-braces: no env-read call form mentioning the sub-flag at all.
    raw = _master_source()
    for read_form in ("environ.get(", "os.getenv(", "getenv("):
        idx = raw.find(read_form)
        while idx != -1:
            window = raw[idx: idx + 120]
            assert "SPARSE_V" not in window, (
                "PN26 master must not read any SPARSE_V env flag"
            )
            idx = raw.find(read_form, idx + 1)


def test_master_dead_deferred_branch_removed():
    """The 'will be wired in next iteration' dead branch wording is gone,
    and no sparse-V status placeholder ('scaffold-only') remains in code."""
    src = _master_source().lower()
    assert "next iteration" not in src
    assert "scaffold-only" not in src
    # The dead-branch sentinel variable must not exist.
    assert "sparse_v_status" not in src
    assert "sparse_v_enabled" not in src


def test_master_apply_status_reflects_only_centroids(monkeypatch):
    """With no vLLM install root resolvable, master apply() SKIPS cleanly
    and the reason mentions only its real work (centroids), never a
    sparse-V claim."""
    monkeypatch.setenv("GENESIS_ENABLE_PN26_TQ_UNIFIED", "1")
    monkeypatch.setenv("GENESIS_ENABLE_PN26_SPARSE_V", "1")
    master = importlib.import_module(MASTER_PATH)
    status, reason = master.apply()
    # On a host without a resolvable vLLM tree this is a clean skip.
    assert status in ("skipped", "applied", "failed")
    assert "sparse v" not in reason.lower()
    assert "sparse_v" not in reason.lower()


def test_pn26b_kernel_is_sole_flag_owner_and_skips_when_off(monkeypatch):
    """PN26b's real kernel still owns the flag: off → clean skip."""
    monkeypatch.delenv("GENESIS_ENABLE_PN26_SPARSE_V", raising=False)
    kernel = importlib.import_module(KERNEL_PATH)
    status, reason = kernel.apply()
    assert status == "skipped"
    assert "opt-in" in reason.lower()


def test_pn26b_kernel_reads_the_flag():
    """Sanity: the real kernel is the module that reads the flag."""
    src = inspect.getsource(importlib.import_module(KERNEL_PATH))
    assert "GENESIS_ENABLE_PN26_SPARSE_V" in src
