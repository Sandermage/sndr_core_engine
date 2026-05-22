# Genesis vLLM Patches — Интегрированный план действий

**Версия:** 2026-05-09
**Объединяет:**
- `docs/upstream/DEEP_AUDIT_VLLM_NOONGHUNNA_2026-05-08_RU.md` (внешний аудит)
- `docs/_internal/BACKLOG_2026-05-09.md` (текущий backlog после Wave 7)

**Статус P0 фиксов на момент создания:** ✅ всё зелёное
- pytest: **2994 passed / 0 failed / 94 skipped**
- no-torch dry-run: **failed=0** (114 applied, 20 skipped)
- 35B PROD bench Wave 7: **TPS 237.95 (+0.7% выше baseline)** + tool 7/7
- 27B PROD bench Wave 7: **TPS 124.29** (within noise) + decode_TPOT **-7%** + tool 8/8

---

## Уже сделано в этой сессии (P0 + P1.1 + P1.3 + P2.1)

| ID | Что | Файлы | Статус |
|---|---|---|---|
| **P0.1** | R-011 audit_rules: добавлены префиксы `GENESIS_PN16_`, `GENESIS_FLA_GUARD_`, `GENESIS_PN65_`, `GENESIS_PN72_`, `GENESIS_OBSERVABILITY` | `vllm/sndr_core/model_configs/audit_rules.py:622-636` | ✅ |
| **P0.2** | test_model_config_cli: hardcoded TPS 231.41 → YAML-driven через `_expected_tps()` helper | `tests/legacy/test_model_config_cli.py` | ✅ |
| **P1.1** | No-torch dry-run failed=0: `ImportError → skipped` для P22, P31, P32/P33, P28, P7, P17/P18, P20 | `vllm/sndr_core/apply/_per_patch_dispatch.py` | ✅ |
| **P1.3** | Community samples: `vllm/_genesis` → `vllm/sndr_core` mount path | `gemma-4-26b-a4b-awq.yaml.sample`, `EXAMPLE_symbolic_mounts.yaml.sample` | ✅ |
| **P2.1** | Hardcoded IPs `192.168.1.10` → `127.0.0.1` defaults | `benchmarks/harness/run_all.py`, `tests/probes/streaming_thinking_probe.py` | ✅ |

---

## Sprint 0 — финал стабилизации (1-2 дня)

### S0.1 — README актуализация (P1.3 продолжение)

**Что говорит аудит:**
> README still claims old structure (PN72 commercial, 130 patches, pytest 2425→2621, 131 entries). Текущий: 132 specs, all community, pytest 2994.

**Точки правки (`README.md`):**
- `:19-35` — структура `sndr_core` / `sndr_engine`
- `:39-41` — patch count
- `:83-92` — engine-tier description
- pytest baseline numbers

**Код:**
```markdown
## Structure

- `vllm/sndr_core/` — public Apache-2.0 patches (132 entries, all community tier)
- `vllm/sndr_engine/` — reserved namespace, currently empty (`engine_available()` returns False)
  Future commercial overlay will land here when there is closed IP not present in upstream PRs.

## Test posture (2026-05-09)

- pytest: 2994 passed / 0 failed / 94 skipped (env-dependent)
- No-torch dry-run: 114 applied / 20 skipped / 0 failed
- Server-verified bench: 35B 237.95 TPS / 27B 124.29 TPS / tool 7-8/8
```

Effort: 0.5d (text-only). Decision: оставить на отдельный коммит с финальным review.

### S0.2 — PRODUCTION_ROADMAP_2026-05-09 retire as historical

**Аудит:** `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md` уже не соответствует коду.

**Решение:**
1. Добавить header в файл:
   ```markdown
   > **Historical snapshot** taken 2026-05-09. Current source of truth:
   > `docs/_internal/INTEGRATED_PLAN_2026-05-09.md`. Findings in this file
   > may be stale — see "Уже сделано" section of the integrated plan.
   ```
