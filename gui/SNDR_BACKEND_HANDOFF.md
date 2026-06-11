# SNDR backend handoff — items the GUI work needs from the `sndr` project

This file is the contract between the **GUI release pass** (which only touches
`gui/web/`) and the agent that owns the `sndr/` backend. The GUI enterprise /
release-prep pass introduced **no new backend code changes**: the GUI↔daemon API
contract was audited as complete (143 `api.ts` methods ↔ 177 legacy routes, zero
mismatches). Everything below is either (a) hardening already committed on
`feat/v12-sndr-platform` that must reach and activate on the host, or (b) a
forward note. Nothing here should be re-implemented from scratch — verify state
first.

Branch with the changes: `feat/v12-sndr-platform`. Host (`192.168.1.10`) runs the
`sndr-daemon` container from branch `dev`. The gap is deploy + branch-sync.

---

## 0. Ship the rebuilt GUI bundle (the actual release artifact)

The release-ready build is `gui/web/dist/` (produced by `npm run build` in
`gui/web/`). The legacy daemon resolves its static dir in this order
(`http_app.py:_resolve_gui_static_dir`): `SNDR_GUI_STATIC` env → packaged
`web_static/` beside the module → repo `gui/web/dist`. Because packaged
`web_static/` wins over `gui/web/dist`, a stale `web_static/` will keep serving
the **old** GUI. To ship the new one, do exactly one of:

- **Preferred (clean):** sync the bundle into the packaged dir —
  `rm -rf sndr/product_api/legacy/web_static/* && cp -R gui/web/dist/* sndr/product_api/legacy/web_static/`
  then rebuild/restart the daemon.
- **Or** set `SNDR_GUI_STATIC=<repo>/gui/web/dist` in the daemon's environment
  (what the local smoke used — no write into `sndr/`).

This bundle deploy was intentionally left to the `sndr` agent: the GUI pass only
touches `gui/web/`, and `web_static/` lives under `sndr/`. The new bundle includes
the `react-vendor` cache-split chunk and the hardened `index.html`
(`color-scheme` / `theme-color` / `robots: noindex` / inline SVG favicon).

---

## 1. Hardening already committed — needs a host daemon rebuild to take effect

All of these live in `sndr/product_api/legacy/` and are committed; the tree is
clean. Only the threadpool fix has been verified live on the host. The rest were
held back from prod pending operator approval.

| # | Change | File / anchor | Commit | Live on host? |
| --- | --- | --- | --- | --- |
| 1 | Blocking container/system/k8s/proxmox handlers converted `async def` → `def` so Starlette runs them in the threadpool (kills event-loop serialization; 8-way concurrent load went 2.49s → 0.32s) | `http_app.py` (e.g. `container_inspect`, line ~1310) | `4302a137` | **Yes — deployed + verified** |
| 2 | `GZipMiddleware(minimum_size=512)` added before CORS | `http_app.py:251` | `4302a137` | No — needs rebuild |
| 3 | Security headers: `X-Frame-Options: DENY`, COOP `same-origin-allow-popups`, CSP, and HSTS gated on TLS (`_is_https` / `X-Forwarded-Proto` / `SNDR_FORCE_HSTS`) | `http_app.py:311,326,329` | `28e038e3` | No — needs rebuild |
| 4 | Strict SSH host-key policy: `RejectPolicy` by default, `AutoAddPolicy` only under TOFU env (`SNDR_SSH_HOST_KEY_POLICY` / `SNDR_SSH_STRICT_HOST_KEYS`); actionable error on unknown host | `ssh_client.py` | `28e038e3` | No — needs rebuild |
| 5 | One-time WARNING when Proxmox `verify_ssl` is disabled | `proxmox_client.py` | `28e038e3` | No — needs rebuild |
| 6 | `container_link` live-patch overlay now matches the **registry** `SNDR_ENABLE_*` flags (PN282/PN283) instead of a prefix guess, so those patches show as live while the daemon gates `SNDR_ENABLE_APPLY` / `SNDR_ENABLE_EXEC` correctly do **not** | `container_link.py:34-58` | `e29fbf5d` | No — needs rebuild |

### Required action

1. Merge / cherry-pick the three commits above into the host's deployed branch
   (`dev`), or fast-forward `dev` to include them.
2. Rebuild + restart the host `sndr-daemon` container (host-network bind-mount of
   `/home/sander/genesis-vllm-patches/sndr`).
3. Run the post-deploy smoke (section 3). Items 2–6 only become observable after
   this rebuild.

### Deployment safety notes

- **Item 4 (SSH strict host keys)** is the only behavior-changing one for live
  ops: if the host's `known_hosts` does not yet trust a target (Proxmox `.33`,
  server `.10`), connections will now be **rejected** instead of auto-added.
  Either pre-seed `known_hosts` or set `SNDR_SSH_HOST_KEY_POLICY` to the TOFU
  value for the first connect, then tighten. Do not deploy item 4 blind.
- **Item 3 (HSTS)** only emits over real TLS or when `SNDR_FORCE_HSTS` is set, so
  a plain-HTTP loopback deploy is unaffected.

---

## 2. SGLang — no action required for the GUI release

The audit confirmed the shipped GUI and the legacy daemon it talks to **do not
reference SGLang at all** (`grep -ri sglang gui/web/src` → 0;
`grep -ri sglang sndr/product_api/legacy` → 0). There is therefore no false
"engine parity" to correct. SGLang exists only as:

- an empty data-model adapter in the **newer** `sndr/product_api/server.py`
  framework, which the legacy daemon does **not** serve, and
- patch-borrowing references (P82, PN350) that run *inside* vLLM.

**Forward note (out of scope for this release):** if SGLang ever becomes a live
engine, the engines/capabilities service in the new `server.py` framework needs
real wiring (`get_runtime_config` currently returns `None`). Until then, keep any
product surface that lists "vLLM and SGLang" labelled as aspirational, not
operational. No GUI change is blocked on this.

---

## 3. Post-deploy verification (run after the host rebuild)

```bash
# 1. gzip negotiated on a large JSON route
curl -s -H 'Accept-Encoding: gzip' -D - http://127.0.0.1:8765/api/v1/overview -o /dev/null | grep -i content-encoding
# 2. security headers present
curl -s -D - http://127.0.0.1:8765/api/v1/health -o /dev/null | grep -iE 'x-frame-options|content-security-policy|cross-origin-opener'
# 3. HSTS absent on plain HTTP (only fires under TLS / SNDR_FORCE_HSTS)
curl -s -D - http://127.0.0.1:8765/api/v1/health -o /dev/null | grep -i strict-transport-security || echo 'HSTS correctly absent on plain HTTP'
# 4. concurrency: blocking routes no longer serialize
time (for i in $(seq 8); do curl -s http://127.0.0.1:8765/api/v1/containers -o /dev/null & done; wait)
# 5. container_link: a container running SNDR_ENABLE_PN282/PN283 shows them as live patches,
#    while SNDR_ENABLE_APPLY / SNDR_ENABLE_EXEC never appear in the live-patch overlay
```

The matching unit tests already exist under `tests/unit/product_api/`
(`test_http_app.py`, `test_ssh_client.py`, `test_container_link.py`) and pass
(564 product_api tests green). Run `pytest tests/unit/product_api/` after the
merge to confirm nothing regressed.

---

## 4. What the GUI pass did NOT need from the backend

For the record, so nothing gets invented: the GUI enterprise/release pass
(tsconfig strictness, vendor chunk-split, release metadata, dead-code removal)
required **no** new endpoints, no schema changes, and no contract changes. The
existing routes and frozen dataclasses are sufficient and correct.
