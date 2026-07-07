# Hardware Guide

This document describes which hardware Genesis runs on, how much VRAM you need for each supported model, and how to choose between single-GPU and multi-GPU configurations. All numbers are empirical from the Genesis reference rig (`2× RTX A5000 24 GiB`, PCIe Gen4 x16, no NVLink) unless explicitly noted otherwise. Numbers on other Ampere/Ada cards are within ±5% per VRAM bandwidth scaling, but please verify on your own setup.

If your card is not listed and your workload is unusual, run `python3 -m sndr.compat.gpu_profile --explain` after install — it prints per-patch recommendations based on your detected SM, HBM bandwidth, and L2 size.

## Supported GPU Classes

| Architecture | SM | Examples | Status |
|---|---|---|---|
| Blackwell | 10.0 / 12.0 | RTX 5090, R6000 Pro 96GB | Supported (FP8 native, fastest) |
| Hopper | 9.0 | H100, H200 | Supported (FP8 native) |
| Ada Lovelace | 8.9 | RTX 4090, 4080 | Supported (no NVLink on consumer) |
| Ampere | 8.6 | RTX 3090, 3080, A5000, A6000 | Supported (Genesis reference) |
| Ampere | 8.0 | A100 | Supported |
| Turing / Volta / Pascal | 7.x or lower | V100, T4, RTX 20-series | NOT SUPPORTED — pre-Ampere skips most patches and many Triton kernels |
| AMD ROCm | n/a | MI250, MI300 | NOT SUPPORTED — Triton kernels are CUDA-only |

Most Genesis kernels gate on `compute_capability >= (8, 6)`. The dispatcher will print `[SKIP — pre-Ampere]` and fall back to upstream paths if you boot on Turing or earlier.

**Per-class notes** (the FAQ has the full "can I use an X?" answers):
- **RTX 3090 / A5000 (Ampere 8.6)** — the reference class. Presets, VRAM
  budgets, and TPS numbers are calibrated here. Dual = PCIe P2P, no NVLink.
