# Release Policy — Genesis vLLM Patches

This document is the **single source of truth** for which patch-proof
mode gates a public Genesis release. It exists to remove the
ambiguity flagged by the 2026-05-15 production-readiness audit (C1):
two release-check modes existed (`require-static` and `require-baseline`)
without an explicit decision which one is the current release gate.

## TL;DR

| Mode | Status | Where it runs |
| --- | --- | --- |
| `require-static` | **Active release gate** | `make evidence --release`, CI |
| `require-bench` | Optional ratchet | `make audit-release-check-bench-attached` |
| `require-baseline` | Optional ratchet (strict) | `make audit-release-check-baseline-optional` |

A release ships when `require-static` passes for every registry entry.
The two stricter modes are run on demand by operators preparing a
hardened deploy.

## Mode definitions

### `require-static` — current release gate

Every entry in `PATCH_REGISTRY` must have a static-proof JSON under
`evidence/patch_proof/<id>__*.json` that records:

- registry presence (id resolves)
- `apply_module` resolution (file exists OR `_retired/` exemption)
- env-flag declaration matches `vllm/sndr_core/env.py::Flags`
- dispatcher wiring matches expectations (legacy `@register_patch` OR
  spec-driven dispatch via `dispatcher/spec.py`)

No bench data is required. The proof artifact is produced by
`sndr patches release-check --mode require-static` and persists across
runs under `evidence/patch_proof/`.

Why this is the gate: every patch the registry advertises must at least
*resolve* before release; bench data quality varies per patch and is
hardware-bound, so making it mandatory would block every release until
operators re-bench all 169 entries on their rig. See
`audit_release_check_baseline-optional` rationale in the Makefile for
the historical decision.

### `require-bench` — optional ratchet (default-on subset)

Same as `require-static` PLUS at least one bench attachment per patch
(any `bench_attached` artifact, regardless of baseline comparison).
Operators preparing a hardened deploy run this against the default-on
subset of their preset first, then expand coverage incrementally.

### `require-baseline` — optional ratchet (strict)

Same as `require-bench` PLUS the bench must carry a baseline
comparison (`bench_with_baseline`). This is the strictest mode and
takes the longest to satisfy because every patch needs a reference
bench run.

Currently 0/169 entries carry `bench_with_baseline`. Operators who
want to adopt this gate should:

1. Promote the **default-on patches in production presets** first
   (smallest set that actually matters in steady-state traffic).
2. Then **all default-on** patches across all presets.
3. Then **stability-critical** patches (PN95 tier-aware cache,
   PN116/118/119 TurboQuant backports, PN132/133 correctness fixes).
4. Then everything else (community / research / drift-sensitive).

## How to run each gate

```bash
# Release-gate (current public policy) — used by CI + make evidence
make audit-release-check
python3 -m vllm.sndr_core.cli patches release-check --mode require-static

# Hardened ratchet 1 — at least one bench attached per patch
make audit-release-check-bench-attached
python3 -m vllm.sndr_core.cli patches release-check --mode require-bench

# Hardened ratchet 2 — bench with baseline comparison per patch
make audit-release-check-baseline-optional
python3 -m vllm.sndr_core.cli patches release-check --mode require-baseline
```

The `make_evidence.py --release` aggregate wires the **release gate**
into a 43-of-43 audit panel. Operators who want one of the ratchets
to participate in that aggregate should add the matching target to
`scripts/make_evidence.py` and document the change in this file.

## Lifecycle of a policy decision

1. **Proposal.** A maintainer opens a PR that bumps `make_evidence.py`
   to a stricter default mode. The PR description must show the
   percentage of registry entries that pass under the proposed gate
   today.
2. **Coverage runway.** The PR remains open until at least 95% of
   default-on entries in **all** production presets pass under the
   proposed gate.
3. **Cutover.** The PR merges, `RELEASE_POLICY.md` is updated to
   reflect the new gate, and any operator-facing scripts are
   refreshed (Makefile target description, README badge, CI YAML).

Inverse direction (loosening the gate) is allowed only when the
stricter mode causes a release-blocking regression that cannot be
fixed in the short window of a release candidate; loosen-then-fix is
preferred over no-release. Such loosenings must reference the
upstream bug, the regression-test that catches it next time, and the
target date for re-enabling the strict gate.

## Related artefacts

- `Makefile` targets: `audit-release-check*`
- CLI: `vllm/sndr_core/cli/patches.py::release_check`
- Implementation: `vllm/sndr_core/audit/release_check.py`
- CI workflow: `.github/workflows/test.yml` (`make evidence --release`)
- Audit history is captured per-release in the production-readiness
  audit reports that maintainers attach to each release artifact.

## History

| Date | Change |
| --- | --- |
| 2026-05-11 | Initial `require-static` policy adopted as the release gate; `require-baseline` introduced as a strict ratchet. |
| 2026-05-15 | Audit flagged ambiguity (C1): `audit-release-check-strict` Makefile target name suggested it was a release-blocker, but `make_evidence.py --release` only ran `require-static`. |
| 2026-05-16 | Audit C1 closure — renamed strict target to `audit-release-check-baseline-optional`, added `RELEASE_POLICY.md` (this file) as canonical source of truth, added `bench-attached` ratchet as the bridge between static-only and full-baseline coverage. |
