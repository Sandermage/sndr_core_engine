# SPDX-License-Identifier: Apache-2.0
"""Doc/help preset-key drift gate.

Integrity-audit 2026-07-04 (NOT_YET_UNIFIED verdict) found the operator
surface teaching keys that no longer resolve: docs/INSTALL.md's primary
quick-start used the Phase-10-sunset V1 key ``a5000-2x-35b-prod`` and
scripts/launch/README.md advertised four archived dflash presets — every
copy-pasted command failed with ``config not found``. This gate prevents
the recurrence class:

  1. every ``sndr launch <key>`` command in operator-facing markdown must
     resolve against the live V2 preset registry (or a builtin model id —
     the deployment resolver accepts both);
  2. the retired V1 key must not appear on the operator surface at all —
     migration history belongs to CHANGELOG / audit scripts / skipif-guarded
     legacy tests, not to docs an operator follows on day one.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# Operator-facing files: what a day-one operator actually reads/copy-pastes.
_OPERATOR_DOCS = [
    "README.md",
    "docs/INSTALL.md",
    "docs/QUICKSTART.md",
    "docs/USAGE.md",
    "docs/BENCHMARKS.md",
    "docs/CLI_REFERENCE.md",
    # docs/TROUBLESHOOTING.md is deliberately OUT of scope: its
    # emergency-rollback runbook restores the historical V1 baseline from git
    # history and self-documents that its V1 key + vllm/sndr_core paths are
    # intentional ("do not rewrite these to sndr/").
    "docs/GUI.md",
    "docs/TUI.md",
    "docs/FAQ.md",
    "scripts/launch/README.md",
]

# Live help/example surfaces inside the CLI + operator tools.
_OPERATOR_SOURCE = [
    "sndr/cli/main.py",
    "sndr/cli/legacy/config.py",
    "sndr/cli/legacy/compose.py",
    "sndr/cli/legacy/patches.py",
    "sndr/cli/legacy/install.py",
    "sndr/cli/legacy/report.py",
    "sndr/cli/legacy/memory.py",
    "sndr/cli/commands/chat.py",
    "sndr/compat/models/pull.py",
    "sndr/product_api/legacy/deployment.py",
    "tools/kv_calc.py",
    "scripts/launch.sh",
    "scripts/cold_install_smoke.sh",
]

# Phase-10 V1 sunset: retired monolithic keys whose V2 successors are the
# canonical operator vocabulary now (see scripts/audit_no_new_v1.py).
_RETIRED_V1_KEYS = (
    "a5000-2x-35b-prod",
    "a5000-2x-27b-int4-tq-k8v4",
)

# Real preset ids always carry digits (qwen3.6/gemma4/27b/...); requiring one
# filters flag-value captures (`--runtime docker`) and template text
# (`prod-<key>`) without missing a genuine key.
_LAUNCH_RE = re.compile(r"sndr launch (?:--[a-z-]+ )*([a-z0-9][a-z0-9.\-]+)")


def _resolvable_keys() -> set[str]:
    # `sndr launch` resolves V2 preset cards only (verified 2026-07-04:
    # builtin model ids do NOT resolve through the launch CLI).
    from sndr.model_configs import registry_v2

    return set(registry_v2.list_presets())


def test_docs_sndr_launch_keys_resolve():
    """Every `sndr launch <key>` an operator can copy-paste must resolve."""
    valid = _resolvable_keys()
    bad: list[str] = []
    for rel in _OPERATOR_DOCS:
        path = _REPO / rel
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for key in _LAUNCH_RE.findall(line):
                if not re.search(r"\d", key):
                    continue  # flag value / template text, not a preset id
                if key not in valid:
                    bad.append(f"{rel}:{i}: sndr launch {key!r} does not resolve")
    assert not bad, (
        "operator docs teach `sndr launch` keys that do not resolve against "
        "the live preset/model registry:\n  " + "\n  ".join(bad)
    )


def test_no_retired_v1_keys_on_operator_surface():
    """The Phase-10-sunset V1 keys must not appear on the operator surface."""
    hits: list[str] = []
    for rel in _OPERATOR_DOCS + _OPERATOR_SOURCE:
        path = _REPO / rel
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for key in _RETIRED_V1_KEYS:
                if key in line:
                    hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not hits, (
        "retired V1 preset keys leaked onto the operator surface (use the V2 "
        "successors, e.g. prod-qwen3.6-35b-balanced):\n  " + "\n  ".join(hits)
    )
