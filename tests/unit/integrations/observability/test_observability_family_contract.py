# SPDX-License-Identifier: Apache-2.0
"""observability family contract — Theme 4 expansion (2026-05-11).

Single patch: PN122. Was registry-tagged family=
"worker" pre-2026-05-11 audit (filesystem/category mismatch) — fixed
to "observability" in v2 retire batch.
"""
from tests.unit.integrations._family_contract_helpers import (
    make_family_contract_class,
    make_family_registry_class,
)

PATCHES = [
    (
        "vllm.sndr_core.integrations.observability.pn122_sprint26_cudagraph_dispatch_trace",
        "PN122",
    ),
]


class TestObservabilityPatchContract(
    make_family_contract_class("observability", PATCHES)
):
    pass


class TestObservabilityFamilyRegistry(
    make_family_registry_class("observability", PATCHES)
):
    pass