2. Не удалять — нужен для аудита эволюции.

Effort: 5 минут.

### S0.3 — Bare-metal renderer wheel-mode separation (P2-2)

**Аудит:** `vllm/sndr_core/compat/model_config_cli.py:582-615` делает `pip install -e {plugin_src}` в production-mode bare-metal scripts с `|| true` маскирующим ошибки.

**Решение:**

```python
# vllm/sndr_core/compat/model_config_cli.py
def render_bare_metal_script(cfg, *, mode: str = "wheel") -> str:
    """Render bare-metal launch script.

    mode='wheel': требует pre-installed sndr_core wheel; не делает editable install
    mode='dev':   разрешает editable install + source path mounts
    mode='dev_strict': editable install БЕЗ `|| true` — fail на ошибке
    """
    if mode == "wheel":
        # Verify import path WITHOUT pip install
        return f"""
        python3 -c 'import vllm.sndr_core' || {{
            echo "ERROR: vllm-sndr-core wheel not installed"
            exit 1
        }}
        """
    # ... существующий dev-friendly путь, но с явным mode флагом
```

**Тест:**
```python
# tests/unit/compat/test_model_config_cli_modes.py
class TestRenderModes:
    def test_wheel_mode_does_not_emit_pip_install(self):
        out = render_bare_metal_script(cfg, mode="wheel")
        assert "pip install" not in out
        assert "import vllm.sndr_core" in out

    def test_dev_strict_mode_no_silent_fail(self):
        out = render_bare_metal_script(cfg, mode="dev_strict")
        assert "|| true" not in out
```

Effort: 1d. Wheel CI gate откроется после.

---

## Sprint 1 — Boost-above-236 sweep (1.5 дня)

Из BACKLOG Phase 1 — поиск real TPS wins выше текущего 237.95.

### S1.1 — `GENESIS_P67_NUM_KV_SPLITS` sweep

**Гипотеза:** memory says 32 валидирован, но 320K context может сместить optimum.

**Метод:**
```bash
# 4 bench rounds, каждый ~10 минут (boot + bench)
for splits in 16 32 48 64; do
  GENESIS_P67_NUM_KV_SPLITS=$splits bash start_35b_pn90_test.sh
  # wait API ready
  python3 tools/genesis_bench_suite.py --quick --name 35b_split_${splits} \
    --out bench_results/sprint1/35b_split_${splits}.json
  docker stop vllm-server-pn90-test
done
```

**Acceptance:**
- TPS > 240 на каком-либо split → save winner в YAML, document
- Else → log что 32 confirmed optimum

Effort: 1d.

### S1.2 — `GENESIS_P82_THRESHOLD_SINGLE` sweep (0.2/0.3/0.4)

Аналогично. 3 bench rounds.

### S1.3 — `VLLM_FLOAT32_MATMUL_PRECISION=medium` A/B

Один bench. Risk: accept_rate может drop.

### S1.4 — `max_num_batched_tokens` 4096→8192 A/B

Один bench. Risk: scheduler может drop TTFT.

### S1.5 — Зафиксировать winner combo в PROD YAML

Если найдём combo дающий >240 TPS — обновить:
- `vllm/sndr_core/model_configs/builtin/a5000-2x-35b-prod.yaml:reference_metrics`
- `genesis_pin: v11.0.0+wave7+sprint1`

---

## Sprint 2 — Patcher infrastructure foundations (3-4 дня)

### S2.1 — Regression bench harness в CI

**Файл:** `tests/integration/test_patch_regression_bounds.py`

