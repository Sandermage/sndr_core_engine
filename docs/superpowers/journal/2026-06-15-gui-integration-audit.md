# GUI ↔ backend integration audit (2026-06-15)

Operator ask: "проверить интеграцию с gui и исправить все недочеты" (check GUI
integration + fix all defects). Audited the React/Vite GUI (`gui/web/`) against
the FastAPI backend (`sndr/product_api/`).

## Integration shape

- **Production path (clean):** the legacy monolith `sndr/product_api/legacy/http_app.py`
  (177 routes, launched by `sndr gui-api`, port 8765) serves both the full
  `/api/v1/*` JSON API (bare responses) + the built SPA from
  `sndr/product_api/legacy/web_static/`. WebSocket terminal + SSE `/api/v1/events`.
  Auth = session cookie (same-origin) or Bearer/PAT (cross-origin), `X-Engine-Api-Key`
  passthrough. **Every one of the ~130 `gui/web/src/api.ts` calls maps to a real
  route** — the live frontend↔backend contract is clean (cross-checked, no orphans,
  no shape mismatch).
- **Carbon stack (parallel, incomplete):** `sndr/product_api/server.py`
  (`create_app`, port 8800, Envelope `{data,meta}` API, ~20 routes) + a separate
  `web_static_carbon/` bundle. This is the intended modern UI but is unfinished.

## Fixed this session

- **Stale production bundle (MED):** `legacy/web_static/` was 2 source-commits
  behind `gui/web/src` (predated "fix(gui): chat (empty) on reasoning models" — the
  deployed UI showed empty chat for reasoning models like the 27B/35B). Re-ran
  `make gui-build`, committed the refresh (488af475).
- **Dead gitignore path (MED):** dropped `sndr/product_api/web_static/` (written by
  no make target; production output is the tracked `legacy/web_static/`). Fixed the
  misleading "not tracked" comment (bfa1df50).
- **Stale doc refs (LOW):** `server.py` + `__init__.py` called the legacy monolith
  `vllm.sndr_core.product_api`; it is `sndr.product_api.legacy.http_app` post-v12
  (bfa1df50).

## Open — needs an operator product decision (NOT auto-fixed: would destroy WIP or
## require completing a ~110-route gap)

- **Carbon build is broken (HIGH):** `make gui-build-carbon` (Makefile:472-476) runs
  `npm run build:carbon`, but `gui/web/package.json` has no `build:carbon` script and
  the build never emits the `index.carbon.html` the target then `mv`s. The target
  fails immediately. The Carbon files are stale WIP (no substantive recent commits).
- **Carbon server cannot serve the GUI (HIGH):** `server.py:79` mounts the SPA at `/`,
  but `create_app` registers only ~20 Envelope-wrapped routes; the frontend needs
  ~130 **bare-JSON** routes (incl. `/auth/*`, `/engine/*`, `/copilot/*`, …) and reads
  `response.json()` without unwrapping `.data`. If the daemon ever serves the GUI from
  the Carbon server, login + most panels 404 / mis-parse.

  **Recommendation:** Carbon is non-production and incomplete. Either (a) finish it
  (register the full route set + add a `build:carbon` entry + unwrap `.data` in the
  client), or (b) remove the Carbon target/mount/server if abandoned. The production
  `sndr gui-api` path is unaffected either way. Left as-is pending that decision so
  WIP isn't destroyed.

## Verified fine (don't chase)

- `sndr_core_version` / "SNDR Core" / `sndr-state` strings in `api.ts`/`App.tsx`/
  `i18n.ts` are product field-names / branding (the patcher version), not stale imports.
- `/vllm/sndr_core` strings in `legacy/node_setup.py` + `legacy/deployment.py` are the
  engine container's runtime bind-mount path (`docker inspect`), not Python imports —
  correct by design (they target the compat mount; see the separate compat-mount-removal
  task, which updates these together).
