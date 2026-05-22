# Upstream vLLM 38-PR audit — re-verification 2026-05-13

Source: `docs/upstream/PR38_PATCHER_REWORK_PLAN_2026-05-07.md` §4.
Re-verified live against `github.com/vllm-project/vllm` via `gh pr view` on 2026-05-13.

## Текущий статус по PR

| PR | Состояние upstream | План (2026-05-07) | Действие сейчас |
|---|---|---|---|
| 41703 | OPEN | Watch | Watch — drift риск для PN21/PN24/PN38/PN40 |
| 41763 | OPEN | Watch | Watch |
| 41896 | OPEN | Do (PN55v2) | ✅ В registry как часть PN55 unified |
| 41873 | OPEN | Do (PN82) | ✅ В registry как PN82 |
| 41747 | OPEN | Watch | Watch — может задеть P31 anchors |
| 41728 | OPEN | Watch | Watch — может задеть PN52 anchors |
| 41883 | OPEN | Watch | Watch — большой refactor |
| 41890 | OPEN | Watch | Watch |
| 41939 | OPEN | Watch | Watch |
| 41748 | OPEN | Watch | Watch |
| 41931 | OPEN | Skip | Skip |
| 41947 | OPEN | Watch | Watch — H100/NVFP4 |
| 41915 | OPEN | Watch | Watch — Blackwell |
| 41889 | **MERGED** (2026-05-07) | Skip | Skip — LoRA не PROD path |
| 41892 | OPEN | Skip | Skip — model-specific |
| 41882 | **MERGED** (2026-05-10) | Skip/Watch | Skip — NVFP4 не текущий stack |
| 41868 | **MERGED** (2026-05-08) | Watch | Watch — может пригодиться для PN77 (Ada/Blackwell) |
| 41785 | OPEN | Skip | Skip |
| 41796 | OPEN | Skip | Skip — docs only |
| 41928 | **MERGED** (2026-05-11) | Skip | Skip — KV offload не used |
| 41929 | OPEN | Skip | Skip |
| 41945 | **MERGED** (2026-05-12) | Skip | Skip |
| 41777 | OPEN | Skip | Skip |
| 41727 | **MERGED** (2026-05-11) | Skip | Skip |
| 41847 | OPEN | Skip/Watch | Skip |
| 41923 | OPEN | Skip | Skip — disagg serving не used |
| 41887 | CLOSED | Skip | Skip — revert PR |
| 41943 | **MERGED** (2026-05-08) | Skip | Skip — CI infra |
| 41910 | OPEN | Optional | Optional — Mac dev convenience |
| 41776 | OPEN | Skip | Skip |
| 41723 | OPEN | Skip | Skip |
| 41875 | OPEN | Skip | Skip |
| 41936 | OPEN | Skip | Skip |
| 41944 | OPEN | Watch | Watch — Gemma4 |
| 41905 | OPEN | Skip | Skip |
| 41755 | (already merged earlier) | Skip | Skip |
| 41769 | OPEN | Watch | Watch — Blackwell |
| 41683 | OPEN | Watch/Ignore | Ignore — huge open PR |

## Сводка

- **MERGED upstream с 2026-05-07**: 7 PR — все в категориях Skip / Watch для нашего stack. Никакие новые backport не нужны.
- **CLOSED**: 1 (revert PR).
- **OPEN**: 30 PR (из них Do — 3, Watch — 11, Skip — 16, Optional — 1).
- **Do-список не изменился**:
  - PN82 (vllm#41873): уже в `PATCH_REGISTRY` (experimental, default_on=False).
  - PN55 (vllm#41896 + #41602): unified backport уже в `PATCH_REGISTRY`.
  - P61c (club-3090#72): уже в `PATCH_REGISTRY`.

## Drift watch — что меняется при merge каждого Watch PR

Все Watch PR трогают anchors / категории, которые перекрываются с нашими патчами. План: при merge каждого — запускать `make audit-patches-prove-all` чтобы убедиться что наши anchors не сдвинулись. Если сдвинулись — re-anchor + re-bench.

| Watch PR | Наши потенциально затронутые patches |
|---|---|
| 41703 (DFlash batched verification) | PN21, PN24, PN38, PN40 |
| 41747 (router_logits refactor) | P31 |
| 41728 (scheduler prefill chunk) | PN52, anchors scheduler/* |
| 41883 (W16A16 kernel refactor) | P22, P77 |
| 41868 (CUTLASS scaled mm, MERGED) | PN77 (Ada/Blackwell roadmap) |
| 41944 (Gemma4 K=V) | future Gemma4 stack |

## Вывод

Re-audit на 2026-05-13 подтверждает, что план от 2026-05-07 был корректно применён: все три Do-PR представлены в `PATCH_REGISTRY` (PN82, PN55, P61c). Merged-upstream PRs за прошедшую неделю не открывают новых action items для нашего production stack (A5000 2x, Qwen3.6 27B/35B, hybrid GDN + TQ k8v4).

Следующая ревизия — через ~1 неделю или при triggering events: новый OPEN PR в registry watch-list переходит в MERGED, либо появляется new vLLM pin (drift).