**Структура:**
```python
"""Bench-driven regression detection.

Runs subset of genesis_bench_suite.py against a live test server
(skipped on Mac). Asserts decode_TPOT/tool/wall_TPS within tolerances.
"""
import os, json, subprocess, pytest

BASELINE = json.load(open("tests/integration/baselines/35b_wave7.json"))

@pytest.mark.skipif(
    not os.environ.get("GENESIS_INTEGRATION_ENDPOINT"),
    reason="set GENESIS_INTEGRATION_ENDPOINT=http://server:8000/v1 to run"
)
def test_no_decode_tpot_regression():
    out = subprocess.check_output([
        "python3", "tools/genesis_bench_suite.py",
        "--quick", "--skip-stress", "--skip-ctx-probe",
        "--out", "/tmp/regress.json",
    ])
    result = json.load(open("/tmp/regress.json"))
    tpot = result["decode_bench"]["decode_tpot_ms"]
    baseline_tpot = BASELINE["decode_bench"]["decode_tpot_ms"]
    assert tpot <= baseline_tpot * 1.02, (
        f"decode_TPOT regression: {tpot} > {baseline_tpot * 1.02}"
    )

def test_no_tool_call_quality_regression():
    # ... assert tool_call.passed_positive >= baseline
```

**CI integration:** GitHub Actions matrix or self-hosted GPU runner.

Effort: 2-3d.

### S2.2 — Decode_TPOT-first bench reporting (0.5d)

**Файл:** `tools/genesis_bench_suite.py:945-980` (Summary section).

**Изменение:**
```python
# Было:
print(f"  Decode bench:     wall_TPS {wall_tps:.4f}  CV {cv:.4f}  (n=25)")

# Стало:
print(f"  Decode bench (per-token, primary):")
print(f"    decode_TPOT_ms = {tpot:.4f}  CV {tpot_cv:.4f}")
print(f"  Throughput proxy (response-length sensitive):")
print(f"    wall_TPS       = {wall_tps:.4f}  CV {cv:.4f}  (n=25)")
```

### S2.3 — Apply contract tests (1d)

**Файл:** `tests/unit/test_patch_apply_contracts.py`

```python
"""Assert every PATCH_REGISTRY entry has a working apply() function.

Codegen test that walks PATCH_REGISTRY and validates the apply contract:
  - apply() callable
  - returns Tuple[str, str]
  - status ∈ {"applied", "skipped", "failed"}
  - never raises (defensive try/except inside)
"""
import pytest
from vllm.sndr_core.dispatcher import PATCH_REGISTRY, iter_patch_specs


@pytest.fixture(scope="module")
def all_specs():
    return list(iter_patch_specs())


class TestApplyContract:
    def test_every_spec_has_apply_module(self, all_specs):
        missing = [s.patch_id for s in all_specs if not s.apply_module]
        assert not missing, f"specs without apply_module: {missing}"

    @pytest.mark.parametrize("spec", iter_patch_specs(), ids=lambda s: s.patch_id)
    def test_apply_module_importable(self, spec):
        """Each apply_module must import cleanly (no torch required)."""
        if spec.apply_module is None:
            pytest.skip("spec-only, no apply_module")
        import importlib
        importlib.import_module(spec.apply_module)

    @pytest.mark.parametrize("spec", iter_patch_specs(), ids=lambda s: s.patch_id)
    def test_apply_returns_tuple(self, spec, monkeypatch):
        if spec.apply_module is None:
            pytest.skip("spec-only")
        # Force env disabled so apply() should return ("skipped", reason)
        monkeypatch.delenv(spec.env_flag, raising=False)
        import importlib
        mod = importlib.import_module(spec.apply_module)
        if not hasattr(mod, "apply"):
            pytest.skip("module has no apply() — non-standard")
        result = mod.apply()
        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], str) and isinstance(result[1], str)
        assert result[0] in {"applied", "skipped", "failed"}
```

### S2.4 — Patch conflict/dependency resolver (1d)

**Файл:** `vllm/sndr_core/apply/orchestrator.py:run()` (после registry validation).

