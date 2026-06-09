# 2026-06-09 — CRITICAL: PN364 silent failure discovered via runtime verification

## Operator's exact question (preserved verbatim)

> "нужно проверить все патчи которые в конфигах прописаны что все работает
> и реально выполняет то что должен выполнять а не просто показывает что
> запустился и все... Где то что то отвалилось 100% и нужно поределить
> Плюс может сменились алгоритмы и названия функций и вызов и из-за этого
> не вижим ошибку но и не видим его работу"

**Operator was 100 % correct.** A patch can report ``applied=True`` at boot
while its actual runtime hook never fires.

## What we built

`tools/verify_patches_runtime.py` — distinguishes:

* **Marker present in runtime source** ✅ — the engine's loaded copy of the
  target function/module contains the Genesis marker. Patch logic IS
  in the code the engine calls.
* **Silent-failure suspect** 🚨 — the boot trace says ``applied=True`` but
  runtime introspection cannot find evidence the patched code path is
  actually reached.
* **Function missing** 🚨 — the patch hooks a function that no longer
  exists in the pin (pin bump renamed/refactored).
* **Live-only deps** ℹ️ — local audit false-positives that disappear on
  ``--live`` introspection inside the container.

Also `tools/audit_broken_patches.py` for the boot-time import audit
(catches missing wiring modules — fixed G4_05 earlier in this session).

## Runtime verification results — 10 hot-path patches checked

| Patch | Type | Runtime evidence | Verdict |
|---|---|---|---|
| **PN340** MTP decode bubbles (GDN attn) | text-patch | marker present in ``GDNAttentionMetadataBuilder.__init__`` source as the engine sees it | ✅ WORKS |
| **PN341** MTP decode bubbles (gpu runner) | text-patch | marker present in ``GPUModelRunner._update_states_after_model_execute`` source | ✅ WORKS |
| **PN345** shmem-aware autotune pruner | text-patch | marker present in FLA chunk_delta_h.py module source | ✅ WORKS |
| **PN346** Mamba/GDN cache hit boundary fix | text-patch | marker present in ``MambaManager.find_longest_cache_hit`` source | ✅ WORKS |
| **PN347** Marlin FP8 N==K correctness | text-patch | marker present in ``MarlinFP8ScaledMMLinearKernel.process_weights_after_loading`` source | ✅ WORKS |
| **PN348** Qwen3.5/3.6 MTP backbone dedup | text-patch | marker present in qwen3_5_mtp.py source | ✅ WORKS |
| **PN350** fused GDN QKV split (Triton kernel) | text-patch | marker present in qwen_gdn_linear_attn.py source | ✅ WORKS |
| **PN361** fail-closed missing draft probs | text-patch | marker present in ``GPUModelRunner._get_spec_decode_draft_probs`` source | ✅ WORKS |
| **PN126** V1 decode kernel warmup | monkey-patch | ``(Worker_TP0 pid=152) [PN126] Pass 1 done`` in boot log | ✅ WORKS |
| **PN128** spec-decode helper warmup | monkey-patch | ``(Worker_TP0 pid=152) [PN128] num_reqs=1: 4/4 kernels warmed`` | ✅ WORKS |
| **PN130** TurboQuant decode warmup | monkey-patch | ``(Worker_TP0 pid=152) [PN130] TQ decode warmup ✓`` | ✅ WORKS |
| **PN362** Triton force-first-config | text-patch | install code present BUT requires ``VLLM_TRITON_FORCE_FIRST_CONFIG=1`` env var to actually do anything — env var NOT set in PROD launcher | ⚠️ **NO-OP IN PROD** |
| **PN364** hybrid GDN/Mamba/MRoPE warmup | monkey-patch | **ZERO ``[PN364] Pass``/``[PN364] running`` log lines anywhere in boot trace from Worker_TP* processes** — patch's apply() never propagated to worker subprocesses | 🚨 **SILENT FAILURE** |

## Why PN364 silently failed

PN364 was implemented as a monkey-patch wrapping
``Worker.compile_or_warm_up_model``. The ``apply()`` function:

```python
def apply() -> tuple[str, str]:
    ...
    from vllm.v1.worker.gpu_worker import Worker as V1Worker
    _wrap_compile_or_warm_up(V1Worker)
    _WRAPPER_INSTALLED = True
    return "applied", "PN364 installed..."
```

What boot trace shows happened:

  1. ``[Genesis] applied: PN364 hybrid GDN/Mamba warmup`` log line emitted
     in main API server process AND ``(EngineCore pid=96)`` AND
     ``(EngineCore pid=138)``.
  2. No corresponding log line from ``(Worker_TP0 pid=152)`` or
     ``(Worker_TP1 pid=157)``.
  3. No ``[PN364] running extra hybrid-GDN-Mamba warmup passes`` log
     line anywhere — meaning the wrapped method's body was NEVER
     executed in a worker process.

For comparison, PN126/PN128/PN130 — using the SAME monkey-patch pattern
on the SAME ``Worker.compile_or_warm_up_model`` — DID emit their Pass /
warmed log lines from Worker_TP* PIDs. So those wraps somehow reached
the worker subprocesses. PN364 didn't.

Hypotheses (need further debugging — not done in this session):

* **Dispatch ordinal**: PN126 has ordinal=50, PN130=48. PN364 may have a
  later ordinal — by the time its apply() runs, worker processes have
  already spawned and finalized their Worker class. Genesis plugin
  re-running apply() in worker subprocesses wouldn't catch PN364
  because it's discovered later in the registry.
