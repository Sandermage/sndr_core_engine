---
name: Community model config submission
about: Submit a YAML config that boots and benches well on YOUR rig
title: '[community-config] <gpu>-<model>-<note>'
labels: community-config, needs-review
---

## Hardware

- GPU model + count + VRAM:
- NVLink / PCIe topology:
- Driver / CUDA version:
- Tested: bare-metal / Docker / both?

## Model

- Model HF path:
- Model size + quantization (e.g. 27B INT4-AutoRound):
- Tokenizer:

## Config YAML

<!-- paste the FULL YAML from your `~/.genesis/model_configs/` -->

```yaml
key: <gpu>-<model>-<note>
title: ...
maintainer: <github-handle>
lifecycle: community-test  # MUST start as community-test (auto-promotes after verify)
schema_version: 1
genesis_pin: <commit>
vllm_pin_required: <pin>
hardware:
  gpu_match_keys: ['...']
  n_gpus: ...
  min_vram_per_gpu_mib: ...

# ... full config below
```

## Bench results — `genesis model-config verify <key>`

<!-- paste the bench output of `genesis model-config verify` against your rig -->

```
short_TPS=...
long_TPS=...
tool=N/N
stability_CV=...%
VRAM=...
```

## Validation

- [ ] Boot succeeds 3 consecutive times (no flake)
- [ ] Tool-call quality: 10/10 over `genesis bench tool-call --runs 30`
- [ ] No regression on adjacent builtin config (if applicable)
- [ ] Reference metrics captured via `genesis model-config bench-and-update`

## Known limitations

<!-- Any caveats? E.g. "fails with --enable-prefix-caching", "OOM at 256K but 192K fine". -->

## Lifecycle promotion path

This config will be merged at lifecycle `community-test`. After 7 days of
community feedback (no regression reports) AND if I run
`genesis model-config verify` successfully on a separate rig, it can be
promoted to `community-stable` via PR.
