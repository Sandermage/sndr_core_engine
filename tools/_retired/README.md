# `tools/_retired/` — archived tools

Same lifecycle pattern as `vllm/sndr_core/integrations/_retired/`: scripts
or harnesses that were canonical at some point but have been **superseded
or made obsolete** by a newer tool. Kept on disk for git-blame archeology
and for occasional re-runs against historical configs.

## Policy

A tool transitions here when **one** of:

1. **Superseded by a newer harness.** The newer tool covers the same +
   broader testing scope.
2. **Tied to a sprint / phase that ended.** Phase-specific harnesses live
   here once that phase is closed (the `runs/` artefact remains in
   `docs/_internal/runs/`).
3. **Functionality merged into a CLI command.** E.g. `sndr bench …`
   absorbed several ad-hoc shell scripts.

DO NOT delete retired files unless a follow-up audit explicitly confirms
they reference no still-used artefact (run dirs, baseline JSON, etc.).

## Inventory

| File | Date archived | Successor | Reason |
|---|---|---|---|
| `phase1_test_harness.sh` | 2026-05-15 | `tools/multi_conc_bench.py` + `tools/genesis_bench_suite.py` | Phase 1 was the V8/Wave 1 era; Wave 10 multi-conc + Genesis bench suite cover all 6 sub-tests with better resolution. Last live run: 2026-05-01. |