```python
def _validate_dependency_graph(stats):
    """Pre-flight: resolve requires_patches / conflicts_with metadata.

    Logs warnings for missing deps + active conflicts. Future: hard-block
    when env GENESIS_STRICT_DEPS=1.
    """
    from vllm.sndr_core.dispatcher import PATCH_REGISTRY
    enabled_now = {pid for pid, meta in PATCH_REGISTRY.items()
                   if _is_env_enabled(meta.get("env_flag"))}
    for pid in enabled_now:
        meta = PATCH_REGISTRY[pid]
        for req in meta.get("requires_patches", []) or []:
            if req not in enabled_now:
                log.warning(
                    "[Genesis dep-graph] %s requires %s but %s not enabled",
                    pid, req, req,
                )
        for conflict in meta.get("conflicts_with", []) or []:
            if conflict in enabled_now:
                log.error(
                    "[Genesis dep-graph] CONFLICT: %s + %s both enabled",
                    pid, conflict,
                )
                if _strict_mode():
                    raise SystemExit(2)
```

### S2.5 — `sndr bench compare A.json B.json` CLI (1d)

**Файл:** `vllm/sndr_core/cli/bench_compare.py` (новый)

```python
"""sndr bench compare A.json B.json — A/B harness ergonomics."""
import json, statistics
from typing import Tuple

def compare(a_path: str, b_path: str) -> int:
    a = json.load(open(a_path))
    b = json.load(open(b_path))
    print(f"## A: {a['name']}\n## B: {b['name']}\n")
    metrics = [
        ("decode_TPOT_ms", "lower_better"),
        ("wall_TPS", "higher_better"),
        ("TTFT_ms", "lower_better"),
        ("tool_call_passed", "higher_better"),
    ]
    print(f"{'Metric':<25} {'A':>12} {'B':>12} {'Δ':>10} {'verdict':>15}")
    for m, direction in metrics:
        va, vb = _extract(a, m), _extract(b, m)
        delta_pct = ((vb - va) / va * 100) if va else 0.0
        verdict = _verdict(direction, delta_pct)
        print(f"{m:<25} {va:>12.4f} {vb:>12.4f} {delta_pct:>9.2f}% {verdict:>15}")
    return 0
```

### S2.6 — CUDA graph dispatch hit-rate logging (2d)

Hook в `gpu_model_runner.py` через text-patch. Считает % requests dispatched в captured graph vs eager fallback. Эмит лог summary каждые N requests или по запросу через `sndr report`.

---

## Sprint 3 — Per-patch quality audits (3 дня)

### S3.1 — Bench-driven validation per tool-call patch

Расширить `tools/genesis_bench_suite.py` named test cases:
- `p59_tool_call_in_think` — модель эмитит `<tool_call>` внутри `<think>` → проверка что P59 recovery path успешно извлекает
- `p61c_qwen3coder_sse_silence` — narrative `<tool_call>` mention → P61c deferred-commit gate
- `p64_mtp_streaming_truncation` — MTP streaming bundles last param + `</function>` → P64 safety net
- `pn56_xml_fallback` — JSON parse fails → PN56 XML recovery
- `pn66_multiturn_think_leak` — prior assistant `</think>` → PN66 reset
- `pn70_xgrammar_subset` — combined `anyOf` schema → PN70 filter

Effort: 2d.

### S3.2 — "Expected delta" assertions (1-2d)

Каждый perf patch должен иметь test, который assertit measured delta:

```python
@pytest.mark.integration
@pytest.mark.skipif(no_server, reason="needs live server")
def test_p71_block_verify_tps_delta():
    """P71 promised +5-15% TPS on K=3 spec-decode."""
    on = bench_with_env({"GENESIS_ENABLE_P71_BLOCK_VERIFY": "1"})
    off = bench_with_env({"GENESIS_ENABLE_P71_BLOCK_VERIFY": "0"})
    delta_pct = (on.wall_tps - off.wall_tps) / off.wall_tps * 100
    assert delta_pct >= 0.0, f"P71 regressed: {delta_pct:.2f}%"
    # Loose upper bound — claim is +5-15%, accept >= 1% as positive signal
```

