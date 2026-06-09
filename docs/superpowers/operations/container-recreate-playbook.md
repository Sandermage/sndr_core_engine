# Container recreate playbook — Genesis PROD vLLM

Status: drafted 2026-06-09. Not yet executed against PROD.

## When to use this playbook

Use this playbook **only** when:

  * A YAML env change (e.g. `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR`) was added
    that must be present at PID 1 from container-creation time AND
    visible to `docker exec` sidecars — `docker restart` is NOT enough,
    because the docker env layer is set at container creation, not start.
  * A new bind mount needs to land at container-creation time.
  * Operator explicitly approved the recreate after seeing the dry-run
    diff.

Do NOT use this playbook for routine launcher edits (`run.sh` exports
take effect on plain `docker restart`).

## Why a recreate is different from a restart

| Action | What it does | Env layer | Binds layer |
|--------|--------------|-----------|-------------|
| `docker restart` | re-runs PID 1 | unchanged (creation-time) | unchanged |
| `docker stop && docker start` | same as restart | unchanged | unchanged |
| **`docker stop && docker rm && docker run`** | new container | new (from `-e` flags) | new (from `-v` flags) |

The launcher script (`run.sh`) can `export` new env vars but those
exports only apply to processes spawned after that `export` runs.
Docker exec sidecars and any subprocess that resets its env (e.g. the
NCCL bootstrap fork) inherit the docker-layer env, not the runtime
shell env.

## Current state diagnostic (run BEFORE you decide to recreate)

```bash
# 1. Confirm the running container
ssh sander@192.168.1.10 'docker ps --filter name=vllm-qwen3.6-35b-balanced-k3'

# 2. Count env vars and look for the autotune dirs at docker layer
ssh sander@192.168.1.10 \
  'docker inspect vllm-qwen3.6-35b-balanced-k3 --format "{{json .Config.Env}}"' \
  | python3 -c "import json,sys; e=json.load(sys.stdin); print(f'{len(e)} env vars'); \
                print([x for x in e if 'AUTOTUNE' in x or 'TRITON_CACHE' in x])"

# 3. Check PID 1 actually sees the dirs (what the engine reads at startup)
ssh sander@192.168.1.10 \
  'docker exec vllm-qwen3.6-35b-balanced-k3 sh -c \
     "cat /proc/1/environ | tr \"\\0\" \"\\n\" | \
        grep -E \"FLASHINFER|TRITON_CACHE\""'

# 4. Confirm the host autotune dirs exist + are populated
ssh sander@192.168.1.10 \
  'ls -la /home/sander/genesis-vllm-patches/.autotune_cache/{flashinfer,triton}; \
   du -sh /home/sander/genesis-vllm-patches/.autotune_cache/*'

# 5. Capture the current patch summary as a baseline
ssh sander@192.168.1.10 \
  "docker logs vllm-qwen3.6-35b-balanced-k3 2>&1 | \
     grep 'register() complete: applied=' | tail -1"
```

**Decision criteria:**

  * If steps 2 + 3 already show the autotune dirs AND the cache is
    populated (step 4) — a recreate is **not** required for autotune
    persistence. The launcher script is already doing the right thing.
  * Recreate is still beneficial when you want to **promote** the
    launcher exports into the docker layer so they survive launcher
    edits / are visible to sidecars.

## Pre-recreate checklist

- [ ] Off-peak window confirmed (no live tool-call traffic).
- [ ] Recent bench baseline captured (current `wall_TPS`, `TTFT σ`,
      `decode_TPOT`) — store somewhere outside the container.
- [ ] `docker inspect` snapshot saved — `tools/safe_container_recreate.py`
      does this automatically into `/tmp/genesis_recreate/snapshot-<...>/`.
- [ ] Patch summary baseline captured (`applied=N skipped=M failed=K`).
- [ ] Disk space on `/home/sander/genesis-vllm-patches/.autotune_cache`
      has at least 5 GB headroom (autotune cache can grow).
