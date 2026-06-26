---
name: Bug report
about: Report something that's broken in Genesis vLLM patches
title: '[bug] '
labels: bug
---

## What broke

<!-- One sentence: what should happen, what actually happens. -->

## Hardware

<!-- output of `nvidia-smi --query-gpu=name,driver_version,vbios_version,memory.total --format=csv` -->

```
<paste here>
```

## Software stack

- Genesis pin / commit:
- vLLM pin (per `python -c "import vllm; print(vllm.__version__)"`):
- Python version:
- OS / kernel:
- Container OR bare-metal:

## `genesis doctor --json` output

<!-- attach the JSON output as a file or paste below -->

```json
<paste here>
```

## Reproduce

```bash
# minimal command sequence that triggers the bug
```

## Expected behavior

<!-- what you thought would happen -->

## Actual output / error

```
<paste docker logs / stdout / stderr last 50 lines>
```

## Genesis env vars at failure

<!-- output of `docker exec <container> env | grep ^GENESIS_ | sort` -->

```
<paste here>
```

## Have you tried

- [ ] `genesis doctor` (any failures reported?)
- [ ] `genesis verify --quick`
- [ ] Re-running with `GENESIS_DISABLE=1` to confirm it's our code (not vLLM upstream)
- [ ] Searching closed issues + [docs/TROUBLESHOOTING.md](../../docs/TROUBLESHOOTING.md) (covers former CLIFFS.md + OOM_RECIPES.md content per 2026-05-16 consolidation)

## Additional context

<!-- benchmark history, PR / issue links, anything relevant -->
