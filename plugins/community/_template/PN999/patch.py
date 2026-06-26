# SPDX-License-Identifier: apache-2.0
"""Community patch PN999 — entry-point implementation.

This is the scaffolded stub. Replace `apply()` body with the real patch
logic. The `apply()` callable signature is `apply(target, **kwargs) -> Any`
where `target` is the runtime object the patch wraps (engine, scheduler,
model worker — depends on `family`).

The stub returns None and emits a structured log line so an operator
can confirm the patch is being dispatched even before the real logic
lands.
"""
from __future__ import annotations

import logging

log = logging.getLogger("genesis.patch.PN999")


def apply(target=None, **kwargs):  # noqa: D401 — entry-point hook
    """No-op stub. Replace with the actual patch logic.

    Returning None tells the dispatcher there is nothing to substitute.
    """
    log.info(
        "patch PN999 apply() called — stub no-op "
        "(replace with real implementation)"
    )
    return None
