# SPDX-License-Identifier: Apache-2.0
"""Patch-plan resolver — Phase B of the patch-attribution integration plan.

The resolver answers the question "given a composed ModelConfig and a
policy name, which env-flag entries should the runtime actually
include?". It does *not* override the dispatcher's runtime decision
(``should_apply()``); it is a *read-only* explanation layer used by
``sndr patches plan --explain`` and (in Phase C) ``sndr compose
render --policy``.

Contract:

  PatchPlan
    .policy      "compat" | "safe" | "minimal"
    .included    tuple of PatchDecision (env_flag stays in the runtime)
    .excluded    tuple of PatchDecision (env_flag dropped, with reason)
    .warnings    tuple of strings (advisory only; never blocking here)

  PatchDecision per entry carries patch_id, env_flag, value, role,
  reason, note, bench_evidence — everything a CLI explainer needs.

Policy semantics:

  compat  : pass-through. Every flag in cfg.genesis_env with value != "0"
            is included. Excluded set holds only operator-disabled
            (value == "0") entries — so compose render can still tell
            "operator put this here on purpose" from "patch never was on".

  safe    : compat + drop role == "no_op".
            Operator-visible payoff: shorter env block, fewer red
            herrings in diagnose runs. Conservative — won't drop
            anything that *might* be doing work.

  minimal : safe + drop role in {"suspected_regression", "unknown"}.
            For advanced operators who curated attribution and want a
            lean stack. Unknowns are dropped because by definition
            we cannot defend their inclusion in a minimal preset.

See `docs/_internal/PATCH_ATTRIBUTION_COMPOSE_GENERATOR_INTEGRATION_PLAN_2026-05-16_RU.md`
§ 6 for the algorithm and § 5.4 for the data shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid runtime cycle (schema imports nothing from us)
    from .schema import ModelConfig, PatchAttribution


_VALID_POLICIES: tuple[str, ...] = ("compat", "safe", "minimal")


def _build_env_flag_to_patch_id() -> dict[str, str]:
    """Return a reverse map from registry env_flag → patch_id.

    Regex-based env-flag parsing is unreliable for canonical Genesis
    flag names like ``GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ`` —
    a naive regex captures the full suffix and produces patch IDs that
    don't exist in the registry. The reliable mapping is the registry
    itself: every PATCH_REGISTRY entry declares its own ``env_flag``.
    Lifted into a module-level cache because the registry never mutates
    at runtime (frozen dict literal at import time).
    """
    # Imported inside the helper to keep `patch_plan` importable without
    # the full dispatcher stack in scope (resolver tests use synthetic
    # ModelConfigs and don't need the registry there).
    from vllm.sndr_core.dispatcher.registry import PATCH_REGISTRY
    out: dict[str, str] = {}
    for pid, meta in PATCH_REGISTRY.items():
        flag = meta.get("env_flag") if isinstance(meta, dict) else None
        if isinstance(flag, str) and flag:
            out[flag] = pid
    return out


_ENV_FLAG_TO_PATCH_ID: dict[str, str] | None = None


_GENESIS_PREFIX_RE = None  # lazy-initialised, see _strip_genesis_prefix


def _strip_genesis_prefix(env_flag: str) -> str:
    """Strip ``GENESIS_(ENABLE|DISABLE)_`` prefix → bare suffix.

    Synthetic fallback for env flags that don't appear in the live
    registry reverse index (test fixtures, custom operator overrides).
    Returns the input unchanged when the prefix isn't present.
    """
    global _GENESIS_PREFIX_RE
    if _GENESIS_PREFIX_RE is None:
        import re
        _GENESIS_PREFIX_RE = re.compile(r"^GENESIS_(?:ENABLE|DISABLE)_")
    m = _GENESIS_PREFIX_RE.match(env_flag)
    return env_flag[m.end():] if m else env_flag


def _patch_id_from_env_flag(env_flag: str) -> str:
    """Resolve env_flag → patch_id.

    Lookup order:
      1. Registry reverse index — authoritative for canonical Genesis
         flags like ``GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ`` →
         ``PN204`` (the registry stores the full flag name, the
         patch ID is its registry key).
      2. Prefix-strip fallback — for flags not in the registry
         (synthetic fixtures, operator overrides). Strips
         ``GENESIS_(ENABLE|DISABLE)_`` → bare suffix so
         ``GENESIS_ENABLE_PN17`` resolves to ``PN17`` cleanly.
      3. Otherwise return the raw flag (legacy bare flags like
         ``GENESIS_OBSERVABILITY``); attribution lookup then keys
         by the full flag name and role defaults to "unknown".
    """
    global _ENV_FLAG_TO_PATCH_ID
    if _ENV_FLAG_TO_PATCH_ID is None:
        try:
            _ENV_FLAG_TO_PATCH_ID = _build_env_flag_to_patch_id()
        except Exception:
            # Defensive: if the registry can't load (dev env), keep
            # using the prefix-strip fallback below.
            _ENV_FLAG_TO_PATCH_ID = {}
    hit = _ENV_FLAG_TO_PATCH_ID.get(env_flag)
    if hit is not None:
        return hit
    return _strip_genesis_prefix(env_flag)


@dataclass(frozen=True)
class PatchDecision:
    """One env-flag entry's include/exclude decision under a policy.

    `patch_id` is best-effort: it's derived from the env-flag name when
    the flag follows the canonical ``GENESIS_(ENABLE|DISABLE)_<PID>``
    pattern, else the raw flag name. Role-related fields default to
    "unknown" / empty string when the cfg has no attribution for this
    patch.
    """
    patch_id: str
    env_flag: str
    value: str
    decision: str           # "include" | "exclude"
    role: str               # PatchAttribution.role or "unknown"
    reason: str             # human-readable rationale
    note: str = ""          # attribution.note (verbatim)
    bench_evidence: str = ""  # attribution.bench_evidence (verbatim)


@dataclass(frozen=True)
class PatchPlan:
    """Result of `resolve_patch_plan()` — what's in/out under a policy."""
    policy: str
    included: tuple[PatchDecision, ...] = ()
    excluded: tuple[PatchDecision, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def env(self) -> dict[str, str]:
        """Drop-in replacement for ``cfg.genesis_env`` after filtering.

        Order-preserving (Python 3.7+ dict order = insertion order)."""
        return {d.env_flag: d.value for d in self.included}


# ─── Helpers ─────────────────────────────────────────────────────────────


def _attribution_for(
    attribution: dict[str, "PatchAttribution"],
    env_flag: str,
) -> tuple[str, "PatchAttribution | None"]:
    """Return (patch_id, attribution_entry_or_None)."""
    pid = _patch_id_from_env_flag(env_flag)
    return pid, attribution.get(pid)


def _is_truthy(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ─── Main resolver ───────────────────────────────────────────────────────


def resolve_patch_plan(
    cfg: "ModelConfig",
    policy: str = "compat",
) -> PatchPlan:
    """Compute the patch plan for a composed ``ModelConfig``.

    Args:
        cfg: A V1 ModelConfig produced by compose() (or built by hand
            in tests). The resolver reads ``cfg.genesis_env`` for the
            current canonical env-flag set and ``cfg.patches_attribution``
            for the role/note/evidence metadata.
        policy: One of "compat", "safe", "minimal". See module docstring.

    Returns:
        A frozen ``PatchPlan`` with included/excluded decisions and an
        empty warnings tuple (Phase B is read-only; warnings reserved
        for future delivery-path checks in Phase C).

    Raises:
        ValueError: when ``policy`` is not in ``_VALID_POLICIES``.
    """
    if policy not in _VALID_POLICIES:
        raise ValueError(
            f"policy={policy!r} not in {_VALID_POLICIES} — "
            f"resolver supports the documented modes only"
        )

    attribution = getattr(cfg, "patches_attribution", {}) or {}
    genesis_env = getattr(cfg, "genesis_env", {}) or {}

    included: list[PatchDecision] = []
    excluded: list[PatchDecision] = []

    for env_flag, raw_value in genesis_env.items():
        value = str(raw_value)
        pid, attr = _attribution_for(attribution, env_flag)
        role = attr.role if attr is not None else "unknown"
        note = (attr.note or "") if attr is not None else ""
        bench = (attr.bench_evidence or "") if attr is not None else ""

        # First filter: operator-disabled (value=="0") is always excluded
        # under every policy. The decision surfaces in `.excluded` so a
        # downstream diff can show "operator turned this off here".
        if not _is_truthy(value):
            excluded.append(PatchDecision(
                patch_id=pid, env_flag=env_flag, value=value,
                decision="exclude", role=role,
                reason="operator-disabled in genesis_env (value != truthy)",
                note=note, bench_evidence=bench,
            ))
            continue

        # Policy filters — applied in order of aggressiveness.
        drop_for: str | None = None
        if policy in ("safe", "minimal") and role == "no_op":
            drop_for = "role='no_op' (declared inactive on this config)"
        elif policy == "minimal" and role == "suspected_regression":
            drop_for = "role='suspected_regression' (minimal policy)"
        elif policy == "minimal" and role == "unknown":
            drop_for = "role='unknown' (no attribution; minimal policy)"

        if drop_for is not None:
            excluded.append(PatchDecision(
                patch_id=pid, env_flag=env_flag, value=value,
                decision="exclude", role=role,
                reason=drop_for, note=note, bench_evidence=bench,
            ))
        else:
            included.append(PatchDecision(
                patch_id=pid, env_flag=env_flag, value=value,
                decision="include", role=role,
                reason=f"role={role!r} kept under policy={policy!r}",
                note=note, bench_evidence=bench,
            ))

    return PatchPlan(
        policy=policy,
        included=tuple(included),
        excluded=tuple(excluded),
        warnings=(),
    )


__all__ = ["PatchDecision", "PatchPlan", "resolve_patch_plan"]