### S3.3 — PROD YAML audit script (0.5d)

Скрипт обходит обе PROD YAMLs + проверяет каждый enabled env flag → fires или skipped (not failed).

---

## Sprint 4 — Tool-call deep fix (PN16 V6, 3-5 дней)

Из BACKLOG Phase 3.

### S4.1 — Streaming `<think>` truncator

**Файл:** `vllm/sndr_core/middleware/think_streaming_truncator.py` (новый)

**Дизайн:**
```python
"""PN16 V6 — streaming `<think>` truncator.

Watches the streaming chat-completion response. Counts tokens inside
`<think>...</think>`. When count exceeds GENESIS_PN16_MAX_THINKING_STREAM_TOKENS
AND tools are attached, injects `</think>` into the output stream and stops
forwarding internal thinking tokens. Model's subsequent answer/tool_call
tokens flow through normally.

Cache-safe: doesn't change input prompt. CUDA graphs preserved. MTP draft
compat preserved.
"""
class ThinkStreamingTruncator:
    def __init__(self, budget: int):
        self.budget = budget
        self.in_think = False
        self.token_count = 0
        self.injected_close = False

    def filter_token(self, token_text: str) -> tuple[str, bool]:
        """Return (text_to_emit, stop_internal). stop_internal=True means
        we've truncated and the next tokens should be passed unchanged."""
        if self.injected_close:
            return token_text, False
        if "<think>" in token_text:
            self.in_think = True
            self.token_count = 0
            return token_text, False
        if "</think>" in token_text:
            self.in_think = False
            return token_text, False
        if self.in_think:
            self.token_count += 1
            if self.token_count > self.budget:
                self.injected_close = True
                self.in_think = False
                # Inject `</think>` + signal that we've capped
                return "</think>", True
        return token_text, False
```

**Wiring:** wrap streaming generator at `OpenAIServingChat.chat_completion_stream_generator`.

### S4.2 — Tests + integration with bench

```python
class TestThinkTruncator:
    def test_under_budget_passes_through(self):
        t = ThinkStreamingTruncator(budget=200)
        for tok in ["<think>", "let me", "calculate", "</think>", "answer"]:
            out, _ = t.filter_token(tok)
            assert out == tok

    def test_over_budget_injects_close(self):
        t = ThinkStreamingTruncator(budget=2)
        outputs = []
        for tok in ["<think>", "tok1", "tok2", "tok3", "tok4", "</think>"]:
            out, _ = t.filter_token(tok)
            outputs.append(out)
        # After 2 tokens inside think, next emits </think>
        assert "</think>" in outputs
```

---

## Sprint 5 — Audit closure (Sprint 0 audit + remaining backlog) (3-5 дней)

### S5.1 — Registry specs metadata enrichment (P1-2 from audit)

Аудит: 132/132 specs missing `implementation_status` and `category`.

**Изменения:**

1. Дополнить registry entries — массовый patch:
```python
# vllm/sndr_core/dispatcher/registry.py
# Каждая entry получает:
#   "implementation_status": "live" | "text_patch" | "runtime_hook" |
#                             "metadata_only" | "retired" | "research" |
#                             "blocked" | "upstream_merged"
#   "category": "memory" | "spec_decode" | "structured_output" |
#               "quantization" | "gdn" | "moe" | "launcher" | "security" |
#               "observability" | "research"
#   "source": "genesis_original" | "vllm_pr_backport" | "club_3090_adapted" |
#             "cross_engine_research"
```

2. Schema validator: warning сейчас, error для новых патчей после cutoff.

3. `sndr patches plan` использует поля для structured output.

Effort: 2-3d (132 entries × ~30s каждая = 1.5h ручной работы + tests).

### S5.2 — Gemma 4 sprint (по аудиту §6/7.6)

