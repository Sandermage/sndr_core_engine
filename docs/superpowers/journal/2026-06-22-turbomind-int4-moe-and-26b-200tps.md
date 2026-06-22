# Журнал — неделя 2026-06-16…22: TurboMind int4-MoE ядро + цель «26B 200+ TPS»

**Дата закрытия:** 2026-06-22. **Ветка:** `feat/v12-sndr-platform`. **Все коммиты ЛОКАЛЬНЫЕ** (push только по явному «ok push» в приватный `sndr-dev`, НИКОГДА в public origin; Co-Authored-By строкой strip — iron rule #7).

---

## TL;DR (для следующей сессии)

1. **Ядро TurboMind int4-MoE — полностью построено и доказано** (8 коммитов, `ee35092a`…`320db075`): 3–6× vs CUDA-core `moe_wna16`, точность 0.036% vs FP16, полный MoE forward из Python через torch-extension, формат int4 подтверждён vs реального `moe_wna16`.
2. **НО для PROD-26B ядро почти бесполезно** — главная находка: **PROD-26B работает на Marlin** (`CompressedTensorsWNA16MoEMethod` + G4_08 паддинг 352→384), а **НЕ на moe_wna16**. Наши 3–6× — против пути, который PROD обходит. Ценность vs Marlin ≈ +19% (неточно на A5000), и только на int4-части (мелкой) — dense bf16 MLP доминирует.
3. **Цель «26B 200+ TPS» закрыта diffusiongemma**, НЕ ядром: diffusiongemma-26B (block-diffusion, FP8) = **200–310 TPS** (median 188, peak 282), tool-call OK, качество чистое при `denoising_steps=6`.
4. **Обычный 26B-A4B упёрт ~120-140 TPS** архитектурно (dense bf16 MLP intermediate=2112 в `ignore`, не квантуется; 4B активных).

---

## 1. Ядро TurboMind sm80_16816 int4 grouped-MoE — что и как

**Зачем начали:** 26B-A4B int4 (compressed-tensors g32) при TP=2 имеет intermediate_per_partition=352; `352 % max(64,32)=64 = 32 ≠ 0` → Marlin структурно отвергает → fallback на `moe_wna16_gemm` (CUDA-core, memory-bound, медленный). TurboMind sm80_16816 — единственное tensor-core int4-MoE ядро, толерантное к K=352 (16×8×32 MMA) + g32, CUTLASS-free.

**Вендоринг:** `third_party/tm_int4_moe/` — подмножество TurboMind (lmdeploy `src/turbomind/...`, Apache-2.0). Build-recipe: `third_party/tm_int4_moe/torch_ext/build_probe.sh`. Флаги: `-arch=sm_86 -std=c++17 -DENABLE_BF16 -DFMT_HEADER_ONLY --expt-relaxed-constexpr --extended-lambda -Xcompiler -fPIC -include cuda_fp16.h -include cuda_bf16.h -I.`.

**Фаза 0** (`ee35092a` и ранее): libtm_int4_moe.a, 3 ядра sm80_16816_{4,8,16} компилируются на SM86.

**Фаза 1 — корректность** (`ee35092a`): собрали `test_gemm_v2` (testbed_v3 + cuBLAS reference). **Ключевой баг найден дисциплиной «изучить→разложить»**: «No feasible kernel» → file-probe (stderr теряется под `abort()`!) показал, что sm80-ядра РЕГИСТРИРУЮТСЯ (252), а отвергаются на `gate=order` (order_b mismatch). **Root cause:** testbed не звал `LinearWeight::set_grouped(true)` → dense u4-конвертер вместо grouped. Фикс → **reldiff vs FP16 = 0.000356** (ядро численно верно).

**Фаза 2 микробенч** (`bcb83549`): cudaEvent-тайминг grouped-MoE на shape Gemma-26B (E=128, top_k=8, hidden=2816, inter=704, g32). TurboMind int4 (w1w3+w2) vs vLLM moe_wna16 full:
| tokens | M | TurboMind | moe_wna16 | speedup |
|---|---|---|---|---|
| 1 (decode) | 8 | 57.2µs | 187.4µs | **3.3×** |
| 16 | 128 | 506µs | 2354µs | **4.65×** |
| 64 | 512 | 702µs | 4248µs | **6.05×** |

w1w3 GEMM на M=128 = **~737 GB/s ≈ 96% пиковой HBM A5000** (memory-bound оптимум); автотюн → ~801 GB/s.

**Фаза 2.2 — torch-extension** (`266282a8`, `520ac2a2`): `torch_ext/tm_moe_op.cu` — кастом-класс `TmInt4MoE`. Решённые проблемы сборки: `-fPIC`, `-lcuda` (driver stub), `is_python_module=False`, объекты через `extra_ldflags` (нет `extra_objects` в этом torch), персистентный never-popped ContextGuard (как `main()`). **GEMM_err=0** (op = x@dequant идеально).

**Фаза 2.1 fix квантайзера** (`fb0d676e`): `quantization.cu:426` клампил asymmetric zero-point в `[0,max_q]` → коллапс all-positive int4-групп. Убрал кламп (`zero_ = -round(minval/scale)`); zero хранится как half, используется только через fused `-zero*scale` FMA. all-positive 0.586→**0.007**.

**Полный MoE forward** (`ffa6cca8`): два TmInt4MoE (w13 + w2 через identity-gather) + SwiGLU + combine в torch → **reldiff_vs_dq_ref = 0.00088**.

**G4_85 monkey-patch** (`812a7f10`, `320db075`): `sndr/engines/vllm/patches/moe/g4_85_tm_int4_moe_kernel.py`. **Формат int4 ПОДТВЕРЖДЁН** (`torch_ext/test_vs_vllm.py`) vs реального `fused_experts_impl`: декод = **`(nibble−8)·scale`** (unsigned, zero-point 8) → reldiff 0.051; signed two's-complement → 1.32. 26B симметричный → риск #1 (zero-point) снят. Остаток 0.051 = dequant→requant; lossless-путь = прямой репак (zero=8, scale=scale, без requant) — НЕ сделан.

---

## 2. ГЛАВНАЯ НАХОДКА: PROD-26B на Marlin, не moe_wna16

INFO-логи живого 26B (`start_gemma4_26b_0231.sh`):
```
compressed_tensors_moe.py:146  Using CompressedTensorsWNA16MoEMethod
compressed_tensors_wNa16.py:112  Using MarlinLinearKernel
```
`GENESIS_ENABLE_G4_08_MARLIN_KDIM_PAD=1` паддит intermediate 352→384 (384%64=0) → Marlin eligible. **moe_wna16 не используется.** Значит:
- 3–6× ядра — vs пути, который PROD обходит.
- PROD-релевантно: TurboMind vs Marlin-padded ≈ +19% (arXiv A100, на A5000 не мерили).
- Ядро влияет только на int4-MoE (мелкую) часть; dense bf16 MLP (intermediate=2112, в `ignore`, не квантуется, ~35MB/токен) — якорь. → ~+5% TPOT. Не путь к 200.

G4_85 при желании измерить vs Marlin: перенацелить патч на `CompressedTensorsWNA16MoEMethod.apply` (сейчас таргетит `MoeWNA16Method`), задеплоить vendored-дерево в `$GENESIS_TM_INT4_MOE_DIR`, применить в TP-воркерах (sitecustomize или sndr_core overlay), `GENESIS_G4_85_VALIDATE=1` → реальный reldiff, потом A/B.

---

## 3. Живое тестирование моделей (рига sander@192.168.1.10, 2×A5000)

| Модель | TPS | tool-call | Качество | 200+? |
|---|---|---|---|---|
| 26B-A4B (AWQ-4bit) baseline | 108, TPOT 9.8ms, TTFT 76ms | ✅ `get_weather{"city":"Tokyo"}` | хорошее | ❌ |
| 26B-A4B + `--enable-expert-parallel` | 122 (+13%), TPOT 8.69ms | ✅ | хорошее | ❌ упёрт ~120-140 |
| **diffusiongemma-26B** (FP8 block-diffusion) | **200–310** (median 188, peak 282, denoising=6) | ✅ | чистое | ✅ **>200** |

**diffusiongemma config finicky** (`/tmp/diff_gen_fast.json` mount): `max_denoising_steps=6` → 200-310 чисто; `=7` → срыв (повторы «atmosphere atmosphere is is», 29 TPS); `=8` → чисто но 91 TPS. **6 = рабочая точка** (восстановлено). min=2 TPS-выбросы = ранние стопы (короткие ответы), не медленная генерация. Дальнейшее качество без потери >200 = многопараметрический поиск (entropy_bound=0.1, t_max=0.8, t_min=0.4, stability_threshold=1).

**EP не был включён в start_gemma4_26b_0231.sh** — добавление `--enable-expert-parallel` дало +13% (стоит закрепить в PROD-конфиге 26B).

---

## 4. Состояние рига на конец сессии

- **diffusiongemma поднята** (контейнер `vllm-diffusiongemma`, порт 8102, denoising=6).
- 26B-тест (`vllm-gemma4-26b-a4b-test`) и 35B PROD — ОПУЩЕНЫ. 35B PROD НЕ восстанавливал (правило: не восстанавливать PROD без явной команды).
- GPU: при тесте свободны были оба (0%).

---

## 5. Артефакты (пути для следующей сессии)

- **Ядро/вендоринг:** `third_party/tm_int4_moe/` — `torch_ext/{tm_moe_op.cu, build_ext.py, build_probe.sh, test_vs_vllm.py}`, `bench/wna16_compare.py`, `README.md`, `src/turbomind/...`.
- **Патч:** `sndr/engines/vllm/patches/moe/g4_85_tm_int4_moe_kernel.py` (draft, self-validating; перенацелить на CompressedTensorsWNA16MoEMethod для A/B vs Marlin).
- **Детектор:** `sndr/engines/vllm/patches/moe/g4_84_moe_geometry_advisor.py` + тест `tests/unit/integrations/moe/test_g4_84_moe_geometry_advisor.py`.
- **Спека:** `docs/superpowers/specs/2026-06-22-turbomind-int4-moe-port.md`.
- **Этот журнал:** `docs/superpowers/journal/2026-06-22-turbomind-int4-moe-and-26b-200tps.md`.
- **Деплой на риге:** vendored-дерево с пребилт-объектами лежит в `/tmp/tb/tm_int4_moe` (эфемерно). Конфиг diffusiongemma: `/tmp/diff_gen_fast.json`. Старт-скрипты: `~/start_gemma4_26b_0231.sh`, `~/start_diffusiongemma_fast.sh`.

**Коммиты (локальные, ветка feat/v12-sndr-platform):** `ee35092a` `bcb83549` `266282a8` `520ac2a2` `fb0d676e` `ffa6cca8` `812a7f10` `320db075`.

---

## 6. Что дальше (приоритеты)

1. **Для «26B 200+» → diffusiongemma** — прогнать по полной (chat-matrix по видам чата, tool-call надёжность, concurrency), подтвердить устойчивость >200; при желании дотюнить качество не теряя 200.
2. **Закрепить EP** в 26B-A4B PROD-конфиге (+13%, бесплатно).
3. **Ядро** — опционально: A/B vs Marlin (перенацелить G4_85). Если +19% на A5000 подтвердится и точность lossless-репака OK — внедрять; иначе оставить как валидированную разработку для других int4-MoE моделей (где Marlin реально недоступен).
4. **Восстановить 35B PROD** по команде пользователя.
