// SPDX-License-Identifier: Apache-2.0
// Patch overview panels (the patches-tab header strip): KPI summary, lifecycle /
// production-default distributions, registry insight with a plain-language
// legend, and the supported-models chips.
import { type PatchListResult, type PatchRow } from "../api";
import { countRecord } from "../lib/coerce";
import { SegmentBar, BarList, segmentsFromCounts } from "../components/charts";
import { KpiGrid, CompactList } from "../components/primitives";
import { tr } from "../i18n";

export function PatchSummaryPanel({
  summary,
  total,
  selectedCount
}: {
  summary: PatchListResult["summary"] | null;
  total: number;
  selectedCount: number;
}) {
  const lifecycleRows = Object.entries(summary?.lifecycle_counts ?? {});
  const productionRows = Object.entries(summary?.production_default_counts ?? {});
  return (
    <div className="patch-summary-grid">
      <KpiGrid
        rows={[
          [tr("Registry"), total],
          [tr("Selected Plan"), selectedCount || "-"],
          [tr("Stable"), summary?.lifecycle_counts.stable ?? 0],
          [tr("Default Applied"), summary?.production_default_counts.applied ?? 0]
        ]}
      />
      <CompactList rows={lifecycleRows.map(([key, value]) => [`${tr("lifecycle")}:${key}`, String(value)])} />
      <CompactList rows={productionRows.map(([key, value]) => [`${tr("default")}:${key}`, String(value)])} />
    </div>
  );
}

export function PatchLifecycleGraph({
  summary
}: {
  summary: PatchListResult["summary"] | null;
}) {
  const lifecycle = summary?.lifecycle_counts ?? {};
  const production = summary?.production_default_counts ?? {};
  const lifecycleTotal = Object.values(lifecycle).reduce((a, b) => a + b, 0);
  const productionTotal = Object.values(production).reduce((a, b) => a + b, 0);
  const lifecycleColors: Record<string, string> = {
    stable: "var(--ok)", experimental: "var(--warn)", research: "var(--info)",
    retired: "var(--danger)", qa: "var(--accent)"
  };
  const defaultColors: Record<string, string> = {
    applied: "var(--ok)", marker: "var(--warn)", "opt-in": "var(--info)", blocked: "var(--danger)"
  };
  return (
    <div className="patch-graph-grid">
      <section>
        <strong>{tr("Lifecycle distribution")}</strong>
        <SegmentBar
          segments={segmentsFromCounts(lifecycle, lifecycleColors)}
          total={lifecycleTotal}
          totalLabel={tr("patches")}
        />
      </section>
      <section>
        <strong>{tr("Production default behavior")}</strong>
        <SegmentBar
          segments={segmentsFromCounts(production, defaultColors)}
          total={productionTotal}
          totalLabel={tr("patches")}
        />
      </section>
    </div>
  );
}

const IMPL_MEANING: Record<string, string> = {
  full: tr("complete overlay — observable ON/OFF difference"),
  partial: tr("some anchors wired; not yet fully effective"),
  marker_only: tr("registry marker, no runtime code"),
  placeholder: tr("reserved id, implementation pending"),
  experimental: tr("wired but unproven; needs evidence"),
  retired: tr("superseded/removed, kept for audit")
};

function patchBar(counts: Record<string, number>, limit = 99): Array<[string, number, string]> {
  const max = Math.max(1, ...Object.values(counts));
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([k, v]) => [k.replace(/_/g, " "), Math.round((v / max) * 100), String(v)] as [string, number, string]);
}

/** Tab-1 insight: status + family distributions + a plain-language legend. */
export function PatchRegistryInsight({
  summary,
  patches
}: {
  summary: PatchListResult["summary"] | null;
  patches: PatchRow[];
}) {
  const implCounts = summary?.implementation_status_counts ?? {};
  const familyCounts = countRecord(patches.map((patch) => patch.family || "uncategorized"));
  return (
    <div className="patch-insight">
      <div className="patch-insight-grid">
        <div>
          <h5>{tr("Implementation status")}</h5>
          <BarList rows={patchBar(implCounts)} />
        </div>
        <div>
          <h5>{tr("Families")} <em>{Object.keys(familyCounts).length}</em></h5>
          <BarList rows={patchBar(familyCounts, 12)} />
        </div>
      </div>
      <div className="patch-legend">
        <h5>{tr("What the values mean")}</h5>
        <dl>
          <div><dt>{tr("Lifecycle")}</dt><dd><b>stable</b> {tr("safe default")} · <b>experimental</b> {tr("needs evidence")} · <b>research</b> {tr("idea-only")} · <b>legacy</b> {tr("older but kept")} · <b>retired</b> {tr("audit-only")} · <b>coordinator</b> {tr("orchestrates others.")}</dd></div>
          <div><dt>{tr("Production default")}</dt><dd><b>applied</b> {tr("on with real code")} · <b>marker</b> {tr("on but no effect")} · <b>opt-in</b> {tr("off by default")} · <b>blocked</b> {tr("not production-safe.")}</dd></div>
          <div><dt>{tr("Implementation")}</dt><dd>{Object.entries(IMPL_MEANING).map(([k, v]) => `${k}: ${v}`).join(" · ")}.</dd></div>
        </dl>
      </div>
    </div>
  );
}

/** Tab-1 supported models — the catalog the patch family targets. */
export function PatchModelSupport({ models }: { models: Array<{ id: string; title?: string }> }) {
  return (
    <div className="patch-models">
      <p className="muted">
        {tr("Patches target the catalog models below. Each patch declares its own applicability — model family, TurboQuant, vLLM version range — shown per-patch in the Inventory tab under")} <strong>{tr("Supported models")}</strong>.
      </p>
      <div className="chip-row">
        {models.length ? models.map((model) => (
          <span className="chip" key={model.id} title={model.title ?? model.id}>{model.id}</span>
        )) : <span className="muted">{tr("No models in the catalog.")}</span>}
      </div>
    </div>
  );
}