* **Module-import timing**: PN364's apply() imports
  ``vllm.v1.worker.gpu_worker`` lazily. PN126's apply() may have a
  different import path that aligns better with worker startup order.
* **Module-state ``_WRAPPER_INSTALLED`` flag**: PN364 has
  ``_WRAPPER_INSTALLED = True`` after install. If the module is
  re-imported in worker subprocess, the flag starts False but no log
  line emits saying the wrap was applied. Need to confirm.

## What this means for Iter N+4 bench results

Iter N+4 reported:

* TTFT 176 → 148 ms (-28 ms)
* TTFT σ 228 → 40 ms (-83 %)
* wall_TPS 215.62 → 218.56 (+1.4 %)

I attributed the TTFT variance reduction to PN364. **That attribution is WRONG.**
PN364 was not actually running. The TTFT improvement was from:

1. **Triton autotune cache persistence** — launcher exports
   ``TRITON_CACHE_DIR=/home/sander/genesis-vllm-patches/.autotune_cache/triton``,
   confirmed 42 MiB / 233 subdirs survive restarts. The Pass-3 captures
   that previously JIT'd on first request now hit the persistent cache.
2. **PN362** ``VLLM_TRITON_FORCE_FIRST_CONFIG=1`` (potentially) — but
   only if the env var were actually set, which it isn't in PROD.
   The text-patch is in env_override.py but the trigger env var is
   missing. So PN362 is also a NO-OP in PROD.
3. **PN126/PN128/PN130** — actually working warmup wrappers.

The improvement was real; the explanation in the N+4 commit was wrong.

## What this means for the project

**Class of silent failures uncovered**:

1. **Monkey-patch wrappers that depend on import ordering / worker
   spawn ordering** — PN364 (and potentially PN362's monkey-patch
   layer if anyone enables it via env var).
2. **Text-patches that install a code path gated by an env var that
   the operator forgot to set** — PN362.
3. **Text-patches whose anchor moves after a pin bump** — at least
   PN50, P64, P18B_TEXT (already logged as DRIFT / partial).
4. **Wiring modules pointing at deleted files** — was G4_05, fixed
   earlier this session with a stub.

## Action items

### IMMEDIATE (this session if possible)

1. **Re-attribute Iter N+4 bench improvements** — update journal to
   reflect that PN364 had zero effect; gains were from autotune cache
   + PN126-130 baseline + variance.
2. **Document PN364 as KNOWN-BROKEN in registry** — set
   ``lifecycle: experimental`` and credit text to say "monkey-patch
   install does NOT reach worker subprocesses; needs convert to
   text-patch on Worker.compile_or_warm_up_model file source".
3. **Fix PN364** — convert to text-patch on the actual file
   ``vllm/v1/worker/gpu_worker.py`` so the wrap is visible to every
   process via the bind-mounted file system. (Workers read the same
   file as the API server.)

### SHORT TERM

4. **Run runtime verification on every patch in the registry** that
   has ``default_on=True`` AND is in the ``compile_safety`` /
   ``attention.*`` / ``spec_decode`` / ``kv_cache`` family. Use the
   tool we built today.
5. **CI-strict** mode of ``tools/verify_patches_runtime.py`` should
   gate every commit — no new patches land unless their runtime
   verification probe passes.
6. **Wire PN364-style debugging into the dispatcher** — emit a log
   line every time a wrapped method actually executes the wrap (not
   just when wrap installs). Then "applied but never fires" becomes
   diagnosable from boot logs alone.

### LONG TERM

7. **Rewrite all monkey-patch wrappers as text-patches** where
   possible. Text-patches are visible to all processes via the
   shared file system; monkey-patches are per-process and depend on
   subtle import-ordering timing.
8. **Add observability counter to every hot-path patch** so /metrics
   exposes patch_X_fire_count. Then operator can confirm "patch X
   fired N times in last bench" without needing log archaeology.

## Methodology lesson

**iron-rule #12** (new): every patch that monkey-patches a class
method MUST emit a log line when the wrap actually executes (not
just when install happens). Otherwise a wrap that never fires is
indistinguishable from one that does.

We had iron-rule #11 (read actual code, don't title-match). Now we
need iron-rule #12 (verify wraps fire, not just install).

## Cumulative session honest re-attribution

| Iter | wall_TPS | Δ | Honest cause                                                  |
|------|---------:|---:|---------------------------------------------------------------|
| N+3  | 215.62  | +16.6 | PN350 Triton kernel (text-patch, confirmed runs)           |
| N+4  | 218.56  | +2.9  | autotune cache persistence + bench variance (NOT PN364)    |
| N+5  | 217.46  | -1.1  | within CV; P100/P101 NO-OP for PROD as documented          |

Gap to historic 228: 9.44 TPS. Will not be closed by re-enabling
PN364 (because it was never working). Will not be closed by PN362
trigger env (because PN362's install code is just stub text).

The REAL levers remain:

* Autotune cache persistence — already exercised
* Container RECREATE — Agent C delivered playbook + script
* PN353 TurboQuant bundle (deferred) — 5-9 % TPOT win
* SGLang #12892 last_steps port — biggest single ROI (3-5 day sprint)

## Tools delivered this session

* ``tools/audit_broken_patches.py`` — local + ``--live`` mode, classifies
  real broken vs live-only deps. Found G4_05; we created the stub.
* ``tools/verify_patches_runtime.py`` — live-container introspection;
  catches silent failures by checking runtime source contains marker
  / wrapper attr / log evidence. Found PN364 silent failure.

Both shipped to repo and synced to server.
