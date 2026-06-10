# 2026-06-10 — PN369 cell A/B: нулевой эффект, подозрение на тихий no-op

## Прогоны (quick bench @1024, temp=0.7 — random path где relaxed активен)

| Конфиг | TPOT | wall_TPS | quality |
|---|---|---|---|
| PN369 cell-1 (topk=4, delta=0.2) | 4.628 | 211.26 | 5/5 |
| PN369 cell-2 (topk=16, delta=0.5) | 4.613 | 211.69 | 5/5 |
| PN369 OFF (тот же restart-класс) | 4.613 | 212.20 | — |
| Утренний well-warmed baseline | 4.501 | 216.62 | 5/5 |

## Вывод

Все три свежерестартовых прогона ИДЕНТИЧНЫ (4.61-4.63 / 211-212) —
разница с утренним baseline = restart-state, не PN369. Эффект
relaxed acceptance = НОЛЬ в обе стороны при обоих настройках.

Идентичность консервативной и агрессивной ячеек — красный флаг
bug class 3 (тихий no-op): либо relaxed-окно после top-p почти
никогда не срабатывает сверх строгого правила, либо маска/tail-
extension не стреляют вовсе (gate-условие, баг маски).

## Что сделано правильно

- Gates G2/G3-lite прошли (точность 391, tools OK) — greedy строгий
  как задумано, качество не тронуто.
- P71 v7.43 (threading) применился чисто через pristine-restore
  (обход bake-pitfall v7.42).
- Откат = env=0, текст bit-identical — PROD на baseline.

## Resume-путь (PN369 v2)

1. ПЕРВЫМ ДЕЛОМ G5-телеметрия: счётчик срабатываний relaxed-маски
   (лог раз в N шагов / Prometheus). Без подтверждения «маска вообще
   стреляет» дальнейшая оптимизация бессмысленна.
2. Если стреляет но эффект мал: профилировать цену torch.topk по
   словарю 151k/step; альтернатива — delta-only правило через max
   (O(vocab) max вместо topk-sort) или маска внутри существующего
   ядра из уже загруженных probs.
3. Если НЕ стреляет: дебаг gate-цепочки block-verify tail
   (synthetic_mode? draft_probs availability? shapes?).

## Косметика

PN369 drift-marker список содержит собственный маркер '[Genesis
PN369' → поздние процессы бута логируют пугающее "upstream marker
detected — patch obsolete, skip" вместо "already applied". Поправить
на отдельную idempotency-ветку.
