# SPDX-License-Identifier: Apache-2.0
"""G4_T1 marker-only stub — apply contract for the registry.

The actual fix is the vendored parser file at
``g4_t1_gemma4_tool_parser_pr42006_overlay.py`` which gets bind-
mounted into the container by the operator's launcher. That file
imports the real ``regex`` package (a vllm/upstream dependency)
which is intentionally NOT available in the test environment.

This marker module exists so:

  - ``test_patch_apply_contracts.TestApplyModule`` can import the
    apply_module path without pulling in the heavy parser
    dependencies.
  - The dispatcher's ``should_apply()`` and ``apply()`` lifecycle
    work uniformly for every registry row (the vendored overlay
    isn't a Genesis runtime patch — it's an operator-side bind-
    mount — so apply() returns "skipped" with a clear reason).

If the operator follows the launcher pattern documented in the
overlay file's header, the vendored parser takes effect via the
``-v`` docker mount. This marker is only the registry-side contract.
"""
from __future__ import annotations


def apply() -> tuple[str, str]:
    """Marker-only apply — G4_T1 is deployed via operator-side bind-mount.

    Returns ``("skipped", "<reason>")`` so the dispatcher logs the
    correct lifecycle even though no runtime mutation is performed.
    """
    return "skipped", (
        "G4_T1 is operator-side ONLY — the vendored gemma4 tool-parser "
        "(vllm PR #42006 backport) is deployed via the launcher's "
        "`docker run -v $REPO/vllm/sndr_core/integrations/tool_parsing/"
        "g4_t1_gemma4_tool_parser_pr42006_overlay.py:$TGT/tool_parsers/"
        "gemma4_tool_parser.py:ro` bind-mount. Genesis dispatcher does "
        "NOT call into the vendored file directly. Verify the mount "
        "from inside the container: `docker exec <c> head -5 "
        "/usr/local/lib/python3.12/dist-packages/vllm/tool_parsers/"
        "gemma4_tool_parser.py` should show the Genesis G4_T1 header."
    )


def is_applied() -> bool:
    """G4_T1 has no in-process state — operator-side mount or absent."""
    return False


__all__ = ["apply", "is_applied"]
