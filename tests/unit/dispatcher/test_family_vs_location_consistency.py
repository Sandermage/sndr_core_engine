"""Registry `family` field MUST match the actual integrations/ directory.

Background — 2026-05-12 audit found `PN26b` declared `family: "memory"` but
the wiring file `pn26_sparse_v_kernel.py` lived under
`integrations/attention/turboquant/`. Drift like this:
- Confuses contributors browsing by subsystem
- Breaks `sndr family <X> status` CLI output
- Misroutes the family contract test (or skips the patch silently)

This test asserts: for every patch that DOES have a wiring file under
`integrations/<dir>/`, the registry's `family` field maps to that `<dir>`.
Patches without a wiring file (`apply_module=None` or living in
`vllm/sndr_core/kernels/` etc.) are exempt — their family is informational.
"""

from __future__ import annotations

# Family-string → canonical relative path under integrations/.
# Dotted families like `attention.turboquant` map to `attention/turboquant`.
# Special: `model_specific` is informational, no specific subdir (skipped).
_FAMILY_TO_DIR = {
    "attention.gdn": "attention/gdn",
    "attention.turboquant": "attention/turboquant",
    "attention.flash": "attention/flash",
    "tool_parsing": "tool_parsing", "reasoning": "reasoning",
    "serving": "serving", "spec_decode": "spec_decode",
    "scheduler": "scheduler", "worker": "worker",
    "kv_cache": "kv_cache", "moe": "moe", "quantization": "quantization",
    "kernels": "kernels", "compile_safety": "compile_safety",
    "loader": "loader", "middleware": "middleware",
    "memory": "memory", "observability": "observability",
    "lora": "lora", "multimodal": "multimodal",
    "offload": "offload",        # PN102/PN104/PN105 — offload patches
    "streaming": "streaming",    # PN200/PN201/PN202/PN203 — streaming-architecture memory mgmt
}


def test_registry_family_matches_integrations_subdir():
    """For every patch with a wiring file under `integrations/<subdir>/`,
    registry `family` field MUST map to that exact subdir.
    """
    from vllm.sndr_core.dispatcher import PATCH_REGISTRY
    from vllm.sndr_core.compat.categories import module_for

    drift = []
    for pid, meta in PATCH_REGISTRY.items():
        fam = meta.get("family")
        if not fam or fam == "model_specific":
            continue
        # Retired patches live under `integrations/_retired/` by design;
        # the registry `family` field remains as the original wiring family
        # for audit trail. Skip them from the family-path consistency check.
        if meta.get("lifecycle") == "retired":
            continue
        mod = module_for(pid)
        if mod is None or "integrations." not in mod:
            # Patch has no wiring file under integrations/ (e.g. legacy
            # pre-dispatcher patch living in kernels/, or registry-only
            # diagnostic entry). family field is informational only.
            continue
        # Extract subdir from dotted module path:
        #   `vllm.sndr_core.integrations.attention.turboquant.pn14_*`
        # → `attention/turboquant`
        after_int = mod.split("integrations.", 1)[1]
        subdir = after_int.rsplit(".", 1)[0].replace(".", "/")
        expected = _FAMILY_TO_DIR.get(fam)
        if expected is None:
            drift.append(f"{pid}: family={fam!r} is not in _FAMILY_TO_DIR map")
            continue
        if subdir != expected:
            drift.append(
                f"{pid}: registry family={fam!r} → integrations/{expected}/ "
                f"but wiring lives at integrations/{subdir}/"
            )
    assert not drift, (
        f"{len(drift)} family/location drift case(s):\n  "
        + "\n  ".join(drift[:10])
    )