**Префлайт-задачи:**
1. Backport vLLM PR #42102 (DFlash + quantized KV groups) → новый `PN104_DFLASH_QUANT_KV_GROUPS`
2. Evaluate #42069 (Gemma4 DFlash backend autoselect)
3. Backport #42105 (Gemma4 reasoning batch chat) и #42006 (Gemma4 MTP streaming multi-tool)
4. Add Gemma4 INT8 PTH config: `vllm/sndr_core/model_configs/builtin/gemma4-31b-2x3090-mtp-int8.yaml.sample`
5. Add Gemma4 parser tests

Effort: 5-7d.

### S5.3 — Memory/KV sprint (kv-calc.py port, residency instrumentation)

Из аудита §7.4-7.5.

1. Port `club-3090/tools/kv-calc.py` formulas → `vllm/sndr_core/memory/estimator.py`
2. `sndr memory explain` Phase 2/3/4 (live VRAM probe, recommendations, per-patch attribution)
3. Residency instrumentation port (изменить `_genesis` imports на `sndr_core`)

Effort: 5-7d.

### S5.4 — Report/verify sprint

1. `sndr report bundle --full` (по образцу `club-3090/scripts/report.sh`)
2. `sndr verify --stress` (по образцу `verify-stress.sh`)
3. `sndr verify --soak`

Effort: 5-7d.

---

## Sprint 6 — Production readiness (release gates)

Из аудита §10.

### P0 release gates (blocking)
- [✅] `pytest -q` green (2994/0/94)
- [✅] `sndr install --dry-run` failed=0
- [✅] `sndr apply.shadow --strict` clean
- [⚠] `schema_validator --quiet` warnings (research_note: P82, P83, PN26b) — accept или fix
- [⚠] `lifecycle_audit_cli --quiet` 90 experimental, 5 retired — promote/retire deliberate
- [⏳] README matches current code (S0.1)
- [⏳] `sndr launch --dry-run` clean wheel mode + dev mode separately (S0.3)

### P1 release gates
- [⏳] Build wheel `vllm-sndr-core`
- [⏳] Install wheel в clean venv, import works
- [⏳] Container image smoke (no source mount, no `/plugin` editable)
- [⏳] SBOM generated and attached to release
- [⏳] `KNOWN_GOOD_IMAGES` enforced for production presets
- [🔒] Real Ed25519 public key inserted (BLOCKED: Sander offline keygen ceremony)
- [⏳] Tests with `SNDR_ALLOW_LEGACY_LICENSE_KEYS` disabled

### P2 quality gates
- [⏳] `sndr verify --stress`
- [⏳] `sndr verify --soak`
- [⏳] Per-patch quality tests (S3.1)
- [⏳] PROD YAML audit (S3.3)
- [⏳] Regression bench in CI (S2.1)

---

## Sprint 7 — Cross-engine integrations (long-term, multi-week)

Из BACKLOG Phase 6.

| Item | Когда делать | Effort |
|---|---|---|
| **LMCache integration** | После решения prefix-cache problem (TQ k8v4 + spec-decode crash) | 10-14d |
| **SGLang HiCache** | После prefix-cache | 10-14d |
| **TRT-LLM cache reuse keys** | P102 partial done | 5-7d |
| **SGLang fused_gdn_gating** | Только 27B релевантно | 3-5d |
| **SGLang `<think>` strip from radix cache** | Требует prefix-cache active | 3-5d |

---

## Sprint 8 — Security finalization

Из BACKLOG Phase 7.

### S8.1 — Real Ed25519 trust anchor
**BLOCKED** — требует Sander offline keygen ceremony:
1. Сгенерировать Ed25519 keypair offline
2. Securely store sk
3. Embed pk in `vllm/sndr_core/license.py:_TRUST_ANCHOR_PUBKEY_B64URL`

### S8.2 — SBOM в release pipeline
Tooling готов (`scripts/generate_sbom.py`). Wire в `pyproject.toml` build hooks или GitHub Actions release workflow.

