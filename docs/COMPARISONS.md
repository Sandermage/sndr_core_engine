# Self-host vs cloud APIs

An honest look at when running SNDR Core on your own hardware beats a hosted
API, and when it doesn't. No vendor numbers are quoted as fact — the costs
below are a **worked illustration**; plug in today's prices and your own
measured throughput.

## When self-host wins

- **Steady, high volume.** If you push tokens through a model many hours a day,
  amortized hardware beats per-token billing — often by a wide margin.
- **Privacy / compliance.** Data that legally or contractually cannot leave
  your premises.
- **Latency and reliability.** No network hop, no rate limits, no upstream
  model deprecation breaking your pipeline overnight.
- **Tinkering and research.** Full control of the model, quant, KV cache, and
  patches — the whole point of this project.

## When cloud wins

- **Spiky or low volume.** A few thousand tokens a day will never amortize a
  GPU; a hosted API is cheaper and simpler.
- **No hardware / no ops appetite.** You don't want to own a GPU, manage
  drivers, or keep a box running.
- **Frontier-model needs.** When only the largest closed models will do, you
  can't self-host them on a 24 GB card.

## Cost crossover — a worked illustration

The crossover is the monthly token volume at which a paid-off rig becomes
cheaper than per-token billing.

Take the reference rig and a representative cloud price. **These are
placeholders — substitute current figures:**

- **Rig:** 2× RTX A5000, assume an all-in amortized cost of **$C/month**
  (hardware depreciation + power). Pick your own `C`.
- **Cloud:** a comparable hosted model at **$P per million output tokens**.
  Pick your own `P`.
- **Your throughput on the rig:** SNDR Core sustains **~239.7 tok/s**
  single-stream for Qwen3.6-35B (and **~675 tok/s** aggregate at 8-way
  concurrency) — see [`BENCHMARKS.md`](BENCHMARKS.md).

The rig pays for itself once your **monthly output tokens** exceed roughly
`C / P` million. For example, at `C = $120/month` and `P = $0.60 /Mtok`, the
crossover is about **200 M output tokens/month** — a volume a single busy agent
or a small team reaches quickly, but a casual user never will.

The point is not the exact number — it's the **shape**: self-host has a fixed
monthly cost and near-zero marginal cost; cloud has zero fixed cost and a fixed
marginal cost. They cross at one volume. Find yours.

## What SNDR Core changes

SNDR Core moves the crossover **in self-host's favour** by raising the rig's
throughput: **+46–53 %** single-stream over stock vLLM, and ~3.2× aggregate
scaling under concurrency (see the headline table in the
[`README`](../README.md)). More tokens per hour from the same hardware means the
fixed monthly cost is spread over more output — the rig pays for itself at a
lower volume than it would on stock vLLM.

## Next

- Measure your own throughput → [`BENCHMARKS.md`](BENCHMARKS.md)
- New to the concepts → [`LOCAL_AI_PRIMER.md`](LOCAL_AI_PRIMER.md)
- Ready to run → [`GETTING_STARTED.md`](GETTING_STARTED.md)
