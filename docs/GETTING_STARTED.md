# Getting started

New here? This page orients you in two minutes, then points you at the right
next step. It does **not** repeat the commands — the [`QUICKSTART.md`](QUICKSTART.md)
has the copy-paste path; this page tells you whether SNDR Core is for you and
where to go.

## Is this for you?

SNDR Core Engine (Genesis) is for you if:

- You have **one or two consumer NVIDIA GPUs** — RTX 3090, 4090, 5090, A5000,
  A6000 — and want to run a **modern, production-grade LLM at home** or in a
  homelab / dev backend.
- You want an **OpenAI-compatible API** on `localhost` (drop-in for any client
  or agent that speaks the OpenAI protocol), with **tool-calling** and
  **long context** that actually work.
- You are comfortable on **Linux + Docker** (or WSL2 on Windows).

It is probably **not** for you (yet) if you have no NVIDIA GPU, only want a
one-click desktop chat app, or need a frontier hosted model — in those cases a
cloud API is the simpler call. See [`COMPARISONS.md`](COMPARISONS.md) for the
honest self-host-vs-cloud trade.

## What you get

A patched vLLM that turns a consumer Ampere/Ada/Blackwell rig into a fast
Qwen3.6 / Gemma4 inference server. On the reference 2× RTX A5000 rig:

| What | Number |
| --- | --- |
| Qwen3.6-35B-A3B (MoE), single-stream decode | **~242 tok/s** (pin `dev748`, 2026-07-04, AWQ checkpoint; ≈1.5× stock vLLM — +53 % measured against a stock baseline on `dev148`, 2026-06-19) |
| Qwen3.6-27B-int4, single-stream decode | **~127.4 tok/s** (+46 %; pin `dev148`, 2026-06-19) |
| Context, served in production (35B) | **280K** |
| Tool-call clean rate | **7/7** (35B, pin `dev748`, 2026-07-04) · **7/7** (27B, `dev148`) |

Full methodology and per-rig reproduction: [`BENCHMARKS.md`](BENCHMARKS.md).
What it is and how the overlay works: the project [`README`](../README.md).

## The fastest path

One paste installs everything and registers the `sndr` command:

```bash
curl -sSL https://raw.githubusercontent.com/Sandermage/sndr_core_engine/main/install.sh | bash
```

Then **three commands** take you from install to a chat prompt — they are laid
out, with expected output, in [`QUICKSTART.md`](QUICKSTART.md). Prefer a manual
clone instead of the installer? That path is in [`INSTALL.md`](INSTALL.md).

## Where to go next

| If you want to... | Read |
| --- | --- |
| Clone → first token, with the actual commands | [`QUICKSTART.md`](QUICKSTART.md) |
| Use the browser GUI (`sndr up` / `sndr open`, port 8765) | [`GUI.md`](GUI.md) |
| Drive everything from one keyboard screen (no commands to memorise) | [`TUI.md`](TUI.md) |
| Understand local AI from scratch (hardware / engines / quants) | [`LOCAL_AI_PRIMER.md`](LOCAL_AI_PRIMER.md) |
| Decode a term — TPS, KV, MTP, TurboQuant, GDN | [`GLOSSARY.md`](GLOSSARY.md) |
| Pick a model + hardware combo | [`MODELS.md`](MODELS.md) + [`HARDWARE.md`](HARDWARE.md) |
| Run on a single 3090 / 4090 | [`SINGLE_CARD.md`](SINGLE_CARD.md) |
| Weigh self-host vs a cloud API | [`COMPARISONS.md`](COMPARISONS.md) |
| Diagnose an out-of-memory, cliff, or boot failure | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| Quick answers — pins, patches, hardware, licensing | [`FAQ.md`](FAQ.md) |
| See every `sndr` command | [`CLI_REFERENCE.md`](CLI_REFERENCE.md) |

Stuck or have numbers from your own rig to share? Open a
[discussion or issue](https://github.com/Sandermage/sndr_core_engine/issues) —
cross-rig reports are genuinely welcome.
