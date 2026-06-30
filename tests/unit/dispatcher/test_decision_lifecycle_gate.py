# SPDX-License-Identifier: Apache-2.0
"""GAP4 — lifecycle hard-gate in ``should_apply()``.

A ``lifecycle=retired`` patch must NOT engage via an apply path (env override
or legacy default-on), even when its ENABLE flag is set and its apply_module is
still present in the tree. This is the pin-upgrade break-safety backstop: a
patch retired because upstream merged it (or because it is incompatible with
the new engine) must be hard-skipped on dispatch so a stale ENABLE flag carried
across a pin bump can't silently re-engage dead code. Escape: GENESIS_ALLOW_RETIRED=1.
"""
import os
from unittest import mock

# A real retired, opt-in patch with an ENABLE flag and no version_range — so
# the version gate cannot mask the lifecycle gate under test.
RETIRED_PID = "P61"
RETIRED_FLAG = "GENESIS_ENABLE_P61_QWEN3_MULTI_TOOL"


def _should_apply():
    from sndr.dispatcher.decision import should_apply
    return should_apply


def _clean_env(**extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GENESIS_ENABLE_", "GENESIS_DISABLE_",
                                "SNDR_DISABLE_", "GENESIS_ALLOW_RETIRED",
                                "GENESIS_LEGACY_DEFAULT_ON", "GENESIS_ENFORCE_VERSION_RANGE"))}
    env.update(extra)
    return env


def test_retired_patch_skips_even_with_enable_flag():
    """The GAP4 hole: ENABLE flag set on a retired patch used to apply it."""
    with mock.patch.dict(os.environ, _clean_env(**{RETIRED_FLAG: "1"}), clear=True):
        ok, reason = _should_apply()(RETIRED_PID)
    assert not ok, f"retired patch must hard-skip even with {RETIRED_FLAG}=1, got apply: {reason}"
    assert "lifecycle" in reason.lower() and "retired" in reason.lower(), reason


def test_allow_retired_escape_hatch_engages():
    """GENESIS_ALLOW_RETIRED=1 lets diagnostics force a retired patch through."""
    with mock.patch.dict(os.environ,
                         _clean_env(**{RETIRED_FLAG: "1", "GENESIS_ALLOW_RETIRED": "1"}),
                         clear=True):
        ok, reason = _should_apply()(RETIRED_PID)
    assert ok, f"GENESIS_ALLOW_RETIRED=1 should engage the retired patch, got skip: {reason}"
