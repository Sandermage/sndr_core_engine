# Operations — the day-2 runbook

Install day is covered by [`INSTALL.md`](INSTALL.md) →
[`QUICKSTART.md`](QUICKSTART.md). This is everything after: daily
health checks, swapping models on shared GPUs, benching cadence, pin
bumps and rollbacks, log triage, GUI daemon lifecycle, and disk
hygiene. Reference topology throughout: 2× RTX A5000, TP=2, pin
`dev748` (`0.23.1rc1.dev748+g2dfaae752`, current per `sndr/pins.yaml`
as of 2026-07-04), rollback `dev714`.

## Daily health checks

Three probes, ~10 seconds total:

```bash
# 1. Engine liveness (vLLM OpenAI server)
curl http://localhost:8000/health -H "Authorization: Bearer genesis-local"
# -> HTTP 200 (empty body). Anything else: see log triage below.

# 2. GUI / product-API daemon (auth-exempt endpoint)
curl http://127.0.0.1:8765/api/v1/health
# -> {"status":"ok",...,"read_only":true}

# 3. What's actually running
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
# -> the expected engine container (e.g. vllm-35b-dev748) Up, port 8000
```

Deeper, when something smells off:

```bash
sndr doctor            # hardware + software + model + patches diagnostic
sndr doctor --full     # + image/mounts/license/engine/remote sections
sndr engines           # registered engines (alias of engines.list)
sndr tui               # live terminal cockpit if you want to watch it
```

A functional smoke beats a liveness probe — one short chat completion
(see the curl in [`QUICKSTART.md`](QUICKSTART.md)) confirms the model
answers, not just that uvicorn is up.

## Model swapping on shared GPUs

The reference rig runs ONE heavy model at a time — 24 GB cards leave
no room for two. The swap pattern is **stop → launch → health**:

```bash
docker stop vllm-qwen3.6-35b-a3b-fp8        # free the VRAM (both cards)
sndr launch prod-qwen3.6-27b-tq-k8v4        # render + boot the other preset
# wait for the boot apply summary in `docker logs -f <container>`, then:
curl http://localhost:8000/health -H "Authorization: Bearer genesis-local"
```

**The warm-layer `docker start` trick.** When you swap back and forth
between presets you have ALREADY booted on the current pin, keep the
stopped containers around and just restart them instead of
re-rendering:

```bash
docker stop vllm-qwen3.6-27b-...
docker start vllm-35b-dev748     # reuses the existing container: warm
                                 # triton/compile caches, patches already
                                 # present in the writable layer
```

This is the fastest swap (cold boots on this rig run 140–370 s per
model, fleet sweep dev748 2026-07-04; a warm `docker start` skips
render + pull + much of the compile). Two caveats:

- On a restarted (already-patched) writable layer the boot apply
  reports text patches as `already applied (marker present)` or skips
  with `anchor not found` — expected, the modifications are already in
  the layer. Do NOT panic-diff that summary against a fresh boot's.
