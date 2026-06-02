# SNDR Control Center — Roadmap / Remaining Work

Status of the GUI + Product API as of the latest iteration, and what is left to
do. Done items are listed for context; open items are prioritized.

## Done

- 15 operator screens (Overview … Advanced), tabbed/modular, dark + light.
- Read-only Product API with plan-before-apply; real apply gated by
  `--enable-apply` + confirm.
- Launch Plan reworked into a guided flow (Choose → Configure → **Launch** →
  Observe) with a dedicated launch surface.
- Presets master/detail catalog; enriched Benchmarks/Evidence panels.
- Single-process packaging (daemon serves the built UI), same-origin.
- **Authentication**: local accounts (scrypt), optional PAM, Google/Apple OAuth,
  TOTP 2FA, signed sessions, admin user management, persistent store under
  `$SNDR_HOME/auth`. Backward-compatible with the legacy `SNDR_GUI_TOKEN`.
- **Live engine bridge**: `/api/v1/engine/{status,metrics,chat}` — the GUI now
  reads a *running* vLLM server: online/version/loaded-model, live Prometheus
  KPIs (queue, KV-cache, throughput, TTFT/TPOT, spec-decode acceptance), and a
  Playground that sends a real prompt. SSRF-safe (validated host, fixed
  ports/paths). Surfaced in Services → Engine and Clients.
- Tests: `tests/unit/product_api` (200+), `tests/unit/product_api/auth` (37),
  `test_engine_client` (11), Playwright smoke e2e, API contract guard.

## Open — project + engine API coverage

The API covers the *static* project (catalog/patches/configs/planning) well and
now reads the *live engine* (status/metrics/playground). Remaining surfaces:

| # | Item | Priority | Notes |
| --- | --- | --- | --- |
| ~~A~~ | ~~**Streaming chat in the Playground**~~ ✅ done | — | `POST /api/v1/engine/chat/stream` (ND-JSON); the Playground streams tokens live with a Stream toggle. |
| ~~B~~ | ~~**Real benchmark execution + A/B compare**~~ ✅ done | — | `POST /api/v1/engine/bench` drives real streamed completions → throughput/TTFT-p50-p90/TPOT/CV; Benchmarks → Live bench runs A/B with deltas. Labelled distinct from the canonical Wave suite (iron rule #9). |
| ~~C~~ | ~~**Live metrics history / sparklines**~~ ✅ done | — | Metrics endpoint keeps a 60-sample ring buffer; Services → Engine draws throughput/KV/queue sparklines. |
| ~~D~~ | ~~**Model download / cache management**~~ ✅ done | — | Models → Cache & download: catalog-validated `model pull` runs as a **live background job** (progress bar + streaming log) with `--enable-apply`; dry-run otherwise. |
| E | **Tune / routing / gateway surfaces** | Low | `tune`, `routing`, `gateway` CLI capabilities are unexposed. |
| F | **Deploy lifecycle (k8s/quadlet/proxmox)** | Low | Launch plan emits artifacts; lifecycle management is CLI-only. |
| G | **Upstream drift audit** | Low | `patches/diff-upstream` is per-patch static; surface the `upstream` audit/drift report. |

## Open — authentication hardening

| # | Item | Priority | Notes |
| --- | --- | --- | --- |
| 1 | **2FA QR code** in the enrolment UI | High | Today shows the secret + `otpauth://` URI for manual entry. Add a client-side QR (e.g. `qrcode`) so users can scan. |
| ~~2~~ | ~~**2FA recovery codes**~~ ✅ done | — | 10 single-use scrypt-hashed codes at enrolment (shown once) + regenerate; login accepts a recovery code. |
| ~~3~~ | ~~**Login rate-limiting / lockout**~~ ✅ done | — | Per-account throttle → temporary 429 lock (tunable thresholds). |
| ~~4~~ | ~~**Auth audit log**~~ ✅ done | — | login/logout/lockout, user create/delete, 2FA, password, revoke → events feed (kind `auth`). |
| ~~5~~ | ~~**Session revocation**~~ ✅ done | — | Per-account token epoch; password change + "sign out everywhere" invalidate all tokens. |
| 6 | **Password reset / forgot-password** | Medium | Admin can delete+recreate; no self-service reset. Needs an out-of-band channel (email) to be safe. |
| ~~7~~ | ~~**CSRF protection**~~ ✅ done | — | Same-origin (`Sec-Fetch-Site`/`Origin`) check on cookie-authenticated mutations; bearer exempt. |
| 8 | **PAM group → role mapping** | Low | PAM logins default to `operator`; map system groups to `admin`/`viewer`. |
| 9 | **Live OAuth validation** | Medium | Google/Apple wiring is unit-tested but not validated against live providers; add an Apple client-secret-JWT helper and a setup checklist. |

## Open — deployment & persistence

| # | Item | Priority | Notes |
| --- | --- | --- | --- |
| 10 | **Ship a GUI Dockerfile + compose** | High | Docs show `docker run`, but no Dockerfile for the daemon is shipped. Provide an image that builds the UI and runs `gui-api`, with `$SNDR_HOME` as a volume. |
| ~~11~~ | ~~**Persist jobs/events**~~ ✅ done | — | Jobs + event feed persisted under `$SNDR_HOME/state` (atomic JSON, bounded); verified across a real daemon restart. |
| 12 | **TLS guidance / built-in HTTPS** | Medium | The daemon serves HTTP; production should sit behind a TLS reverse proxy (documented). Optionally support `--tls-cert/--tls-key`. |
| 13 | **Healthcheck + graceful shutdown** | Low | Container `HEALTHCHECK` and clean uvicorn shutdown for orchestration. |

## Open — frontend quality (carried from prior audits)

| # | Item | Priority | Notes |
| --- | --- | --- | --- |
| 14 | **Decompose `App.tsx`** (~7600 lines) | Medium | Split into feature folders (`Launch/`, `Config/`, `Patches/`, `hooks/`). Structural debt; no user-facing change. |
| 15 | **Broader a11y pass** | Medium | Focus management in dialogs, more `aria-label`s, audit keyboard traps. (Tabs already follow the WCAG pattern.) |
| 16 | **Advanced → Appearance density** | Low | The settings tab is sparse; a compact "session & shortcuts" card would fill it usefully. |
| 17 | **Optimistic updates + retry UX** | Low | A shared `useFetch` retry exists; extend optimistic state to more POST actions. |

## How to pick up an item

Each row maps to a focused change. Auth items touch
`vllm/sndr_core/product_api/auth/*` (+ `gui/web/src/Auth.tsx`); deployment items
are mostly packaging; frontend-quality items are `gui/web/src/`. See
[`docs/GUI.md`](GUI.md) and [`docs/GUI_SECURITY.md`](GUI_SECURITY.md) for the
current surface.
