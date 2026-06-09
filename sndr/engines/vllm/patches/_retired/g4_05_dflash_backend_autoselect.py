# SPDX-License-Identifier: Apache-2.0
"""G4_05 — RETIRED. Superseded by vllm-project/vllm#39930.

Original purpose
================

When Gemma 4 was first integrated, the DFlash drafter backend selector
on Ampere SM 8.6 silently mis-routed `non-causal head_dim=256` to a
backend that segfaulted. G4_05 patched the autoselect logic in
``vllm/v1/spec_decode/dflash/...`` to force the working backend.

Why retired
===========

vllm#39930 landed the equivalent fix upstream on 2026-05-22 (commit
SHA in pin). Our pin (``0.22.1rc1.dev259+g303916e93``, 2026-05-15) is
post-merge — the upstream fix is in our installed vllm. G4_05 backport
is therefore an exact duplicate.

Registry entry was kept (``lifecycle: retired``,
``apply_module: ...g4_05_dflash_backend_autoselect``) for audit-trail
continuity. The module here returns a no-op skipped result so the
dispatcher doesn't raise ``ModuleNotFoundError`` at boot.

When to truly delete
====================

The dispatcher tuple in ``_per_patch_dispatch.py`` line ~6898 (and
this stub) can be removed entirely when:

* The next vllm pin bump moves past dev259 — at that point the
  registry-only retire pattern is well-established and removing the
  stub is safe.
* No backport regression is observed for ≥ 1 month of PROD.

For now (2026-06-09) we keep the stub for clean boot logs.

Restore reference
=================

If we ever roll back the vllm pin below dev259 and need this patch
again, the original wiring lived at::

  sndr/engines/vllm/patches/model_compat/gemma4/g4_05_dflash_backend_autoselect.py

before being moved here on 2026-05-24. Git history retains the full
source.
"""
from __future__ import annotations


def apply() -> tuple[str, str]:
    """No-op skipped — patch retired."""
    return "skipped", (
        "G4_05 retired (2026-05-24): upstream vllm#39930 merged the equivalent "
        "fix; our pin 0.22.1rc1.dev259 (2026-05-15) is post-merge. Original "
        "Genesis backport is a duplicate."
    )


def is_applied() -> bool:
    """Retired patches are never applied."""
    return False
