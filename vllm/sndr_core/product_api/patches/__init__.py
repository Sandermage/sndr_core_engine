# SPDX-License-Identifier: Apache-2.0
"""``product_api.patches`` — pure-Python data layer for the ``sndr patches``
CLI surface. See :mod:`vllm.sndr_core.product_api` for the package contract.

M.6.1 ships read-only queries (listing, explain, doctor, diff-upstream,
bundles). Later phases extend with proof / plan / pn95 helpers (M.6.2-3).
"""
from __future__ import annotations

# Submodules — explicit ``import`` (not ``from .x import y``) so the
# submodule name is preserved as a package attribute even when the
# submodule re-exports a function of the same name (e.g. the
# ``diff_upstream`` function inside the ``diff_upstream`` module).
from . import bundles
from . import diff_upstream
from . import doctor
from . import explain
from . import listing
from . import types

# Public callable / dataclass re-exports. Where a function name would
# collide with its module (``diff_upstream``), we expose the function
# under a non-colliding alias (``diff_upstream_report``) to keep the
# submodule attribute pointing at the module object.
from .bundles import BUNDLES_CATALOG, explain_bundle, list_bundles
from .diff_upstream import diff_upstream as diff_upstream_report
from .doctor import run_doctor
from .explain import explain_patch, resolve_patch_id, suggest_candidates
from .listing import (
    list_patches,
    matches_filters,
    spec_to_row,
    spec_to_row_dict,
)
from .types import (
    BundleSpec,
    DiffReport,
    DoctorReport,
    ExplainView,
    PatchRow,
)

__all__ = (
    # submodules
    "bundles",
    "diff_upstream",
    "doctor",
    "explain",
    "listing",
    "types",
    # listing
    "list_patches",
    "matches_filters",
    "spec_to_row",
    "spec_to_row_dict",
    # explain
    "explain_patch",
    "resolve_patch_id",
    "suggest_candidates",
    # doctor
    "run_doctor",
    # diff_upstream
    "diff_upstream_report",
    # bundles
    "list_bundles",
    "explain_bundle",
    "BUNDLES_CATALOG",
    # types
    "PatchRow",
    "ExplainView",
    "DoctorReport",
    "DiffReport",
    "BundleSpec",
)