- For a **clean** apply summary — after a config edit, pin change, or
  when triaging patch behavior — use a fresh container instead:
  `sndr launch <preset>` (or `docker compose down` → `up -d`). The
  recycled-layer subtleties are catalogued in
  [`QUICKSTART.md`](QUICKSTART.md) § "Stopping cleanly" and
  [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## Benching cadence

Canonical harness: `tools/genesis_bench_suite.py` — the only
methodology whose numbers are comparable with
[`BENCHMARKS.md`](BENCHMARKS.md) (custom scripts carry a 5–25%
systematic offset). Three modes:

| Mode | Cost | When |
| --- | --- | --- |
| `--quick` | ~5 min | after ANY config/patch/flag change; after every model swap you care about; pin-bump smoke |
| `--mode standard --ctx 8k` | ~15–30 min | weekly on the PROD preset; after promoting a profile |
| `--mode full --ctx all` | ~1–2 h | before a release/promotion; after hardware changes; quarterly |

```bash
# routine post-change check
python3 tools/genesis_bench_suite.py --quick --ctx 8k \
    --out ~/.sndr/bench-results/35b_$(date +%Y%m%d).json

# did it regress? (post-hoc, no server needed)
python3 tools/genesis_bench_suite.py --compare baseline.json today.json
```

Judge results against the current labeled reference (pin dev748,
2026-07-04): 35B AWQ wall_TPS **242.55** (CV 6.9%), decode_TPOT
3.9 ms, TTFT 84.5 ms, tool-calls 7/7, ctx-scaling LINEAR_OK — full
tables and per-model fleet numbers in
[`BENCHMARKS.md`](BENCHMARKS.md). Deltas within the run's CV are
noise; act only on repeatable regressions.

## Pin bumps (summary)

The canonical end-to-end procedure is
[`PIN_BUMP_PLAYBOOK.md`](PIN_BUMP_PLAYBOOK.md) — read it before your
first bump. The shape, so you know where you are:

1. Never `docker pull` a newer image proactively — bumps happen on
   explicit operator decision only.
2. Offline preflight against the candidate's pristine tree
   (`make preflight`, `make bump-preflight`) → fix anchor drifts.
3. Throwaway-container boot smoke (+ `make fleet-boot-smoke` for the
   whole fleet), tokenizer-fingerprint gate.
4. Canonical bench vs `reference_metrics` (§ 6).
5. Promote: `make bump-pin NEW=<pin>` (+ `--sha-full`), then
   `make rebuild-pin` and `make audit-pin-consistency`.
6. Tag rotation: `:nightly` re-tagged to the new pin, previous pin
   kept as rollback, oldest dropped (≤ 2 nightly pins on the server).

## Rollback recipes

The whole point of the ≤2-pin policy is that rollback is one command,
not an investigation. `sndr/pins.yaml` tells you what to roll back TO
(`rollback: 0.23.1rc1.dev714+g09663abde` as of 2026-07-04).

**Fast path — the previous container still exists** (it should, during
any validation window):

```bash
docker stop <new-pin-container>
docker start <old-pin-container>     # e.g. the dev714-era container
curl http://localhost:8000/health -H "Authorization: Bearer genesis-local"
python3 tools/genesis_bench_suite.py --quick    # confirm the old numbers
```

**Config-level rollback** — repoint the hardware YAML at the rollback
image (`runtime.docker.image` + `image_digest` must track together;
the explicit-hash `nightly-<sha>` tags exist for exactly this), then
`sndr launch <preset>`. A model held on the rollback pin while the
fleet moves on MUST document that in `versions.pin_hold` + the
launcher header (pin-uniformity rule,
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) § "Pin policy").

**Everything else** — broken schema, bad profile, patch regression:
the scenario-indexed rollback playbook (R-001…R-008) at the bottom of
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## Log triage

First stop, always:

```bash
docker logs <container> 2>&1 | tail -200
```

**1. The apply summary line.** Every boot prints one
(`total= applied= skipped= failed=` — see
[`GLOSSARY.md`](GLOSSARY.md) "dispatcher"); on the 35B PROD preset it
reads:

```text
applied=87 skipped=166 failed=0
```

- `failed=0` is the ONLY acceptable value. `failed>0` → the named
  patch's traceback is right above; do not serve traffic.
- Expected profile on the current pin: **applied=87 / skipped=166 /
  failed=0** (35B, dev748, 2026-07-04 promotion window). A sudden
  change in `applied` between boots of the same preset = drift —
  diff the per-patch lines.

**2. Skip categories** — a SKIP names its reason; they are not equal:

| Skip reason | Meaning | Action |
| --- | --- | --- |
| disabled by env / not enabled | flag off for this preset | none — by design |
| `applies_to` mismatch | patch gated to another model/arch/pin range | none |
| `drift marker found` | upstream ABSORBED the fix on this pin | harmless; optionally drop the enable flag ([`INSTALL.md`](INSTALL.md) § troubleshooting) |
| `anchor not found` | anchor drifted — patch did NOT apply | investigate if the patch is load-bearing; on a warm restart of an already-patched layer this is expected (see swap section) |
| `already applied (marker present)` | idempotent re-apply short-circuit | none — normal on warm restarts |

