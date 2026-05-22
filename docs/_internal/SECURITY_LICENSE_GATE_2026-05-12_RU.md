# Security + license gate design

**Дата:** 2026-05-12
**Owner:** sandermage
**Source:** PROJECT_ROADMAP_V2_REVIEW_NOTES §P1.3
**Status:** draft (architectural boundary only; full license server out of MVP scope)

---

## 0. Зачем сейчас (а не "когда private engine появится")

Если security/license boundary заложить **после** того как private engine
появится, придется ломать public API, переучивать пользователей и менять
inst alleruction. Если заложить **сейчас**, до private engine, то:

- public core остается работающим без license server;
- private engine подключается как optional plugin без перекройки core;
- pub-key верификация существует, но никогда не требуется для public flow;
- community уже знает где границы.

Этот документ описывает **boundary + CLI surface + invariants**, а не
конкретный license server.

---

## 1. Boundary contract

Public/private split:

| Layer | Visibility | License-dependent? |
|---|---|---|
| `vllm/sndr_core/*` | public | NEVER. Должно работать без license. |
| `vllm/sndr_core/community/*` | public | NEVER. Community patches manifest. |
| `vllm/sndr_engine/*` (planned) | private (paid) | YES. Optional discovery от core. |
| `plugins/community/*` | public | NEVER. Patches от community. |
| `plugins/sndr_pro/*` (planned) | private (paid) | YES. Premium patches set. |

**Critical invariants:**

1. **Public core никогда не делает network call к license server.**
   Любой network call за лицензией — только через `vllm.sndr_engine`
   и только если оператор явно его подключил.
2. **Public key для верификации лицензий может быть в core** (read-only,
   используется только для проверки подписи offline license file).
3. **Private key НИКОГДА не в repo.** Хранится оператором отдельно
   (HSM или offline ceremony machine).
4. **Offline activation supported.** License file подписан pub-key,
   `sndr license verify` работает без сети.
5. **No telemetry by default.** Никакой "phone home" в core. Telemetry —
   только opt-in через explicit `sndr telemetry enable` (которой
   пока вообще нет — это будущий extension).

---

## 2. CLI surface

```bash
# License status (works even without license file — reports "unlicensed core")
sndr license status                              # human-readable
sndr license status --json                       # for tooling

# License verification (offline; uses bundled pub-key)
sndr license verify --file ~/.sndr/license.lic --offline

# License import (does NOT trigger network; just copies + validates signature)
sndr license import ~/.sndr/license.lic

# Report bundle redaction (security-sensitive paths/tokens/IPs)
sndr report bundle --redact --dry-run            # show what would be redacted
sndr report bundle --redact > report.tar.gz      # produce redacted bundle

# Security scan (release pipeline)
python3 scripts/security_scan.py --public-release
# Checks: no secrets in tree, no /home/sander, no private IPs,
# no AWS/GCP keys, no SSH private keys, .env files gitignored, etc.
```

**Status output example (unlicensed core):**

```
sndr license status
  Core: public (unlicensed)
  Engine (private): not detected
  Premium patches: none
  Capabilities available: all public-core features
```

**Status output example (with engine):**

```
sndr license status
  Core: public (unlicensed)
  Engine (private): vllm/sndr_engine v1.2.0
  License: ~/.sndr/license.lic
    Subject: sandermage
    Tier: pro
    Expires: 2027-05-12 (365 days)
    Signature: valid (pub-key match)
    Verified: offline
  Premium patches: 12 enabled
```

---

## 3. Release pipeline checks

`make audit-security` (new target, Phase 7):

```bash
make audit-security
# Runs in sequence:
#   1. python3 scripts/security_scan.py --public-release
#   2. rg -n "/home/sander|/Users/sander" vllm/ scripts/ tests/  # zero hits
#   3. rg -n "\\b\\d+\\.\\d+\\.\\d+\\.\\d+\\b" docs/ --glob '!_internal/*' --glob '!upstream/*'  # private IPs
#   4. grep -r "BEGIN RSA PRIVATE\|BEGIN OPENSSH PRIVATE" .  # zero hits
#   5. find . -name ".env*" -not -path "*/node_modules/*" -not -path "*/_archive/*"  # zero hits
#   6. python3 scripts/sbom_generate.py --strict  # SBOM + constraints regenerated
```

If any check fails → `make audit-security` exits non-zero → release blocked.

---

## 4. SBOM + constraints

`scripts/sbom_generate.py` produces (on every release):

- `release/SBOM.spdx.json` — SPDX-format software bill of materials
- `release/constraints.txt` — exact pinned dependency versions
- `release/security_attestation.json` — links scan results to commit SHA

These artifacts are part of the release tarball. Operators can verify
the supply chain without trusting the build server.

---

## 5. Installer guardrails

Forbidden installer patterns (audited by `audit-public-paths`):

| Pattern | Why forbidden |
|---|---|
| `curl ... \| sh` | Pipes remote code through shell — un-auditable |
| `wget ... && bash` | Same risk |
| `eval "$(curl ...)"` | Same risk |
| `sudo` без explicit user prompt | Privilege escalation must be explicit |
| `chmod 777` | Over-broad permissions |
| modifying `/etc/*` без `--system-changes` flag | System-level changes require explicit consent |

Installer must always:

1. Download artifact, verify signature, THEN execute.
2. Print every `sudo` action with reason before running.
3. Be re-runnable (idempotent).
4. Have `--dry-run` mode showing every system call.

---

## 6. What this gate does NOT do (out of scope)

- license server implementation (deferred until private engine actually
  ships).
- license issuance ceremony / key generation procedure (separate
  operator runbook).
- premium patches gating mechanism (deferred; will live in
  `vllm/sndr_engine/__init__.py` plugin discovery).
- per-user usage metering (not planned — operator licenses are per-host).

The gate **establishes the boundary** so all of the above can be added
later without breaking public core.

---

## 7. Roadmap placement

Phase 7 (existing, P1) — `make audit-security` added to aggregate audit.
Phase 9 (existing, P2) — V1 freeze includes review that V1 launcher
does not contain license calls (currently fine; this is a check, not
a refactor).

Phase 4.6 (new, P1, after RuntimeCommandSpec):

1. `vllm/sndr_core/license/__init__.py` — boundary module with stubs.
2. `vllm/sndr_core/license/verify.py` — offline pub-key signature check.
3. `vllm/sndr_core/cli/license.py` — `sndr license status/verify/import`.
4. `scripts/security_scan.py` + `scripts/sbom_generate.py`.
5. `vllm/sndr_core/report/redact.py` — report bundle redaction rules.

Note: stubs are NOT placeholders in the §6.6 sense — they implement
the **unlicensed core** path (which is the default and only path on
public release).

---

## 8. Связи

- Roadmap Phase 4.6 (new, P1) + Phase 7 audit-security target.
- Mitigates: R3 (private paths leak), R5 (rollback unknown — security
  scan catches accidentally-committed credentials), supply-chain
  attacks (SBOM + signed artifacts).
- Implements: PROJECT_ROADMAP_V2_REVIEW_NOTES §P1.3.
- Pairs with: §6.10 public/private docs boundary gate.
