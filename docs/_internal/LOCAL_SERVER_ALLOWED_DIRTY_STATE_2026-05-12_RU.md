# LOCAL ↔ SERVER allowed dirty state — three-tier policy

**Дата:** 2026-05-12
**Owner:** sandermage
**Контекст:** PROJECT_ROADMAP_V2 §6.3 quality gate #6 + risk registry R6/R11

---

## 0. Зачем эта политика

Раньше в roadmap'е стоял безразмерный "≤ N tolerated dirty files" —
без определения N и без объяснения какие файлы считать ОК. Это
делало "convergence" gate неисполнимым: один раз операторская заметка
в логе сломала бы release.

Эта политика разделяет convergence на **3 уровня**, каждый со своими
правилами по dirty state. Любая релиз-проверка проходит **только в
release-tier**; повседневная работа в dev/audit tier'ах разрешает
заведомо disposable state.

---

## 1. Три уровня (tiers)

| Tier | Когда применяется | Tolerance | Gating CLI |
|---|---|---|---|
| **dev** | Активная работа над фичей; ежедневный workflow | Любые non-tracked files; tracked modified files OK если не в `vllm/sndr_core/` | none |
| **audit** | Перед каждым commit / per-PR audit | Untracked OK только в `snapshots/`, `_archive/`, `*.log`. Tracked modified files должны быть intentional | `make audit` clean |
| **release** | Перед merge to `main` + перед V2 acceptance | **Worktree fully clean** на ОБОИХ хостах (local + server) ИЛИ explicit allowlist | `make evidence` + `git status` exact-match |

---

## 2. Per-tier allowlist (что разрешено)

### 2.1 dev tier

Разрешено всё что **не блокирует следующую stage**. Конкретно:

- Любые untracked файлы (включая `*.log`, scratch py-скрипты, draft md в
  `docs/_internal/`).
- Modified files в `tests/`, `docs/_internal/`, `tools/` — не блокируют.
- Untracked patch drafts в `plugins/community/` (Phase 5+).

**Запрет (даже на dev):**

- Modified files в `vllm/sndr_core/` без context — должны быть либо
  staged for commit либо reverted.
- Untracked `.env*` файлы — security risk; добавляются в `.gitignore`
  или удаляются.

### 2.2 audit tier (per-PR)

Расширяет dev запреты. Дополнительно требуется:

- `make audit` aggregate clean (legacy-imports, public-paths,
  upstream-offline, doc-sync — все green).
- Untracked файлы only в explicit allowlist:
  - `snapshots/` (snapshot reports)
  - `_archive/` (legacy quarantine)
  - `*.log` в project root (operator scratch logs, gitignored)
  - `node_modules/`, `.venv/`, `__pycache__/` (build artifacts, gitignored)

**Untracked outside allowlist → audit fails** with explicit listing.

### 2.3 release tier (per-release)

Самый строгий gate. Worktree должен быть **либо полностью clean** либо
содержать только **repo-local** файлы из release allowlist. Host-level
артефакты (вне worktree) проверяются отдельно — см. §2.4.

| Path pattern (repo-local) | Reason |
|---|---|
| `snapshots/<ISO>/` | Acceptable: snapshot artefact frozen at release commit |
| `evidence/patch_proof/*.json` | Acceptable: patch-proof gate output |

**Modified tracked files → release blocked.** Без исключений.

### 2.4 Host artifacts (allowed outside worktree)

Эти пути **не участвуют** в git dirty-state check (их не видно в
`git status --porcelain`), но release pipeline проверяет их отдельно
через `make evidence` / report bundle:

| Path pattern (host-level) | Reason |
|---|---|
| `~/.sndr/bench-results/*.json` | Bench artefacts on this host (Phase 6 methodology contract) |
| `~/.sndr/patches.lock` | Operator-side patch lockfile (community SDK) |
| `~/.cache/sndr/*` | Cache; ignored on every tier |
| `${cache_root}/triton-cache-*/` | vLLM triton cache; ignored on every tier |
| `${cache_root}/compile-cache-*/` | vLLM compile cache; ignored on every tier |

**Rationale:** git dirty-state policy и host runtime artifact policy —
two разных класса. Смешивать их в одном allowlist делает policy
технически неточной + усложняет `check_dirty_state.py`. Release report
bundle ссылается на host artifacts через explicit paths, а не через
git state.

Дополнительно:

- `make evidence` succeeds on local AND server (entry recorded in
  `ROADMAP_EVIDENCE_LEDGER_*.md` for both hosts).
- `git rev-parse HEAD` matches between local and server (sync verified).
- Pytest baseline matches evidence ledger latest entry (0 regressions).

---

## 3. CLI enforcement

Single source of truth: **`tools/policies/dirty_state_allowlist.yaml`**
(YAML, tracked). This markdown file documents the policy in human form;
the YAML is what the script consumes. Both must stay in sync — §6
describes the sync test.

```bash
# Dev tier — informational; pytest baseline doesn't change
make audit-dirty-state-dev          # python3 scripts/check_dirty_state.py --tier dev

# Audit tier (gated by `make audit`)
make audit-dirty-state-audit        # exit 0 if matches; exit 1 otherwise with listing

# Release tier (gated by release pipeline)
make audit-dirty-state-release      # strictest — only snapshot/proof allowed
scripts/check_dirty_state.py --tier release --host local --json   # machine-readable
scripts/check_dirty_state.py --tier release --host server --json
# both must exit 0
```

