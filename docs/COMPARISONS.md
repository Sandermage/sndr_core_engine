# Comparisons

Two honest comparisons: **self-host vs cloud APIs** (when running SNDR Core on
your own hardware beats a hosted API, and when it doesn't) and
**[SNDR Core vs other local engines](#sndr-core-vs-other-local-engines)**.
No vendor or competitor numbers are quoted as fact — the costs below are a
**worked illustration**; plug in today's prices and your own measured
throughput.

## Self-host vs cloud APIs

### When self-host wins

- **Steady, high volume.** If you push tokens through a model many hours a day,
  amortized hardware beats per-token billing — often by a wide margin.
- **Privacy / compliance.** Data that legally or contractually cannot leave
  your premises.
- **Latency and reliability.** No network hop, no rate limits, no upstream
  model deprecation breaking your pipeline overnight.
- **Tinkering and research.** Full control of the model, quant, KV cache, and
  patches — the whole point of this project.

### When cloud wins

- **Spiky or low volume.** A few thousand tokens a day will never amortize a
  GPU; a hosted API is cheaper and simpler.
- **No hardware / no ops appetite.** You don't want to own a GPU, manage
  drivers, or keep a box running.
- **Frontier-model needs.** When only the largest closed models will do, you
  can't self-host them on a 24 GB card.

### Cost crossover — a worked illustration (figures as of 2026-07)

The crossover is the monthly token volume at which a paid-off rig becomes
cheaper than per-token billing.

Take the reference rig and a representative cloud price. **These are
placeholders — substitute current figures:**

- **Rig:** 2× RTX A5000, assume an all-in amortized cost of **$C/month**
  (hardware depreciation + power). Pick your own `C`.
- **Cloud:** a comparable hosted model at **$P per million output tokens**.
  Pick your own `P`.
- **Your throughput on the rig:** SNDR Core sustains **~242 tok/s**
  single-stream for Qwen3.6-35B (pin `dev748`, measured 2026-07-04; 234.2 on
  the same-day `dev714` canonical run) and **~672 tok/s** aggregate at 8-way
  concurrency (K=3 multi-conc bench, 2026-05-23) — see
  [`BENCHMARKS.md`](BENCHMARKS.md).

The rig pays for itself once your **monthly output tokens** exceed roughly
`C / P` million. For example, at `C = $120/month` and `P = $0.60 /Mtok`, the
crossover is about **200 M output tokens/month** — a volume a single busy agent
or a small team reaches quickly, but a casual user never will.

The point is not the exact number — it's the **shape**: self-host has a fixed
monthly cost and near-zero marginal cost; cloud has zero fixed cost and a fixed
marginal cost. They cross at one volume. Find yours.

### What SNDR Core changes

SNDR Core moves the crossover **in self-host's favour** by raising the rig's
throughput: **+44–53 %** single-stream over stock vLLM, and ~3.2× aggregate
scaling under concurrency (see the headline table in the
[`README`](../README.md)). More tokens per hour from the same hardware means the
fixed monthly cost is spread over more output — the rig pays for itself at a
lower volume than it would on stock vLLM.

## SNDR Core vs other local engines

The same honesty rules apply here: **we only quote numbers we measured
ourselves, on a named rig, labeled with pin and date.** We have not benchmarked
Ollama, llama.cpp, or TGI on the reference rig, so their throughput cells are
deliberately empty — a competitor number we didn't measure would be marketing,
not a comparison. The repo ships a llama.cpp preset
(`llamacpp-qwen3.6-27b-q4km-1x`) precisely so you can produce your own measured
row on your own hardware.

| Dimension | SNDR Core (vLLM + Genesis patches) | Stock vLLM | Ollama | llama.cpp | TGI |
| --- | --- | --- | --- | --- | --- |
| Decode TPS, Qwen3.6-35B-A3B on 2× RTX A5000 | **242.55 tok/s** single-stream (pin `dev748`, 2026-07-04, n=25, CV 6.9 %; same-day `dev714` reference 234.2); **~672 tok/s** aggregate @ 8-way (2026-05-23) | ~157 tok/s (our own baseline sweep, dev148 era) | not measured by us | not measured by us (preset shipped — measure yours) | not measured by us |
| Max served context on 24 GB-class cards | **280K** (TurboQuant k8v4 KV cache, 2× A5000) | limited by FP16/FP8 KV cache growth on 24 GB | model/backend dependent | GGUF KV quant available, model dependent | model dependent |
| Tool-call reliability | **7/7** promotion gate (streaming `qwen3_xml` parser; dev748, 2026-07-04) + **8/8** canonical suite (same-day dev714) | parser available; untuned on these quantized checkpoints | not measured by us | not measured by us | not measured by us |
| OpenAI-compatible API | yes (unchanged vLLM server) | yes | yes (compat endpoint) | yes (`llama-server`) | partial (Messages API) |
| MoE + speculative decoding + KV-cache quant, together, tuned for 24 GB | shipped default (MTP K=5 + TurboQuant k8v4) | components exist; not tuned as a bundle for consumer cards | limited | draft-model spec decode exists; combination is DIY | spec decode support varies |

What the patch layer buys over stock vLLM on the *same* hardware is the
measured story above: +44–53 % single-stream, working streaming tool calls,
and 280K served context — details and reproduction commands in
[`BENCHMARKS.md`](BENCHMARKS.md). The qualitative cells for other engines
describe publicly documented features, not measurements; treat them as a map
of what to verify, not a verdict.

## Next

- Measure your own throughput → [`BENCHMARKS.md`](BENCHMARKS.md)
- New to the concepts → [`LOCAL_AI_PRIMER.md`](LOCAL_AI_PRIMER.md)
- Ready to run → [`GETTING_STARTED.md`](GETTING_STARTED.md)