- **RTX 4090 (Ada 8.9)** — same 24 GiB envelope, clears the kernel gate;
  faster raw compute so expect ≥ reference TPS. No NVLink; idle VRAM a touch
  tighter — verify long-context fit with `sndr quickstart`.
  [→ FAQ](FAQ.md#q-can-i-use-an-rtx-4090-instead-of-a-3090)
- **RTX 5090 (Blackwell 12.0)** — 32 GiB (more headroom), native FP8; a few
  Triton autotune configs are Ampere-optimal, so treat reference TPS as a
  floor. [→ FAQ](FAQ.md#q-can-i-use-an-rtx-5090)
- **H100/H200, A100** — supported; data-center envelopes, not the tuning target.

**Driver requirement:** NVIDIA driver **≥ 580.126.09 is REQUIRED** on the current CUDA 13 stack — the 570 series causes a ~3× slowdown (see [`CONFIGURATION.md`](CONFIGURATION.md) header).

## Will it fit? — builtin HardwareDefs + offline projection

Genesis ships three builtin hardware definitions
(`sndr/model_configs/builtin/hardware/`):
`a5000-2x-24gbvram-16cpu-128gbram` (the reference rig),
`a5000-1x-24gbvram-16cpu-128gbram`, and `single-3090-24gbvram`.
Instead of doing VRAM math by hand, project any preset against a rig —
live or synthetic, no GPU required:

```bash
sndr kv-calc prod-qwen3.6-35b-balanced                    # live rig → PASS/TIGHT/FAIL
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --rig single-3090-24gbvram   # builtin rig, offline
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --card 24           # quick ad-hoc 24 GiB card
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --fake-gpus 'RTX 3090:24576:8.6'
sndr kv-calc --fit-all --cards 24,48,80                   # whole catalog fit table
sndr kv-calc prod-qwen3.6-27b-tq-k8v4 --solve-max-ctx     # largest ctx that still fits
sndr preflight prod-qwen3.6-35b-balanced                  # full hardware-envelope gate
```

`kv-calc` (alias `fit`) reports a per-card VRAM/KV byte projection
with a **PASS / TIGHT / FAIL** verdict; `--kv-breakdown` shows the
per-component bytes. `sndr preflight` runs the same envelope check the
launch wizard uses.

## GPU power/clock tuning — `sndr tune`

Presets can carry a Y8 `gpu_tuning` block (power limit, clocks).
`sndr tune` applies it via `nvidia-smi` — dry-run by default:

```bash
sndr tune plan prod-qwen3.6-35b-balanced      # print planned nvidia-smi commands
sndr tune apply prod-qwen3.6-35b-balanced --yes
sndr tune report prod-qwen3.6-35b-balanced    # live nvidia-smi state vs Y8 declared
sndr tune revert                              # best-effort restore to defaults
sndr tune sweep prod-qwen3.6-35b-balanced --bench-cmd '...'   # power-limit sweep
```

## Single-GPU vs Multi-GPU

Genesis is validated in two reference shapes:

| Config | TP | Min VRAM/card | Use case |
|---|---|---|---|
| Single 24 GiB card | TP=1 | 24 GiB | Qwen3.6-27B-int4 with TQ k8v4 up to 78K context (preset `qa-qwen3.6-27b-tq-1x`; see [`SINGLE_CARD.md`](SINGLE_CARD.md)) |
| Dual 24 GiB cards | TP=2 | 24 GiB ×2 | Qwen3.6-27B-int4 long context, or Qwen3.6-35B-A3B — both served at 280K in PROD |
| Single 48 GiB+ card | TP=1 | 48 GiB+ | Either model, full context |
| Dual 48 GiB+ cards | TP=2 | 48 GiB+ ×2 | Production workloads with high concurrency |

### When you need TP=2

- **Qwen3.6-35B-A3B — always** on 24 GiB cards. The model alone is ~33 GiB FP8; KV cache and activations don't fit on one 24 GiB GPU.
- **Qwen3.6-27B-int4 with long context (>78K) — yes** on 24 GiB cards. Single-card 27B serves 78K with TQ k8v4; beyond that the KV cache eats VRAM fast.
- **Spec-decode draft VRAM**: the MTP draft layer costs ~1 GiB/rank on FP8 (PN8 online-quant saves it back). A separate DFlash drafter adds ~2-3 GiB per GPU — note the DFlash presets are currently **archived** pending re-validation on the 0.23.x pins.

## VRAM Budget by Model

Headline numbers measured at idle plus a small representative request.

### Qwen3.6-27B-int4-AutoRound (Lorbus)

| TP | Context | Per-GPU VRAM | Notes |
|---|---|---|---|
| 1 | 16K | ~16 GiB | Comfortable on a single 24 GiB card |
| 1 | 78K | ~22 GiB | Single-card TQ k8v4 cap (preset `qa-qwen3.6-27b-tq-1x`) |
| 2 | 32K | ~12 GiB each | Plenty of headroom |
| 2 | 256K | ~22 GiB each | Validated (2026-05 ladder, TP=2) |
| 2 | 280K | ~23 GiB each | **Current PROD serving cap** — 320K validated historically, trimmed to 280K 2026-05-15 to restore cudagraph-capture headroom |

This is a hybrid (GDN + softmax) model. Prefix-caching has been observed to crash with MTP `accept>1`. Recommended: leave prefix-caching disabled.

### Qwen3.6-35B-A3B-FP8 (MoE)

| TP | Context | Per-GPU VRAM | Notes |
|---|---|---|---|
| 1 | n/a | DOES NOT FIT | Need ≥48 GiB to run at TP=1 |
| 2 | 32K | ~17 GiB each | Comfortable |
| 2 | 96K | ~21 GiB each | Tight on 24 GiB |
| 2 | 280K | ~23 GiB each | **Current PROD serving cap** with TQ k8v4 KV (`prod-qwen3.6-35b-balanced`, `--max-model-len 280000`) |

MoE memory dominates over KV cache. Adding TurboQuant `k8v4` saves 5-10% per-token KV but does not help model weights.

### Spec-decode draft adder

MTP (the PROD method) reuses the target model's MTP layer — the cost
is ~1 GiB/rank on FP8 draft, reclaimed by PN8 online-quant. A separate
DFlash drafter adds approximately +2-3 GiB per GPU — subtract from the
headroom in the tables above when planning context length. (The four
DFlash presets are archived as of v12 pending re-validation.)

## Maximum Context Window vs VRAM

Prefer the tooling: `sndr kv-calc <preset> --solve-max-ctx` computes
the largest context that still PASS/TIGHT-fits (offline, exact
per-component byte model). The rough hand formula, for intuition:

```
free_kv_GiB ≈ (per_GPU_VRAM × gpu_memory_utilization) - model_weights_per_GPU - activation_overhead
context_tokens ≈ free_kv_GiB × 1024^3 / (kv_bytes_per_token × num_layers)
```

For Qwen3.6-27B-int4 with TQ k8v4 on 2× A5000:
- model weights/GPU ≈ 8 GiB
- activation overhead ≈ 2 GiB
- gpu_memory_utilization 0.85 → 20.4 GiB
- free for KV ≈ 10 GiB/GPU = 20 GiB total
- TQ k8v4 KV ≈ 0.06 KiB/token/layer
- ≈ 320K tokens raw budget — PROD serves 280K (the delta is
  deliberately reserved for cudagraph-capture headroom, 2026-05-15 trim)

Practical rules:
- 24 GiB cards: assume max 280K served context with TQ k8v4 (both 27B-int4 and 35B-A3B at TP=2)
- 48 GiB cards: comfortable to 1M context for 27B (untested in Genesis)
- 96 GiB cards: not VRAM-bound for any current Qwen3.6 size

## Which Card Should I Buy?

| Card | VRAM | Verdict |
|---|---|---|
| RTX 3090 | 24 GiB | Excellent value. Genesis-validated by community forks (noonghunna's club-3090). Get 2× for TP=2. |
| RTX 4090 | 24 GiB | Faster than 3090 (Ada vs Ampere). NO NVLink — TP=2 over PCIe is fine for Qwen3.6 but worse for very-large models. |
| RTX A5000 | 24 GiB | Genesis reference rig. Workstation card, lower power, blower cooler. |
| RTX A6000 | 48 GiB | Best price/VRAM in workstation tier. Single card runs both models. |
| RTX 5090 | 32 GiB | Blackwell — fastest consumer card. FP8 native. Limited supply. |
| R6000 Pro Blackwell | 96 GiB | Top tier. Genesis upgrade plan target. |
| Anything pre-Ampere | any | Don't. Genesis skips most kernels. |

### Is NVLink important?

For Qwen3.6 at TP=2: **no, not critical**. PCIe Gen4 x16 between two GPUs is sufficient — measured all-reduce overhead is ~3-5% of step time. NVLink helps more on very large models (70B+ dense) where layer activations are bigger. If your motherboard offers NVLink (some Threadripper / EPYC boards), enable it; otherwise don't pay extra.

## CPU and System RAM

| Component | Recommendation |
|---|---|
| CPU | Any modern 8-core. vLLM is GPU-bound; CPU only serializes requests and runs the tokenizer. AMD Ryzen 5600 / Intel i5-12400 is enough. |
| System RAM | 32 GiB minimum, 64 GiB comfortable. Used for HuggingFace download cache, Triton compile artifacts, and PyTorch's persistent allocator. |
| RAM speed | Not sensitive. DDR4-3200 fine. |

## Disk Space

| Item | Size |
|---|---|
| Qwen3.6-27B-int4-AutoRound | ~16 GiB |
| Qwen3.6-35B-A3B-FP8 | ~37 GiB |
| DFlash draft model | ~6 GiB |
| Triton kernel cache (`~/.triton`) | grows to ~5-10 GiB |
| torch.compile cache (`~/.cache/vllm`) | grows to ~10 GiB |
| HuggingFace hub cache | varies, plan ~80 GiB headroom |

NVMe is recommended — first-load shaves minutes off boot. After warm-up, disk is irrelevant during inference.

## Power Supply

| GPU | TGP | Recommended PSU headroom |
|---|---|---|
| RTX 3090 | 350 W | 850 W single, 1300 W dual |
| RTX 4090 | 450 W | 1000 W single, 1500 W dual |
| RTX A5000 | 230 W | 750 W single, 1000 W dual |
| RTX A6000 | 300 W | 850 W single, 1200 W dual |
| RTX 5090 | 575 W | 1200 W single, 1800 W dual |
| R6000 Pro | 600 W | 1200 W single, 1800 W+ dual |

Add ~150 W for the rest of the system (CPU, RAM, disks, fans).

## Cooling

vLLM under sustained inference pulls full TGP for hours. Workstation cards (A5000, A6000) ship with blower coolers and tolerate stacked configurations. Consumer cards (3090, 4090, 5090) are open-fan and need ~2 slots of airflow per card. Two 4090s stacked without spacing will thermal-throttle within minutes — use riser cables or PCIe extension to space them.

The Genesis reference rig sits at 72-78 °C under sustained load on both A5000s with case-fan airflow alone.