The script:

- loads patterns from `tools/policies/dirty_state_allowlist.yaml`;
- runs `git status --porcelain`;
- reports `accepted / rejected` counts + reasons;
- exits 0 (pass) / 1 (reject) / 2 (policy or git error);
- `--json` mode emits a stable shape for evidence-ledger ingestion.

`release_allowlist.txt` is NOT a tracked file — earlier versions of this
doc mentioned that name. The current implementation reads the YAML
directly via Python, no temp text file needed. If a future bash-only
backend is added, it would materialize `/tmp/sndr-release-allowlist.txt`
at gate time from the same YAML.

---

## 4. Drift between local and server

Per R6: local/server divergence can creep in via operator edits on one
host that don't sync to the other. Release tier check verifies:

1. `git rev-parse HEAD` identical on both hosts.
2. `git status --porcelain | grep -v -f release_allowlist.txt` is empty
   on both hosts.
3. Pytest result count matches between hosts (per evidence ledger).

If any of (1)/(2)/(3) fails → release blocked until reconciled.

---

## 5. Safe sync recipe (operator)

`rsync --delete` is destructive — без явного pre-flight он может стереть
server-only артефакты, новые tracked файлы другого агента или результаты
проверок. Поэтому recipe всегда выполняется в 4 шага: snapshot → dry-run
→ manual review → real sync. Никаких "одной командой".

```bash
# Step 1 — Server snapshot BEFORE sync.
# Surfaces server-only state that would be overwritten.
ssh server 'cd /path/to/genesis-vllm-patches && \
  git status --porcelain && \
  git diff --stat && \
  git rev-parse --short HEAD && \
  git log --oneline -5'

# Step 2 — Dry-run rsync (note the `n` in -avhn). NO destructive change.
# Operator must READ output before proceeding.
rsync -avhn --delete --exclude='.git' \
  /Users/sander/Documents/Visual\ Studio\ Code/genesis-vllm-patches/ \
  server:/path/to/genesis-vllm-patches/

# Step 3 — Manual review. If dry-run shows files being deleted on server
# that are NOT in local (server-only unique work), STOP. Copy them back,
# commit them, or archive them explicitly. Do not auto-proceed.

# Step 4 — Real sync (only if Step 3 review passed).
rsync -avh --delete --exclude='.git' \
  /Users/sander/Documents/Visual\ Studio\ Code/genesis-vllm-patches/ \
  server:/path/to/genesis-vllm-patches/

# Step 5 — Verify on server. Capture FULL log, not just tail.
# `tail -3` alone hides the actual failure when pytest breaks; the ledger
# needs the full log to diagnose without re-running.
ssh server 'cd /path/to/genesis-vllm-patches && \
  mkdir -p /tmp/sndr-evidence && \
  git status --porcelain > /tmp/sndr-evidence/git_status_after_sync.txt && \
  python3 -m pytest tests/ -q --ignore=tests/integration \
    2>&1 | tee /tmp/sndr-evidence/pytest_after_sync.log && \
  echo "--- tail ---" && tail -20 /tmp/sndr-evidence/pytest_after_sync.log'

# Copy full log back to local for evidence ledger inclusion:
scp server:/tmp/sndr-evidence/pytest_after_sync.log \
    /tmp/sndr-evidence/server_pytest_after_sync.log
```

**Evidence ledger entry shape** for sync events (per §5 sync events):

```yaml
- host: local + server
- command: <verbatim from Step 1-5>
- full_log_paths:
    local:  /tmp/sndr-evidence/pytest_after_sync.log
    server: /tmp/sndr-evidence/server_pytest_after_sync.log
- excerpt: "<last 20 lines>"
- exit_code: <int>
- git_rev_local + git_rev_server matched: yes|no
- decision: accept | re-verify | fix | drop
```

Old log files in `/tmp/sndr-evidence/` should be moved to a per-session
archive before each new sync — they are NOT git-tracked.

**Blocking rule:** if Step 1 shows server has uncommitted **tracked**
changes (modified files in `vllm/sndr_core/` или другая critical
path), sync is **blocked** until those changes are either copied
back to local, committed on server, or explicitly archived. Никаких
implicit overwrites.

Each successful sync recorded в evidence ledger как `convergence-check`
entry с full Step 1 output, Step 2 file count summary, Step 5 pytest
result.

---

## 6. Зачем именно три уровня

Originally one threshold ("≤N tolerated") пытался обслуживать сразу два
разных workflow:

- ежедневная работа (нужна свобода — много scratch файлов)
- release readiness (нужно zero ambiguity)

Один порог получился либо слишком строгий (блокирует daily dev), либо
слишком вольный (release выходит с drift). Три tier'а решают: каждый
gate настроен под свою цель. Audit tier — компромиссный, потому что
PR review должен быть быстрым но не пропускать критичное.

---

## 7. Связи

- Mitigates: R6 (local/server divergence), R11 (convergence ambiguity)
  из PROJECT_ROADMAP_V2 §7.2.
- Referenced by: PROJECT_ROADMAP_V2 §6.3 gate #6 (extended quality
  gates).
- Implements: proposals §4 critique ("define N for convergence").
