# PN96 A/B bench plan на 35B PROD

> ⚠️ **DO NOT RUN WITHOUT OPERATOR APPROVAL.** This plan stops and
> restarts the live 35B PROD container; expect ~45 minutes of downtime.
> Operator must give an explicit go-ahead before any phase starts.

Дата: 2026-05-12 (план обновлён под v11 canonical tooling, Этап 7)
Status: ready to execute (S5.1, требует ~45 минут PROD downtime — gated на operator availability)
Trigger: после получения подтверждения от Sander запустить.

## Зачем

PN96 (Persistent Marlin MoE workspace) был включён в 35B PROD config как
часть Wave 9 dev209 pin bump для восстановления -2.82% TPS regression.
Текущий статус: **ON по умолчанию**, но **без A/B бенча на live 35B** мы
не знаем реального contribution.

Audit P5-1 закрытие требует:

1. Зафиксировать current 35B PROD TPS с PN96=ON (baseline).
2. Disable PN96 → restart → re-bench (delta measurement).
3. Re-enable PN96 → restart → confirm restore (regression guard).
4. Записать результат в `tests/integration/baselines/35b_v11_wave9.json`
   если delta устойчив (Welch p < 0.05).

## Pre-flight

1. **Подтверждение оператора.** 45 минут PROD downtime — нужен явный
   go-ahead в чате.
2. **Manual snapshot** (Этап 7 — `snapshot_pre_arm.sh` retired in v11):
   ```bash
   # Capture state before any change so rollback is possible.
   mkdir -p /tmp/pn96_snapshot && cd /tmp/pn96_snapshot
   docker inspect vllm-35b-prod > docker_inspect.json
   docker logs --tail 500 vllm-35b-prod > docker_logs.txt
   nvidia-smi --query-gpu=memory.used,memory.total,temperature.gpu,power.draw \
       --format=csv > gpu_baseline.csv
   (cd "$GENESIS_REPO" && git rev-parse HEAD && git status --short) > repo_state.txt
   ```
3. **Текущий PROD container status:** `docker ps | grep vllm-35b-prod`.

## Execution sequence

Все команды используют **v11 canonical tooling**: `sndr launch <preset>`
вместо удалённых launch-script'ов, существующий `tools/soak.sh` вместо
несуществующего `tools/run_stress.py`.

```bash
# --- Phase A: baseline (PN96 ON) ---
# PROD already running with PN96=1; we just measure.
make integration-35b HOST=http://127.0.0.1:8000 > /tmp/pn96_baseline.txt
python3 tools/genesis_bench_suite.py --quick \
    --host 127.0.0.1 --port 8000 \
    --output /tmp/pn96_baseline_bench.json
# Soak: replace removed run_stress.py with existing soak.sh (5-min window).
HOST=http://127.0.0.1:8000 MODEL=qwen3.6-35b-a3b DURATION_S=300 \
    bash tools/soak.sh > /tmp/pn96_baseline_soak.txt

# --- Phase B: disable PN96, restart ---
docker exec vllm-35b-prod env | grep PN96 || echo "checking env baseline"
docker stop vllm-35b-prod
# v11: re-launch via `sndr launch`, passing the disable flag through env.
GENESIS_DISABLE_PN96=1 python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod
sleep 240  # cold compile ~3-4 min
curl -s http://127.0.0.1:8000/v1/models \
    -H "Authorization: Bearer genesis-local" \
    || (echo "boot failed"; exit 1)

# --- Phase C: measure without PN96 ---
make integration-35b HOST=http://127.0.0.1:8000 > /tmp/pn96_disabled.txt
python3 tools/genesis_bench_suite.py --quick \
    --host 127.0.0.1 --port 8000 \
    --output /tmp/pn96_disabled_bench.json
HOST=http://127.0.0.1:8000 MODEL=qwen3.6-35b-a3b DURATION_S=300 \
    bash tools/soak.sh > /tmp/pn96_disabled_soak.txt

# --- Phase D: restore PN96, verify ---
docker stop vllm-35b-prod
python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod
sleep 240
curl -s http://127.0.0.1:8000/v1/models \
    -H "Authorization: Bearer genesis-local"
python3 tools/genesis_bench_suite.py --quick \
    --host 127.0.0.1 --port 8000 \
    --output /tmp/pn96_restored_bench.json

# --- Phase E: A/B analysis ---
python3 -m vllm.sndr_core.cli bench-compare \
    /tmp/pn96_baseline_bench.json \
    /tmp/pn96_disabled_bench.json \
    --output /tmp/pn96_ab_report.md
echo "--- baseline vs disabled ---"
cat /tmp/pn96_ab_report.md
```

> Each `docker stop` / `sndr launch` step is destructive against PROD —
> review and confirm interactively. The operator is expected to step
> through phases one at a time, not run the block end-to-end.

## Verdict criteria

- **PN96 keeps ON (current):** disabled TPS падает на >1.5% (Welch
  p<0.05) ИЛИ stability CV растёт >25%.
- **PN96 retire candidate:** disabled TPS равен или выше baseline
  (negligible delta).
- **Inconclusive:** TPS delta < 1% и p > 0.10 — оставить ON по
  умолчанию (защитный default), не считать contribution validated.

## Записать результат

- `tests/integration/baselines/35b_v11_wave9.json` — если ratio устойчив,
  update `pn96_contribution_pct` field.
- `docs/_internal/PN96_AB_BENCH_RESULTS_2026-05-12_RU.md` — результат в md.
- Update `docs/PATCHES.md` PN96 row с empirical delta.

## Risk + rollback

- Любая phase падает → restart 35B PROD без override
  (`python3 -m vllm.sndr_core.cli launch a5000-2x-35b-prod`),
  confirm via `/v1/models`, write rollback note в `/tmp/pn96_snapshot/`.
- Если cold compile cache повреждён после restart —
  `rm -rf /root/.triton/cache/* ; rm -rf ~/.cache/genesis_vllm/*`
  внутри контейнера, повторить boot.
- Если `sndr launch` не запускается (registry corrupt и пр.) —
  fallback: `docker run` с image и env из snapshot'а:
  ```bash
  docker run -d --name vllm-35b-prod --gpus all \
      -v "$MODELS_DIR:/models:ro" \
      $(jq -r '.[0].Config.Env[] | "-e " + .' /tmp/pn96_snapshot/docker_inspect.json) \
      vllm/vllm-openai:nightly serve ...  # capture full args from snapshot
  ```