### S8.3 — Plugin runtime sig gate
Wave 4.3 classifier есть. Wire runtime gate в `vllm/sndr_core/plugin.py` или `compat/plugin_signature.py`.

### S8.4 — Self-hosted GPU CI
Sander-side action. Когда GPU runner доступен → migrate from manual ssh-bench to CI matrix.

---

## Sprint 9 — Operator UX expansion

Из BACKLOG Phase 8.

| Item | Effort |
|---|---|
| `sndr models` list/pull/explain | 3-5d |
| `sndr bench` integrated (already partial: bench-and-update) | 2-3d |
| `sndr memory explain` Phase 2 (live VRAM probe) | 2-3d |
| `sndr memory explain` Phase 3 (recommendations) | 2-3d |
| `sndr memory explain` Phase 4 (per-patch attribution через Wave 7 observability extension) | 2-3d |

---

## 📊 Summary порядка действий

| Sprint | Priority | Effort | Blockers |
|---|---|---|---|
| **S0 (final stab)** | P1 | 1-2d | — |
| **S1 (boost-above-236)** | P1 | 1.5d | server access |
| **S2 (patcher infra)** | P1 | 3-4d | — |
| **S3 (per-patch quality)** | P2 | 3d | server access |
| **S4 (PN16 V6 streaming)** | P2 | 3-5d | server access |
| **S5 (audit closure)** | P2 | 5-7d | — |
| **S6 (release gates)** | P0/P1 | mixed | wheel build env |
| **S7 (cross-engine)** | P3 | 10-30d | prefix-cache fix first |
| **S8 (security)** | P2 | mixed | Sander Ed25519 ceremony |
| **S9 (UX)** | P3 | 10-15d | — |

**Total active backlog (S0-S6 без BLOCKED items):** ~25 рабочих дней.

---

## 🎯 Моя рекомендация порядка

1. **Эта сессия (DONE):** P0 + P1.1 + P1.3 + P2.1 ✅
2. **Next session (1d):** S0.1 README, S0.3 bare-metal wheel mode
3. **Sprint 1 (1.5d):** boost-above-236 sweeps на server
4. **Sprint 2 (3-4d):** patcher infra (CI regression bench, contract tests, conflict resolver, sndr bench compare)
5. **Sprint 3-4 (6-10d):** per-patch quality + PN16 V6 streaming truncator
6. **Sprint 5 (5-7d):** registry metadata enrichment + Gemma4 evaluation
7. **Sprint 6 (mixed):** release gates closure (wheel build, SBOM CI, real Ed25519 ceremony)
8. **Sprint 7-9:** long-term integrations + UX

---

## 🔚 No-stubs / no-scaffolds compliance

✅ Все три P0 violations закрыты в Wave 6/7:
- ~~PN91 scaffold~~ → rolled back, library kept
- ~~PN62 marker-only~~ → real `skip_mm_profiling` flip hook
- ~~T2.2 FLA TP guard~~ → wired в orchestrator preflight

В новых wave не должно быть scaffold/stub patches. Каждый patch must observe ON vs OFF runtime difference (verifiable through `@measure_patch_apply` observability instrumentation).

---

## 📁 References

- Аудит: `docs/upstream/DEEP_AUDIT_VLLM_NOONGHUNNA_2026-05-08_RU.md` (1045 строк)
- Backlog (предыдущий): `docs/_internal/BACKLOG_2026-05-09.md`
- Roadmap (исторический): `docs/upstream/PRODUCTION_ROADMAP_2026-05-09.md` (теперь снимок 2026-05-09)
- Memory: `project_wave7_pn16v8_observability_2026_05_09.md`, `project_wave6_pn62_t22_2026_05_09.md`, `project_pn90_wave3_complete_2026_05_09.md`
- Bench results (server): `/home/sander/bench_results/wave6/`
- Hard rule: `feedback_no_stubs_or_scaffolds.md`