**3. Loader / wiring markers.** Runtime-hook patches log their own
proof-of-life; grep for the patch ID. Example — PN520 (the Qwen3.5/3.6
GDN weight-loader restore, battle-validated in the dev748 fleet sweep,
2026-07-04):

```text
[PN520] imperative load_weights ACTIVE (this loader is running)
[PN520] load_weights done: 96 in_proj_ba shards routed, ... params total
```

The ACTIVE line missing (while the flag is on) or `0 shards routed`
means the patch is inert — same class of silent failure the fleet
sweep caught. When a model misbehaves subtly (degenerate output,
wrong tool calls), check the wiring markers of its load-bearing
patches before blaming the model.

## GUI daemon restart

The daemon (product-API + GUI, port 8765) is stateless — restarting it
never touches the engine:

```bash
sndr down                    # stops engine + daemon (the `sndr up` pair)
sndr up --no-engine          # daemon + GUI only, engine left alone
# or run it in the foreground for debugging:
python3 -m sndr.cli gui-api --host 127.0.0.1 --port 8765
```

Port 8765 already in use → a stale daemon holds it: `sndr down`, then
`sndr up` ([`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) quick-triage
table). Daemon security/bind/auth knobs:
[`GUI_SECURITY.md`](GUI_SECURITY.md).

## Disk hygiene

The things that silently eat a homelab disk, in observed order:

```bash
# 1. vLLM images — enforce the pin policy: at most current + rollback
#    nightly pins (+ the stable release slot). More than 2-3 tagged
#    builds = cleanup time.
docker images vllm/vllm-openai
docker rmi vllm/vllm-openai:nightly-<retired-sha>    # drop the oldest pin

# 2. Dangling layers + build cache
docker image prune          # untagged layers from re-tags/pulls
docker builder prune        # buildkit cache (GUI/memory image builds)

# 3. Genesis-side accumulation
du -sh ~/.sndr/bench-results ~/.sndr/reports 2>/dev/null   # bench JSONs, report bundles
du -sh ${triton_cache} ${compile_cache}   # per-config kernel caches grow per pin
```

Rules of thumb: a stale `:nightly` tag is a landmine (it can hide what
build the operator actually runs) — after every promotion confirm
`:nightly` points at the SSOT `current_image` SHA. Old per-pin
triton/compile cache subdirs can be deleted once their pin is retired;
they regenerate in one boot (+30–60 s).

## Weekly checklist

| Check | Command | Green |
| --- | --- | --- |
| Engine + GUI health | the three daily probes above | 200 / `status:ok` / container Up |
| Apply profile stable | `docker logs <c> \| grep -E 'applied=\|failed='` | `failed=0`, `applied` unchanged |
| Bench drift | `--quick` run vs last week's JSON | Δ within CV |
| Pin inventory | `docker images vllm/vllm-openai` | ≤ 2 nightly pins + stable |
| Pin/artifact sync | `make audit-pin-consistency` | exit 0 |
| Disk | `df -h` + the hygiene block above | headroom, no orphan tags |
| Doctor | `sndr doctor` | no critical findings |

## See also

- [`PIN_BUMP_PLAYBOOK.md`](PIN_BUMP_PLAYBOOK.md) — the canonical bump procedure
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — cliffs, OOM recipes, rollback playbook R-001…R-008
- [`BENCHMARKS.md`](BENCHMARKS.md) — methodology + current labeled numbers
- [`QUALITY_GATE.md`](QUALITY_GATE.md) — stress/soak gate for deeper validation
- [`HOST_SETUP.md`](HOST_SETUP.md) — host.yaml (mount failures start here)
- [`GUI.md`](GUI.md) — the Control Center the daemon serves
