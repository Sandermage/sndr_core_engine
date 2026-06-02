# SNDR Control Center — Desktop (Tauri v2)

Status: **entry point for GUI.P6 (desktop packaging).** This directory documents
how to wrap the existing web UI (`gui/web`) as a cross-platform desktop app.

No Rust source is committed here yet on purpose: the desktop build requires a
Rust toolchain that is not part of the Python/Node project, and this repo's rule
is that committed code must be built and verified. The steps and config below
are the exact, ready-to-run scaffold — run them on a machine with Rust to
produce a working app.

## Why Tauri (not Electron)

- Uses the system webview → small bundles, low footprint.
- Cross-platform: macOS / Linux / Windows.
- Strong permission model; good fit for a local control-plane UI.

The Rust layer does **only**: windowing, tray/menu, SSH-tunnel lifecycle helper,
host-profile storage, notifications, and optional local-daemon supervision. It
must **not** contain SNDR business logic — everything goes through the Product
API daemon (`sndr gui-api`), exactly like the browser UI.

## Prerequisites

- Rust toolchain (`rustup`, stable).
- Node + a built/served `gui/web`.
- Platform SDKs for bundling (Xcode CLT on macOS; WebView2 on Windows;
  `libwebkit2gtk` on Linux).

## Scaffold

```bash
cd gui/desktop
npm create tauri-app@latest -- --template vanilla --manager npm   # or init into existing
# choose: app name "sndr-control-center", identifier "ai.sndr.controlcenter"
```

Point Tauri at the web UI. Two modes:

- **Dev:** Tauri loads the Vite dev server (`http://127.0.0.1:5173`).
- **Release:** Tauri bundles the static build from `gui/web/dist`.

### `src-tauri/tauri.conf.json` (essentials)

```json
{
  "productName": "SNDR Control Center",
  "identifier": "ai.sndr.controlcenter",
  "build": {
    "frontendDist": "../../web/dist",
    "devUrl": "http://127.0.0.1:5173",
    "beforeDevCommand": "npm --prefix ../../web run dev",
    "beforeBuildCommand": "npm --prefix ../../web run build"
  },
  "app": {
    "windows": [
      { "title": "SNDR Control Center", "width": 1440, "height": 900, "minWidth": 1024, "minHeight": 700 }
    ],
    "security": { "csp": null }
  },
  "bundle": { "active": true, "targets": "all" }
}
```

## Remote-host model (GUI.P6 scope)

The desktop app's value over the browser is host management:

1. Store SSH host profiles (reuse the daemon's `GET/POST /api/v1/hosts`, or a
   local store mirrored into the Rust side for tunnel metadata).
2. Check whether the remote `sndr gui-api` is running.
3. Open/keep an `ssh -L 8765:127.0.0.1:8765 user@gpu-host` tunnel.
4. Point the embedded UI at the forwarded loopback port.

All actions still flow through the daemon Product API. Keep the daemon bound to
`127.0.0.1` on the remote host (see `docs/GUI_SECURITY.md`).

## Build

```bash
cd gui/desktop
npm run tauri build        # macOS .dmg/.app, Windows .msi, Linux .deb/AppImage
```

## Acceptance (per plan GUI.P6)

- Same UI works in browser and desktop.
- Desktop connects to a remote Linux GPU host over an SSH tunnel.
- Packaging does not require `sndr_engine`.
- No SNDR business logic duplicated in Rust.
- Unsigned dev builds documented separately from release-signed builds.

See `docs/GUI.md` and the main plan
(`sndr_private/planning/SNDR_GUI_IMPLEMENTATION_PLAN_2026-05-28_RU.md`, §20/§23).
