# Run on Linux — the full stack, locally

This is the front door for the machine that actually runs the engine: a
**Linux box with an NVIDIA CUDA GPU and Docker**. On this hardware you get the
whole platform — the patched vLLM engine, the GUI Control Center, and the
persistent memory — running locally. Mac and Windows users drive a box like
this remotely; see [`RUN_ON_MAC.md`](RUN_ON_MAC.md) /
[`RUN_ON_WINDOWS_WSL.md`](RUN_ON_WINDOWS_WSL.md).

> **What "the engine" needs.** The engine is **Linux + CUDA + Docker** only.
> The reference rig is **2× RTX A5000 / 3090, 24 GB each, Ampere `sm_86`**,
> TP=2 for the big models. A single 24 GB card runs the 27B lane; the 35B MoE
> wants two. Current pin **`dev748`** (`0.23.1rc1.dev748+g2dfaae752`), 329
> patches auto-applied at boot.

## Read this first (the one warning that matters)

**One heavy model at a time.** Both GPUs are occupied by a big model at TP=2;
you cannot run two 24 GB-class models concurrently on a 2-card rig. Boot one,
stop it with `sndr down`, then boot the next.

**Never interrupt a production engine.** If a rig is already serving (the
reference PROD lane is `:8102`), do **not** `docker stop` it or launch a second
heavy model on the same cards — you will evict the running model. Check
`docker ps` before you launch.

**Stop with `sndr down`, not `docker stop`.** A plain `docker stop` +
`docker start` recycles the same writable layer, and the Genesis text-patches
applied to that layer fail to re-apply on the next boot (anchors no longer
match). Always use `sndr down`. Recovery for a stuck container is a full
`docker compose down` → `docker compose up -d`. Details:
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## The zero-decision path

If you don't want to think about presets at all:

```bash
# 1. install — detects OS / Python / GPU / vLLM, installs the plugin + `sndr`
curl -sSL https://raw.githubusercontent.com/Sandermage/sndr_core_engine/main/install.sh | bash

# 2. one command: auto-detect the GPU → fit a preset → download weights → boot → open the GUI
sndr quickstart          # equivalently: `sndr up` (auto-picks a preset for your rig)
```

`sndr quickstart` auto-detects your card, picks a fitting preset, pulls the
weights (skipped if present), launches the engine **and** the Control Center,
and opens your browser at `http://127.0.0.1:8765`. Prefer a terminal chat
instead of the GUI? `sndr run` does the same and drops you at a prompt. That is
the whole zero-decision arc — no config files.

Want to lock in a specific model as your default so `sndr up` always boots it?
After the first boot the CLI offers to pin your choice; you can also always be
explicit with `sndr up <preset>` (expert path, below).

## Pick a workload

Every preset below runs through the launcher — `sndr up <preset>` boots it,
`sndr launch <preset> --dry-run` shows the rendered `docker run` without
booting. Numbers are single-stream decode on the reference **2× A5000** rig,
labeled with (pin, date); full methodology and per-rig reproduction in
[`BENCHMARKS.md`](BENCHMARKS.md).

| Workload | Preset | Max ctx | Single-stream TPS | Topology |
| --- | --- | ---: | ---: | --- |
| **IDE agents / low-latency chat** | `prod-qwen3.6-35b-balanced` | 280K | ~223.9 t/s (dev748, 2026-07-04; AWQ PROD lane 242.5) | 2× A5000 TP=2 |
| **High-concurrency serving** | `prod-qwen3.6-35b-multiconc` | 280K | ~672 t/s aggregate @ conc=8 (K=3, 2026-05-23) | 2× A5000 TP=2 |
| **RAG / long-context (27B)** | `prod-qwen3.6-27b-tq-k8v4` | 262K | ~130 t/s (2026-07-04 sweep) | 2× A5000 TP=2 |
| **Single-card 27B** | `qa-qwen3.6-27b-tq-1x` | 78K | ~108–125 t/s | 1× A5000 / 3090 TP=1 |
| **Multimodal / structured (Gemma 4)** | `prod-gemma4-26b-default` | 262K | ~141 t/s (dev748, 2026-07-04) | 2× A5000 TP=2 |
| **Block-diffusion text (experimental)** | `prod-diffusiongemma-tp2` | 128K | n/a (diffusion; AR TPS not applicable) | 2× A5000 TP=2 |

### Workload: IDE agents / low-latency chat

The flagship for a **single user**. Boot the balanced 35B:

```bash
sndr up prod-qwen3.6-35b-balanced
```

`prod-qwen3.6-35b-balanced` is the right default for one person at a keyboard —
it is latency-tuned (`max_num_seqs=2`), serves the full 280K context, and keeps
tool-calling clean (7/7 on the dev748 promotion gate). Use
`prod-qwen3.6-35b-multiconc` **only** when you are serving many concurrent
requests: it is throughput-tuned (`max_num_seqs=8`, ~672 t/s aggregate) and
trades single-stream latency for that aggregate. For one user, balanced wins.

### Workload: RAG / long-context

Big-document retrieval and long chats on the 27B INT4 lane at 262K context:

```bash
sndr up prod-qwen3.6-27b-tq-k8v4
```

TurboQuant `k8v4` KV-cache quant is what makes the long context fit. On a
single 24 GB card use `qa-qwen3.6-27b-tq-1x` (78K context, TP=1) — see
[`SINGLE_CARD.md`](SINGLE_CARD.md) for the single-card cliff story and escape
hatches. (The 27B model loops in thinking mode — a known model trait; chat with
`enable_thinking:false`.)

### Workload: multimodal / structured (Gemma 4)

```bash
sndr up prod-gemma4-26b-default
```

Gemma 4 26B-A4B for structured / multimodal-adjacent work at 262K context. The
31B variant (`prod-gemma4-31b-kvauto-chat`) also boots and serves chat +
tool-calls on this rig.

## Expert path (kept, always works)

The zero-decision surface is additive — none of the explicit controls went
away:

```bash
sndr preset list                                   # browse presets for your rig
sndr launch prod-qwen3.6-35b-balanced --dry-run    # render the docker command + patch plan, boot nothing
sndr up prod-qwen3.6-35b-balanced                  # boot an explicit preset
sndr config diff prod-qwen3.6-35b-balanced prod-qwen3.6-27b-tq-k8v4
sndr down                                          # safe stop
```

Full operator manual: [`USAGE.md`](USAGE.md). Every `sndr` command:
[`CLI_REFERENCE.md`](CLI_REFERENCE.md). Env-flag tuning:
[`CONFIGURATION.md`](CONFIGURATION.md).

## Where to go next

| If you want to… | Read |
| --- | --- |
| The 5-minute clone-to-chat path | [`QUICKSTART.md`](QUICKSTART.md) |
| Full installer flag matrix | [`INSTALL.md`](INSTALL.md) |
| Set up `~/.sndr/host.yaml` (weights paths + mounts) | [`HOST_SETUP.md`](HOST_SETUP.md) |
| Single 3090 / 4090 / A5000 | [`SINGLE_CARD.md`](SINGLE_CARD.md) |
| Pick a model + hardware combo | [`MODELS.md`](MODELS.md) + [`HARDWARE.md`](HARDWARE.md) |
| Day-2 operations (swaps, rollbacks, hygiene) | [`OPERATIONS.md`](OPERATIONS.md) |
| Drive this rig from a Mac / Windows laptop | [`RUN_ON_MAC.md`](RUN_ON_MAC.md) · [`REMOTE_ENGINE.md`](REMOTE_ENGINE.md) |
| Diagnose an OOM, cliff, or boot failure | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
