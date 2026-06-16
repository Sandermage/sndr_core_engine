# SNDR GUI — modernization roadmap & progress

Derived from a code audit + a survey of leading admin panels (React-Admin, Refine,
shadcn/ui, Tremor, Grafana, Portainer, Proxmox, Coolify, OpenWebUI). Goal: a GUI
that is structurally + adaptively compatible with the SNDR backend and bug-free.

## What's already excellent (keep)

Clean `lib/`/`hooks/`/`components/`/`sections/` layering · aggressive code-splitting
(~25 `lazy()`) · strict TS with **zero** `as any`/`@ts-ignore`/TODO · real ultrawide
adaptivity (`useViewport` + `[data-viewport]`) · unified overlay/toast/a11y system ·
daemon-down self-recovery.

## Progress

- [x] **Iteration 1 — quick win + systematize** (`213df92b`)
  - macro tool: 4 rapid Yahoo calls → 429; now ONE batched `/finance/spark` request.
  - section registry: the section list was hand-synced in 3 places (`SectionId`,
    `SECTION_IDS`, `navGroups`); now a single `NAV_SECTIONS` + `ROUTABLE_ONLY` in
    `nav.ts` from which all three are derived. Drift class removed.
- [x] **Iteration 2 — data layer (TanStack Query)**
  - `QueryClientProvider` in `main.tsx` (operator defaults: 10s stale, retry 1, no
    refetch-on-focus). `hooks/useLibrary.ts` = typed query/mutation hooks with a
    shared cache. Reference migration: the prompts/tools library + the chat prompt
    selector now share `["prompts"]` — a mutation invalidates one key and every
    consumer updates, no manual refetch. This is the pattern to extend.

- [x] **Iteration 3 — section data layer on Query**
  - `hooks/useApiQuery.ts`: a `useFetch`-compatible read hook backed by TanStack
    Query (shared/deduped cache, retry, AbortSignal) but with an EXPLICIT queryKey
    (backing `useFetch` transparently was unsafe — two fetchers with the same deps
    would collide). Migrated all 7 `useFetch` call sites (models-workbench,
    diagnostics, catalog-cards) and retired the now-dead `useFetch.ts`.

## Next (prioritized)

1. **Extend Query to the App-level loads** — replace the hand-rolled `usePoll` +
   the ~45-`useState` orchestration in App.tsx. Higher value but entangled with the
   god file, so best done WITH breaking App.tsx up (step 3). Kills the
   swallowed-`catch{}` gaps via Query's built-in error/retry.
2. **Typed contract codegen — BLOCKED on the backend.** Survey + measurement: the
   daemon's OpenAPI is **0% typed** (185 routes, 0 with a real 200 response schema;
   they return `dict[str, Any]`). `openapi-typescript` would emit `unknown`
   everywhere. **Prereq:** give the routes `response_model`s built from the frozen
   dataclasses (a backend track), *then* generate `src/api/schema.gen.ts` (already
   referenced in `eslint.config.js`) and drop the 41 `Record<string, any>` holes.
   Until then the hand-written types stay (they're good — ~80 thorough types).
3. **Break up the god files** — extract App.tsx's inlined launch-plan view +
   `SectionWorkspace` (50-prop), and Containers.tsx (32 `useState`, 7 inline tabs).
4. **Component system** — a `SelectableCard` primitive (unify fleet/launch/catalog
   card variants), promote `PanelHeader`/`EmptyState`, a `cmdk` command palette.
5. **Workspace** — extend the prompt/tool library to the full OpenWebUI idiom
   (Clone / Export-JSON / Import, + Models presets).
6. **i18n tooling** — a `tr()` extractor + CI untranslated-key audit (the
   ~2,500-entry source-keyed `RU_BY_EN` map silently un-translates on a copy edit).
7. **Build integration** — make `dist → web_static` a build step of `sndr` (today
   it's a manual sync), and a11y lint `warn` → `error` for new code.
