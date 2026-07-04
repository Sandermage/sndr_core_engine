# KV / VRAM Projector — byte-level fit math

`sndr kv-calc` (alias `sndr fit`) answers the question the envelope check
cannot: **"given THIS context / kv-format / max-num-seqs / tp, what's my ACTUAL
per-card GB, and will it OOM?"**

It is the Genesis analogue of club-3090's `tools/kv-calc.py`. The math
*structure* is shared (per-card weights + growing-KV pool + recurrent state +
activation peak + cudagraph overhead + drafter, with the vLLM "KV pool fills the
budget" capping behavior, a PASS / TIGHT / FAIL verdict, and the `--fit-all`
whole-catalog projection mode). The per-family **calibration coefficients are OUR
OWN**, derived from OUR measured reality on 2× RTX A5000 24 GB, vLLM pin
`0.23.1rc1.dev424+g3f5a1e173` — not copied from club-3090.

> **Provenance note (2026-07):** `dev424` is the pin the calibration was
> *captured* on, not a sign this doc is stale. The anchor is carried forward
> unchanged onto the current pin (`0.23.1rc1.dev748+g2dfaae752`, see
> `sndr/pins.yaml`); the anchor unit test
> (`tests/unit/model_configs/test_kv_projector.py`) keeps the projection
> pinned to the captured telemetry within 10 %. If a future pin changes
> vLLM's KV block allocation, re-capture the live `num_gpu_blocks` anchor per
> the promote instructions in the 27B section below.

## Paper anchors (provenance for the byte-level model)

The byte-level model is paper-anchored, not curve-fit folklore:

| anchor | paper | what it sets |
|---|---|---|
| **PagedAttention** | [arXiv:2309.06180](https://arxiv.org/abs/2309.06180) | the block-paged KV pool fills `mem_util × VRAM` minus the fixed footprint; a *capped* (not refused) pool is the TIGHT verdict |
| **PerfMamba** | [arXiv:2511.22849](https://arxiv.org/abs/2511.22849) | the GDN/Mamba block-state activation peak is `O(γ·D·N·L)`, linear in context — the form of `_ACTIVATION_COEF_BYTES` |
| **TurboQuant** | [arXiv:2504.19874](https://arxiv.org/abs/2504.19874) | the asymmetric **k8v4** KV cache (8-bit K + 4-bit V → 0.75 B/element) the 35B/27B production lanes run |

## Why it exists (the gap it closes)

`sndr preflight` projects the *envelope*: does the rig clear the preset's
declared min-VRAM floor + SM + GPU count? That answers "am I allowed to try?"
It does **not** answer "will the bytes fit?". Before this module Genesis had
**zero** byte-level fit math — no `kv_pool_per_card`, no `solve_max_ctx`, no
`project`. The existing `tools/kv_calc.py` and `memory_estimator.py` read
`config.json` + safetensors from **disk**, so they cannot run from a typed
preset alone.

`sndr/model_configs/kv_projector.py` is **pure and I/O-free**: it drives
entirely off the `ModelShape` dims declared on the preset
(`capabilities.shape` in schema_v2) plus the rig VRAM, so the CLI and the GUI
can project a fit before anything touches the host.

## The math (per card, after TP split)

```
total_gb = weights_gb               # resident weights ÷ TP
         + kv_pool_gb               # growing KV pool — ATTENTION layers only
         + recurrent_state_gb       # GDN / Mamba fixed state (hybrid models)
         + activation_gb            # prefill activation peak (ctx-linear)
         + cudagraph_overhead_gb    # capture + workspace
         + drafter_gb               # MTP / DFlash adder
```

Growing KV per card:

```
kv_pool_bytes = (num_attention_layers × num_kv_heads × head_dim × 2 × bpe) / tp
              × (ctx + mtp_n × 32) × max_num_seqs
```

`bpe` (bytes per KV element) by format:

| format | bytes/elem |
|---|---|
| bf16 / fp16 / `null` (default) | 2.0 |
| fp8_e5m2 / fp8_e4m3 / int8 | 1.0 |
| **turboquant_k8v4** (8-bit K + 4-bit V) | **0.75** |
| int4 | 0.5 |

Only the **full-attention** layers grow the KV pool. Hybrid GDN/Mamba layers
carry a fixed-size recurrent state (modeled separately), not context-linear KV.
This is why our hybrid models have a tiny growing pool — the 35B-A3B has only
10 attention layers with GQA 8:1 (2 KV heads), so a single token costs just
1920 B/card.

### Verdict (vLLM behavior, OUR thresholds)

vLLM sizes the KV pool to fill `mem_util × VRAM` minus the fixed components, so:

- **PASS** — the requested pool fits with room to spare.
- **TIGHT** — the requested pool (ctx × seqs) exceeds the available slack: vLLM
  *caps* the pool, so effective concurrency at full ctx drops below
  `max_num_seqs`. **Still boots.**
- **FAIL** — the fixed footprint alone leaves no room for even one max_ctx
  sequence's growing KV. **Refuses to boot** (real OOM).

## Calibration

### 35B-A3B FP8 TQ-k8v4 — CALIBRATED (strong anchor)

The dev424 **PN403** investigation captured LIVE engine telemetry at the 35B's
production max (`max-model-len=280000`, `max-num-seqs=2`, MTP K=5,
`gpu-memory-utilization=0.9`, TP=2, k8v4):

```
kv_cache_size_tokens = 388620
num_gpu_blocks       = 161
kv_cache_max_concurrency = 1.388   (= 388620 / 280000)
```

The projector's per-token formula (10 attention × 2 KV heads × 128 head_dim ×
2(K+V) × 0.75 / TP2 = 1920 B/card) and its fixed-footprint coefficients
reproduce this point:

| quantity | projected | live | residual |
|---|---|---|---|
| per-token KV / card | 1920 B | 1920 B | exact |
| available-for-KV pool | 0.68 GiB | 0.695 GiB (388620 tok) | **−0.16%** |
| verdict @ 280K / seqs=2 | TIGHT | concurrency 1.388 < 2 (capped) | matches |

The fixed-footprint decomposition (per card, TP=2, util 0.9):

| component | GiB |
|---|---|
| weights (33.53 GiB ÷ 2) | 16.76 |
| cudagraph + workspace | 1.70 |
| MTP drafter (PN348 shared backbone) | 1.00 |
| activation peak @280K | 1.42 |
| recurrent GDN state | 0.02 |
| **fixed footprint** | **20.91** |
| available for KV (21.6 budget − fixed) | **0.69** |

The activation coefficient (363.76 B per GDN-layer per token) is **solved** so
the fixed-footprint reconstruction lands on the live 388,620-token pool — it is
not a guess.

### 27B int4 AutoRound TQ-k8v4 — PROVISIONAL

This model has **no captured `num_gpu_blocks` anchor** — only the
`docs/HARDWARE.md` residency table (32K→~12 GiB, 256K→~22 GiB, 320K→~23 GiB per
card, TP=2) and the HARDWARE.md context formula. The byte-level framework is
identical, but `project()` sets `Projection.provisional=True` and the CLI / the
preflight row print **`[calibration PROVISIONAL]`** so the lower confidence is
honest. The 27B dims (48 layers, 3:1 GDN:full split → 12 attention + 36
recurrent, head_dim 128, GQA-4) are `config.json`-derived but the absolute
per-card GB should be treated as **±1.5 GiB** until a live capture lands.

> To promote the 27B to CALIBRATED: capture its `num_gpu_blocks` /
> `kv_cache_size_tokens` from a live boot log at a known
> ctx/util/TP/kv-format, then add its shape fingerprint to
> `_CALIBRATED_FINGERPRINTS` in `kv_projector.py` (and verify the residual
> reproduces within ~10%, the same gate the 35B anchor test enforces).

## Usage

```bash
# Project a preset against the live rig (nvidia-smi):
sndr kv-calc prod-qwen3.6-35b-balanced

# Offline against a synthetic rig (club-3090 CLUB3090_FAKE_GPUS style):
sndr kv-calc prod-qwen3.6-35b-balanced \
    --fake-gpus "RTX A5000:24564:8.6;RTX A5000:24564:8.6" --kv-breakdown

# Against a builtin hardware definition, or a bare per-card VRAM:
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --rig single-3090-24gbvram
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --card 48

# Override the operating point:
sndr kv-calc prod-qwen3.6-35b-balanced --ctx 131072 --max-num-seqs 4 \
    --kv-format fp8_e5m2

# Largest context that still PASS/TIGHT-fits:
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --solve-max-ctx

# Machine-readable:
sndr --output json kv-calc prod-qwen3.6-35b-balanced --fake-gpus "..."
```

Sample (`--kv-breakdown`, 35B on real 24564 MiB A5000s):

```
kv-calc: prod-qwen3.6-35b-balanced
  rig:        fake (24 GiB/card, TP=2)
  point:      ctx=280,000  seqs=2  kv=turboquant_k8v4  util=0.9
  ────────────────────────────────────────────────────────────
  Model weights (÷TP)                 16.76 GiB / card
  KV pool (requested)                  1.00 GiB / card
  KV pool (actual, capped)             0.68 GiB / card
  Recurrent state (GDN/Mamba)          0.02 GiB / card
  Activation peak                      1.42 GiB / card
  Cudagraph + workspace                1.70 GiB / card
  Drafter (MTP/DFlash)                 1.00 GiB / card
  ────────────────────────────────────────────────────────────
  FIXED footprint                     20.91 GiB / card
  Available for KV                     0.68 GiB / card
  TOTAL (committed)                   21.59 GiB / card  / 21.59 budget  (100%)
  Headroom                             0.00 GiB / card
  ────────────────────────────────────────────────────────────
  VERDICT: ! TIGHT
    · requested KV pool (1.0 GiB) > available (0.7 GiB) — vLLM will cap the
      pool; effective concurrency may be below max_num_seqs=2 at full
      max_ctx=280,000.
```

## `--fit-all` — project the WHOLE catalog into one table

club-3090's `tools/kv-calc.py` ships a `--fit-all` mode that projects **every**
catalog model/preset at once into a single fit table — *"which of my models fit
which card / ctx before I download anything?"*. `sndr kv-calc --fit-all` is the
Genesis equivalent. It iterates every builtin preset, projects each against each
card size (default ladder **24 / 48 / 80 GiB**, or a `--cards 24,48` list), and
prints a per-card table with the projected per-card total, the largest ctx that
still PASS/TIGHT-fits, and the PASS / TIGHT / FAIL / SKIP verdict. It is fully
**offline** (no nvidia-smi) and handles **both engines** — vLLM lanes via
`project_from_shape`, the llama.cpp single-card GGUF lane via
`project_llamacpp_from_shape`. A model that declares **no** `capabilities.shape`
is **SKIP**ped with a note (the projector can't do byte math for it) — it never
errors out and never drops the rest of the table.

```bash
# Default 24/48/80 GiB ladder, every builtin preset, offline:
sndr kv-calc --fit-all

# A custom card list:
sndr kv-calc --fit-all --cards 24,48,80

# Machine-readable (one row per preset × card):
sndr --output json kv-calc --fit-all --card 24
```

Sample (`--cards 24`, trimmed to the byte-level-shaped presets):

```
kv-calc --fit-all  (which of my models fit which card / ctx?)
  cards: 24 GiB
  verdict: ✓ PASS  ! TIGHT  ✗ FAIL   ? SKIP (no shape)

  ═══ 24 GiB / card ════════════════════════════════════════
  PRESET                             ENGINE     VERDICT      TOTAL   MAX-CTX-FIT
  ──────────────────────────────────────────────────────────────────────────────
  llamacpp-qwen3.6-27b-q4km-1x       llama-cpp  ✓ PASS     22.5 GiB          512k *
  prod-gemma4-26b-default            vllm       ? SKIP         —                —
  prod-qwen3.6-27b-tq-k8v4           vllm       ✓ PASS     15.3 GiB         1024k *
  prod-qwen3.6-35b-balanced          vllm       ! TIGHT    21.6 GiB          300k

  * = calibration PROVISIONAL (no live engine anchor) — ±1.5 GiB.
  MAX-CTX-FIT = largest ctx that still PASS/TIGHT-fits that card at the preset's concurrency.
```

The Gemma-4 rows show `? SKIP (no shape)` because their model YAMLs declare no
`shape:` block yet — the projector refuses to guess rather than print an
uncalibrated number. Declaring a Gemma-4 shape (and, ideally, a live anchor)
follows the same promote path as the 27B section above; until someone does,
`sndr preflight` remains the only fit signal for those presets.

The `--fit-all` math is **reused, not duplicated**: every cell's verdict comes
from the same `project_from_shape` / `project_llamacpp_from_shape` the
single-preset path uses, and its `MAX-CTX-FIT` from `solve_max_ctx`. The
`prod-qwen3.6-35b-balanced` row reproduces the dev424 PN403 **TIGHT** point on a
real 24 GiB A5000; bump to `--cards 48` and the same preset goes **PASS** as the
KV pool clears its requested ceiling.

## Wiring into preflight

`sndr preflight` and `/api/v1/preflight` append a **`projected_vram`** row to
the `FitReport` (additive — every envelope check stays). The byte-level verdict
maps onto the envelope's vocabulary: PASS→pass, TIGHT→warn (boots), FAIL→fail.

One subtlety: a FAIL projected against a builtin hardware definition's
**declared** `min_vram_per_gpu_mib` floor (e.g. 22000 MiB for a 24564 MiB
A5000 — a conservative lower bound) is downgraded to **WARN**, because the
floor is not the card's physical capacity and must not hard-block a config that
runs on the real card. A FAIL against a **measured** card (live nvidia-smi /
`--fake-gpus` / `--card`) is a hard block — a real byte-level OOM.

## Where the dims live

The architecture dims are declared under `capabilities.shape` in each model's
schema_v2 YAML (`sndr/model_configs/builtin/model/*.yaml`). They are inherent to
the checkpoint (`config.json`-derived), so they live with the other inherent
capabilities. A model without a `shape:` block still loads and composes; the
projector simply cannot do byte math for it (the CLI and preflight row skip it
and fall back to the envelope check).
```
capabilities:
  shape:
    num_hidden_layers: 40
    num_attention_layers: 10      # full-attention — these grow the KV pool
    num_recurrent_layers: 30      # GDN/Mamba — fixed state, not KV
    hidden_size: 2048
    num_attention_heads: 16
    num_kv_heads: 2               # GQA — sizes the KV pool
    head_dim: 128
    weight_bits: 8
    weights_total_gib: 33.53      # resident, all ranks (÷TP at projection)
    num_experts: 256
    num_experts_per_tok: 8
    mtp_num_layers: 1
```
