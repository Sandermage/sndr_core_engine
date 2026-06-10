# 2026-06-10 дневная сессия — ledger имплементаций и честных отказов

## SHIPPED и живо на PROD

1. **Tool-call parser** (`--tool-call-parser qwen3_xml --enable-auto-tool-choice`):
   агентские tool_calls парсятся ВПЕРВЫЕ на этом деплое. Валидировано:
   `get_weather(city=Odessa)` корректно структурирован. До этого — FAIL
   (никакого парсера в launcher).
2. **PN367** (vendor #45076): clamp негативной оценки cudagraph-памяти,
   2/2 sub-patches, защита KV-бюджета 24GB карт.
3. **PN79 re-anchor** (K.2): 18 якорей на новый pin, закоммичен —
   но ЗАПАРКОВАН (см. ниже).

## Протестировано с полной отдачей — отказ с доказательствами

4. **PN79 enable**: применился 18/18, точность OK, но первый 8K chunked
   prefill → CUDA IMA → engine death. In-place ветка chunk_delta_h
   (stride/state_idx math) — kernel-level баг. Реверт чист (8K стресс
   проходит). Resume-путь в docstring.
5. **Custom allreduce** (research #1, обещал +5-12% TPOT): VllmWorker-1
   умирает при init. P2P через PHB host bridge нестабилен на практике
   (can_device_access_peer=True врёт о работоспособности). Это и есть
   причина исторического --disable-custom-all-reduce. Закрыто навсегда
   для этой платформы.

## Re-triage до этого (утренний deep-study, 4 агента)

- Pin реально от 2026-06-08 (не 05-15) — #44700, #40172 уже в pin.
- #43887 (−5-9% TPOT) — на ~80% уже покрыт нашим P67b.
- Prefix caching выключен НЕ случайно (P83: −30%), но блокеры в новом
  pin сняты — эксперимент с #44986 остаётся стратегическим.

## Research bank — очередь реальных улучшений (build order)

1. **Relaxed acceptance для MTP** (TRT-LLM `relaxed_topk/delta` семантика):
   ГЛАВНЫЙ честный рычаг — accept-rate на прозе (191→215+ TPS, +8-15%).
   Pin имеет только strict greedy/random rejection. Lossy → нужны
   quality-гейты (GSM8K + tool-call suite). Усилие M. СЛЕДУЮЩАЯ СЕССИЯ.
2. **exp2 расширение на Qwen GDN** (PN354): USE_EXP2 ветка УЖЕ в
   chunk_delta_h нашего pin (KDA-only) — chunk.py просто не передаёт
   флаг + 3 exp-сайта (chunk_o ×2, kkt ×1) + RCP_LN2 фолд. +1.5-3% TTFT.
   Усилие M, риск numerics — нужна GSM8K валидация.
3. **MoE config tune для E=256,N=512 на A5000**: в pin НЕТ sm86-конфигов
   (только H100/H200/B200). Сначала верифицировать что Triton fused_moe
   путь вообще активен (может быть Marlin → void). benchmark_moe.py
   на сервере → JSON overlay. Усилие S после верификации.
4. **SGLang #26856/#26857 gate-sigmoid-mul fusion**: qwen3_next.py:318
   eager sigmoid на 40 слоях. +0.5-1.5% TPOT. Усилие S.
5. PN355 warmup-diff vs наша PN126-130 семья (first-request TTFT).
6. SGLang #26924 overlap Mamba verify-update c draft extend (M/L).
7. GDN APC (#26807+#44986+#43650 бандл) — стратегический warm-TTFT.

## Состояние PROD (конец сессии)

35B-balanced: UP, stable. wall_TPS @1024 = 215.64 (норм. полоса
209-217), TPOT 4.52, 8K prefill OK, tool-calls работают, quality 5/5.
K=3, 280K ctx, CA off, PN79/PN352/PN365 текст чист. Уроки про
docker start env-гонку дважды подтверждены и записаны.

## Урок сессии (большой)

Все S-effort рычаги на этом стеке либо уже взяты (P67b, #44700,
#40172 в pin), либо не работают на платформе (CA/PHB, FULL graphs,
probabilistic draft). Дальнейший рост = M-effort инженерия:
relaxed acceptance (прозовый accept-rate) + exp2 (prefill) + APC
бандл (warm-TTFT). Math-контент УЖЕ декодирует 250-253 TPS — цель
250+ на mixed упирается в accept-rate, и рычаг №1 бьёт ровно туда.
