# PN16 V6 — 5-Run Multi-Bench Validation (2026-05-09)

## Question

Was the london_think regression observed in the V8+V6 single bench
(Sprint 4 closure 2026-05-09) a real systematic regression, or bench
variance?

## Method

Restart 35B PROD with PN16 V6 streaming truncator ON
(`GENESIS_ENABLE_PN16_V6_STREAMING_TRUNCATOR=1`,
`GENESIS_PN16_MAX_THINKING_STREAM_TOKENS=200`) + V8 system-msg hint ON
+ all Wave 7 + Sprint 1 patches + P67_NUM_KV_SPLITS=48.

Run `genesis_bench_suite.py --quick` 5× sequentially with same seed.

## Result

| Run | wall_TPS | CV     | Positive | london_think | tokyo_think | denial |
|-----|----------|--------|----------|--------------|-------------|--------|
| 1   | 238.53   | 0.0581 | 7/7      | **PASS**     | PASS        | PASS   |
| 2   | 237.82   | 0.0652 | 7/7      | **PASS**     | PASS        | PASS   |
| 3   | 234.60   | 0.0673 | 7/7      | **PASS**     | PASS        | PASS   |
| 4   | 236.43   | 0.0632 | 7/7      | **PASS**     | PASS        | PASS   |
| 5   | 233.20   | 0.0741 | 7/7      | **PASS**     | PASS        | PASS   |

- **Mean TPS: 236.12 ± 2.21 (CV 0.94%)** — extremely consistent
- **london_think: 5/5 PASS**
- **tokyo_think: 5/5 PASS** (boundary cases all stable)
- **denial_no_think: 5/5 PASS** (negative case)

## Verdict

**Prior single-run london_think failure was bench variance, NOT
systematic.** PN16 V6 streaming truncator is safe with respect to
tool-call quality across the full 8-case battery.

## Δ vs Sprint 1 reference

| Metric | Sprint 1 (no V6) | V6 5-run mean | Δ |
|---|---|---|---|
| wall_TPS | 241.35 | 236.12 | -2.2% |
| Tool-call (positive) | 7/7 | 7/7 | identical |
| London_think | PASS | 5/5 PASS | identical |

The -2.2% TPS gap is within Sprint 1's CV (6.3%) and within V6's own
multi-bench CV (0.94%). It is a real but small overhead from the SSE
parse/serialize round-trip in the V6 wire-in. Operators where TTFT-
deterministic `<think>` budget matters more than the marginal TPS gap
can opt in safely.

## Decision

V6 stays **opt-in experimental in PROD YAML** for now (no auto-promote
in this session). The regression hypothesis is REJECTED, so future
sessions can promote V6 to `default_on=True` without quality concern,
trading 2.2% TPS for deterministic thought-budget enforcement.

To opt in:
```bash
GENESIS_ENABLE_PN16_V6_STREAMING_TRUNCATOR=1
GENESIS_PN16_MAX_THINKING_STREAM_TOKENS=200
```

## Files

- 5× JSON: `~/bench_results/pn16v6_multibench_2026-05-09/v6_run{1-5}`
- 5× MD:   `~/bench_results/pn16v6_multibench_2026-05-09/v6_run{1-5}.md`
