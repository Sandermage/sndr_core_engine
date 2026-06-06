# Carbon Control Center — PARKED (WIP)

**Status (2026-06-06): parked.** The canonical, shipping GUI is `src/App.tsx`
(served by the legacy daemon). The Carbon-based rewrite below is a parallel
experiment that is **not** in the active build or release path. Do not invest
in it unless a migration is explicitly scheduled.

## Why parked

`App.tsx` is already fully integrated with the v12.x `sndr` restructure
(97/97 endpoint parity, HTTP-decoupled, styled, all features: Fleet,
Hardware telemetry, Engine chat, Installer, Patches+Flags, Routing, Alerts,
License). Maintaining a second, thinner GUI is a clone we don't want. The
enterprise hardening effort goes into `App.tsx`.

## What exists (and builds)

- `src/CarbonApp.tsx`, `src/main.carbon.tsx`, `index.carbon.html`
- `src/features/*` — 17 feature modules wired to the **new enveloped API**
  (`sndr.product_api.server`, `{data, meta}` contract), not the legacy raw API
- `src/api/{client,contract,schema.gen}.ts`, `src/i18n/`, `src/stores/`
- Build: `npm run build:carbon` → green (0 TS errors). Serving wiring:
  `make gui-build-carbon` + `_mount_carbon_ui` in `sndr/product_api/server.py`
  (dormant unless a bundle is present).

## Known gap before it could ship

- **No Carbon theme/styles wired.** The bundle renders unstyled because the
  `@carbon/styles` SCSS layer is not imported in the entry/`styles.css`. This
  is the first thing to fix if Carbon is ever un-parked.
- Feature depth is well below `App.tsx` (no GPU-ring telemetry, streaming
  chat, installer wizard, alerts/routing/flags-matrix panels).

## To resume later

1. Wire `@carbon/styles` (`@use '@carbon/styles';` in the SCSS entry).
2. Bring features to `App.tsx` parity.
3. `make gui-build-carbon && uvicorn sndr.product_api.server:create_app --factory --port 8800`.
