# Local AI primer

Plain English, no prior background assumed. If you have heard "run an LLM
locally" and want to know what that actually involves — and where SNDR Core
fits — start here. For exact term definitions, keep [`GLOSSARY.md`](GLOSSARY.md)
open in a second tab.

## Why run a model locally at all

Four reasons people self-host instead of calling a cloud API:

- **Privacy.** Prompts and documents never leave your machine. Nothing is
  logged by a third party.
- **Cost at volume.** Once the hardware is paid for, tokens are effectively
  free. Heavy, steady usage can be far cheaper than per-token cloud billing —
  see [`COMPARISONS.md`](COMPARISONS.md) for where the crossover lands.
- **Latency and control.** No network round-trip, no rate limits, no surprise
  model deprecations. You decide exactly which model and settings run.
- **Tinkering.** You can inspect, quantize, patch, and benchmark the whole
  stack — which is what this project is about.

## The four things that fit together

Running a model locally is really four pieces clicking into place. Get the
combination right and it just works; get it wrong and you hit an out-of-memory
error or crawling speed.

### 1. The GPU and its VRAM

The model's weights have to live in **VRAM** (the memory on your graphics
card). A consumer card like an RTX 3090, 4090, or A5000 has **24 GB**; a 5090
has 32 GB. VRAM is the single hardest limit: it caps how big a model you can
load and how much **context** (conversation history) you can keep. Most of this
project targets the 24 GB class, single or dual card.

### 2. The inference engine

The engine is the program that loads the weights and actually generates text.
This project builds on **[vLLM](https://github.com/vllm-project/vllm)** — a
high-throughput engine that serves an **OpenAI-compatible API**, so any tool
that talks to OpenAI talks to your local server unchanged. vLLM mostly targets
big datacenter GPUs; SNDR Core is the patch layer that makes it run *well* on
consumer cards.

### 3. Model size and "active parameters" (MoE)

Model size is measured in **parameters** (e.g. "27B" = 27 billion). Bigger is
usually smarter but needs more VRAM. Many modern models are **MoE**
(Mixture-of-Experts): they have many parameters total but only activate a small
**fraction per token**. Qwen3.6-35B-A3B, for example, has 35 B total but only
~3 B *active* per token — so it runs at the speed of a small model with the
quality of a larger one. That is why MoE models are a sweet spot for consumer
rigs.

### 4. Quantization

Full-precision weights (16 bits each) rarely fit on a consumer card.
**Quantization** shrinks them to fewer bits — **FP8** (8-bit float), **INT4**
(4-bit integer, e.g. AutoRound or AWQ) — trading a little quality for a large
VRAM saving. The **KV cache** (the running memory of the current conversation)
can be quantized too; this project's **TurboQuant k8v4** does exactly that,
which is how it serves **280K** context on 24 GB cards (above the model's
published 256K limit). Quant names are
decoded in [`GLOSSARY.md`](GLOSSARY.md); the per-model quant choices live in
[`MODELS.md`](MODELS.md).

## What is tool-calling, and why quantization breaks it

**Tool-calling** (also "function calling") is how a model does more than chat:
instead of answering in prose, it emits a structured request — "call
`get_weather` with `city=Odessa`" — that your application executes, feeding the
result back. Every agent framework, coding assistant, and automation pipeline
is built on it. For it to work, the model must produce **exactly** the expected
format: valid JSON or XML, correct argument names, no stray text.

That exactness is what quantization endangers. Squeezing weights to fewer bits
nudges the model's output distribution — usually harmless in prose, but a
single malformed bracket in a tool call breaks the parse and the whole agent
step fails silently. This is why "tool calls break the moment you quantize" is
such a common complaint with local models. SNDR Core treats tool-call
correctness as a gate: every production configuration must pass a tool-call
suite (currently 8/8 scenarios, including streaming and multi-tool calls)
before it ships, using vLLM's native `qwen3_xml` streaming parser.

## How SNDR Core fits

Stock vLLM, on a consumer card, often won't load these models at all — or runs
them slowly, without working tool-calls or long context. **SNDR Core Engine
(Genesis)** is a set of small runtime patches applied to vLLM at boot that:

- enable the **quantization + KV-cache** paths that fit 24 GB,
- add **speculative decoding** (MTP) for a large speed-up,
- fix **tool-calling** and **long-context** correctness,
- and retire themselves automatically once upstream vLLM merges the fix.

Nothing is forked or rewritten — it is the same vLLM, transformed in memory at
start-up. The full catalogue is in [`PATCHES.md`](PATCHES.md); the what/why is
in the project [`README`](../README.md).

## Next

- Ready to run it? → [`GETTING_STARTED.md`](GETTING_STARTED.md) →
  [`QUICKSTART.md`](QUICKSTART.md)
- Common questions answered → [`FAQ.md`](FAQ.md)
- Self-host vs cloud? → [`COMPARISONS.md`](COMPARISONS.md)
- Which model on which card? → [`MODELS.md`](MODELS.md) +
  [`HARDWARE.md`](HARDWARE.md)