- [ ] Image SHA noted: the recreate must pin to the SAME image SHA, not
      a new pull (operator's vLLM pin policy).
- [ ] Launcher script (`/tmp/qwen3.6-35b-balanced_launcher/run.sh`) on
      the server is the one you want PID 1 to execute.

## The recreate procedure (script-driven)

The `tools/safe_container_recreate.py` script automates each step. It
operates on the **current** container state at run time — no stale
snapshot file is assumed.

### Step 1 — dry-run (mandatory)

```bash
python3 tools/safe_container_recreate.py \
    --host sander@192.168.1.10 \
    --container vllm-qwen3.6-35b-balanced-k3 \
    --port 8102 \
    --api-key genesis-local \
    --dry-run
```

This:

  1. Snapshots the live container into
     `/tmp/genesis_recreate/snapshot-<name>-<ts>/`.
  2. Prints the env diff (added / removed / changed).
  3. Prints the full proposed `docker run` command.
  4. Writes it to `<snapshot>/new_docker_run.sh` for review.
  5. Exits without modifying anything.

**Operator review checklist on the dry-run output:**

  * `image: vllm/vllm-openai:nightly-<sha>` — confirm SHA matches the
    current PROD pin.
  * `env vars: 158` — must match the live count (sanity check).
  * `binds: 4` — must include the launcher dir, the project rw bind,
    the models ro bind, and the sndr ro bind.
  * `added: 7` — must be exactly the launcher-script promotions:
    `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR`, plus 6 GENESIS enables.
  * `changed: 2` — `TRITON_CACHE_DIR` repoints to the autotune dir,
    and `GENESIS_ENABLE_PN204_DUAL_STREAM_INPROJ` flips 1→0 per the
    current launcher.
  * `removed: 21` — must be ONLY docker-injected vars (NVIDIA_*, UV_*,
    PATH, CUDA_*, VLLM_BUILD_*, etc.). If you see a GENESIS_* or a
    VLLM_TQ_* in `removed`, STOP — that's a bug in the filter.
  * `--entrypoint /tmp/qwen3.6-35b-balanced_launcher/run.sh` — present.

### Step 2 — execute the recreate

```bash
python3 tools/safe_container_recreate.py \
    --host sander@192.168.1.10 \
    --container vllm-qwen3.6-35b-balanced-k3 \
    --port 8102 \
    --api-key genesis-local
```

You'll be prompted with `type 'recreate' to continue:`. Type
`recreate` only after the dry-run review passed.

The script then:

  1. `docker stop` the running container.
  2. `docker rename` it to `<container>-rollback-<utc-timestamp>`
     (NOT removed — kept on disk for one-line rollback).
  3. `docker run` the new container with the merged config.
  4. Polls `/health` for up to 10 minutes.
  5. Prints the smoke-test report (patch summary, models endpoint,
     PID 1 autotune env).

**Expected timeline:** 10–15 minutes total.

  * Stop + start: <30 s.
  * vLLM engine load + CUDA graph capture + sndr_core apply: 4–6 min.
  * Smoke tests: <30 s.

## Post-recreate verification checklist

Run each of these. Each must pass before declaring the recreate
successful.

- [ ] Container `Up X seconds`:
      `ssh sander@192.168.1.10 'docker ps --filter name=vllm-qwen3.6-35b-balanced-k3'`
- [ ] `/health` returns 200:
      `ssh sander@192.168.1.10 'curl -sw "%{http_code}" -o /dev/null http://localhost:8102/health'`
- [ ] `/v1/models` lists `qwen3.6-35b-a3b`:
      `ssh sander@192.168.1.10 'curl -s -H "Authorization: Bearer genesis-local" http://localhost:8102/v1/models | head -c 200'`
- [ ] Patch summary matches the pre-recreate baseline:
      `ssh sander@192.168.1.10 "docker logs vllm-qwen3.6-35b-balanced-k3 2>&1 | grep 'register() complete' | tail -1"`
      Expected for current PROD: `applied=104 skipped=128 failed=1`.
      Acceptable: ±1 in skipped (boot-order nondeterminism); failed must NOT increase.
- [ ] PID 1 sees the autotune dirs:
      `ssh sander@192.168.1.10 'docker exec vllm-qwen3.6-35b-balanced-k3 sh -c "cat /proc/1/environ | tr \"\\0\" \"\\n\" | grep -E \"FLASHINFER_AUTOTUNE|TRITON_CACHE\""'`
      Expected: both `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=...` and
      `TRITON_CACHE_DIR=/home/sander/genesis-vllm-patches/.autotune_cache/triton`.
- [ ] **`docker exec env`** (not `/proc/1/environ`) also sees them — this
      is what's NEW. Before the recreate, `docker exec env` only sees
      docker-layer vars; after the recreate, the autotune dirs are at
      docker layer:
      `ssh sander@192.168.1.10 'docker exec vllm-qwen3.6-35b-balanced-k3 env | grep -E "FLASHINFER|TRITON_CACHE"'`
- [ ] First completion request returns 200 within 30 s (TTFT may be
      higher than warm baseline — that's expected on a cold engine):
      ```bash
      ssh sander@192.168.1.10 'time curl -s -o /dev/null -w "%{http_code}\n" \
        -H "Authorization: Bearer genesis-local" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen3.6-35b-a3b\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":4}" \
        http://localhost:8102/v1/chat/completions'
      ```
- [ ] No new errors in the boot log:
      `ssh sander@192.168.1.10 "docker logs vllm-qwen3.6-35b-balanced-k3 2>&1 | grep -iE 'error|traceback' | grep -vE 'warn|info|notice' | head -20"`

## Bench A/B protocol

Compare pre-recreate vs post-recreate steady-state. The hypothesis to
test: with the autotune cache populated and warm, `wall_TPS` converges
faster after restart and the mean recovers toward historic 228.

### Pre-recreate baseline (recorded before any change)

From iter N+5 (2026-06-09 journal):

| metric | value |
|--------|------:|
| wall_TPS mean | 217.46 |
| wall_TPS CV | 5–7 % |
| TTFT mean | 147 ms |
| TTFT σ | 44 |
| decode_TPOT | 4.91 ms |

### Post-recreate measurement plan

Three warm-up cycles, then the bench. Reasoning: autotune state needs
multiple decode passes to converge to the same configs the historic 228
measurement saw.

```bash
# Warm-up cycle (run 3 times)
ssh sander@192.168.1.10 'for i in 1 2 3 4 5 6; do \
  curl -s -o /dev/null \
    -H "Authorization: Bearer genesis-local" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"qwen3.6-35b-a3b\",\"messages\":[{\"role\":\"user\",\"content\":\"warmup pass '"$i"' write a 200 token paragraph about thermodynamics\"}],\"max_tokens\":1024}" \
    http://localhost:8102/v1/chat/completions; \
done'

# Bench (same script used for the iter N+5 baseline)
ssh sander@192.168.1.10 'cd ~/genesis-vllm-patches && \
  python3 tools/bench_decode_tpot_clean_ab.py \
    --base-url http://localhost:8102/v1 \
    --api-key genesis-local \
    --model qwen3.6-35b-a3b \
    --n 50 --max-tokens 1024 \
    --out /tmp/post_recreate_bench.json'

# Compare
ssh sander@192.168.1.10 'cat /tmp/post_recreate_bench.json | python3 -m json.tool | head -40'
```

### Pass criteria

| metric | pre-recreate | target post-recreate | failure threshold |
|--------|-------------:|---------------------:|------------------:|
| wall_TPS mean | 217.46 | ≥ 218 (any recovery is a win; 225+ is the goal) | < 210 |
| wall_TPS CV | 5–7 % | ≤ 7 % | > 10 % |
| TTFT mean | 147 ms | within 2× of pre (≤ 300 ms) | > 500 ms |
| TTFT σ | 44 | ≤ 60 | > 100 |
| decode_TPOT | 4.91 ms | ≤ 4.9 ms (lower is better) | > 5.5 ms |
| Patch summary | 104 / 128 / 1 | 104 / 128 / 1 (±1 skipped) | failed > 1 |

### A second bench after sustained load (optional)

After 200 sustained requests (the conditions that produced the
historic 228 measurement), re-bench:

```bash
ssh sander@192.168.1.10 'cd ~/genesis-vllm-patches && \
  python3 tools/genesis_bench_suite.py \
    --base-url http://localhost:8102/v1 \
    --api-key genesis-local \
    --model qwen3.6-35b-a3b \
    --n 50 --max-tokens 1024'
```

This validates the hypothesis that historic 228 was a
"sustained-warm-cache" measurement that fresh-cache cannot reach in 1
bench cycle but should reach after sustained load.

## Rollback procedure

The recreate script renames the old container; it does NOT remove it.
Rollback is a single ssh command:

```bash
ssh sander@192.168.1.10 \
  'docker stop vllm-qwen3.6-35b-balanced-k3 && \
   docker rm vllm-qwen3.6-35b-balanced-k3 && \
   docker rename vllm-qwen3.6-35b-balanced-k3-rollback-<TIMESTAMP> \
                 vllm-qwen3.6-35b-balanced-k3 && \
   docker start vllm-qwen3.6-35b-balanced-k3'
```

Replace `<TIMESTAMP>` with the exact UTC timestamp printed by the
recreate script (visible in the final report). The script prints the
exact rollback one-liner at the end of a successful recreate AND on a
failed health check.

**When to roll back:**

  * `/health` does not return 200 within 10 min.
  * Patch summary has more `failed=` than pre-recreate.
  * First completion request returns 5xx.
  * Bench `wall_TPS` < 210 after 3 warm-up cycles + bench (significant
    regression vs pre-recreate baseline 217).

**When NOT to roll back:**

  * `wall_TPS` 210–217 (within CV; gather more samples first).
  * Higher TTFT on the first 1–2 requests (expected — engine is cold).

## Cleanup (only after bench A/B PASS)

When the new container has been validated by the bench A/B above, the
rollback container can be removed to free disk:

```bash
ssh sander@192.168.1.10 'docker rm vllm-qwen3.6-35b-balanced-k3-rollback-<TIMESTAMP>'
```

Do NOT clean up the rollback container until the bench A/B passes.

## Failure-mode triage

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `/health` 200 but `/v1/models` 401 | API key drifted | Check `--api-key` in launcher matches the request |
| Patch summary `applied` count drops | Source-code drift; new image | Check `pip install -e` step in launcher; check sndr ro bind |
| Patch summary `failed` count up | Plugin import error; check first few patches | `docker logs ... grep -E "Failed to apply|ImportError" | head -20` |
| `wall_TPS` < 200 even after 3 cycles | Autotune cache not being read | Verify host-side: `ls -la /home/sander/genesis-vllm-patches/.autotune_cache/triton/` size growing? |
| Container OOMKilled after 5 min | Memory increase from new env | Check `docker inspect` `OOMKilled: true`; revert PN204=0 flip if introduced |
| NCCL hang at boot | TP=2 bootstrap | `nvidia-smi` confirms both GPUs visible; `docker logs ... grep NCCL` |

## Iron-rule notes for this playbook

This playbook implements the operator's six-step rule (Study → Analyze →
Verify → Search → Compare → Change) for the container-recreate
operation:

  * **Study**: read the current launcher `run.sh` to find what env it
    exports.
  * **Analyze**: identify which exports take effect at PID 1 (the
    engine) vs which need to be at the docker layer (sidecars).
  * **Verify**: `docker exec env` vs `/proc/1/environ` confirm the
    layer difference live.
  * **Search**: no external recreate tool exists for this exact
    Genesis + vLLM + autotune-cache combination; standard `docker run`
    + a snapshot-then-replay pattern is the right approach.
  * **Compare**: nothing in `tools/` already does this — closest is
    `tools/restart_35b_dev371_multiconc.sh` which is a plain restart,
    not a recreate.
  * **Change**: `tools/safe_container_recreate.py` + this playbook.

## Source files

  * Script: `tools/safe_container_recreate.py`
  * Launcher (server): `/tmp/qwen3.6-35b-balanced_launcher/run.sh`
  * Image SHA (current pin): `vllm/vllm-openai:nightly-303916e93`
    (sha256 `d892cc417362...`)
  * A/B reference: `docs/superpowers/journal/2026-06-09-wall-tps-regression-investigation-AB.md`
