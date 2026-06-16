// SPDX-License-Identifier: Apache-2.0
// The Presets section: a tabbed catalog (browse + quick panel), a recommend &
// analytics tab (policy / coverage / annotation breakdowns), the selected-preset
// detail view, and a visual editor. Owns its controlled tab state so catalog
// actions can jump between tabs. Extracted from section-workspace.tsx.
import { useState } from "react";
import {
  AlertTriangle, BarChart3, Box, Database, FileText, GitBranch, Layers3,
  Rocket, ShieldCheck, SlidersHorizontal, Wrench
} from "lucide-react";
import { tr } from "../i18n";
import { asNumber, asRecord, asText, countRecord } from "../lib/coerce";
import type {
  ProductOverview, PresetListResult, PresetRecord, PresetExplainResult, ProductCapability
} from "../api";
import type { SectionId } from "../nav";
import { TabbedSection } from "../components/tabbed-section";
import { ModuleCard, ModuleGrid } from "../components/layout";
import { BarList } from "../components/charts";
import { CompactList } from "../components/primitives";
import { PresetSelectedView, PresetSummaryStrip } from "./preset-views";
import { PresetCatalogTable } from "./preset-catalog";
import { PresetQuickPanel } from "./preset-quick";
import { PresetRecommendPanel } from "./preset-recommend";
import { PresetPolicyGraph } from "./preset-insight";
import { LayerEditor } from "./layer-editor";

export function PresetsSection({
  overview,
  presets,
  filteredPresets,
  selectedPreset,
  selectedPresetRecord,
  explain,
  runtimeTargets,
  runtimeTarget,
  patchPolicy,
  card,
  composed,
  onPreset,
  onSection
}: {
  overview: ProductOverview | null;
  presets: PresetListResult | null;
  filteredPresets: PresetRecord[];
  selectedPreset: string;
  selectedPresetRecord: PresetRecord | null;
  explain: PresetExplainResult | null;
  runtimeTargets: ProductCapability[];
  runtimeTarget: string;
  patchPolicy: string;
  card: Record<string, unknown>;
  composed: Record<string, unknown>;
  onPreset: (id: string) => void;
  onSection: (section: SectionId) => void;
}) {
  const [presetTab, setPresetTab] = useState("catalog");
  const familyCounts = overview?.catalog.family_counts ?? {};
  const workloadCounts = overview?.catalog.workload_counts ?? {};
  return (
            <TabbedSection
          id="presets"
          activeTab={presetTab}
          onTabChange={setPresetTab}
          tabs={[
            {
              id: "catalog",
              label: tr("Catalog"),
              icon: <Database size={15} />,
              render: () => (
                <div className="preset-catalog-view">
                  {presets?.load_errors && presets.load_errors.length > 0 && (
                    <div className="preset-load-errors">
                      <AlertTriangle size={15} />
                      <div>
                        <strong>{presets.load_errors.length} {presets.load_errors.length > 1 ? tr("presets failed to load") : tr("preset failed to load")}</strong>
                        {presets.load_errors.slice(0, 6).map((e, i) => (
                          <div key={i} className="preset-load-error"><code>{e.preset ?? e.id ?? e.file ?? "?"}</code> — {e.error ?? e.message ?? JSON.stringify(e)}</div>
                        ))}
                        {presets.load_errors.length > 6 && <div className="muted">+{presets.load_errors.length - 6} {tr("more")}</div>}
                      </div>
                    </div>
                  )}
                  <PresetSummaryStrip presets={filteredPresets} selectedPreset={selectedPreset} />
                  <div className="preset-catalog-split">
                    <ModuleCard
                      title={tr("Preset Catalog")}
                      icon={<Database size={18} />}
                      desc={tr("Pick a preset to inspect its runtime, edit a local copy, or launch it.")}
                    >
                      <PresetCatalogTable
                        presets={filteredPresets}
                        selectedPreset={selectedPreset}
                        onPreset={onPreset}
                        onEdit={(id) => { onPreset(id); setPresetTab("edit"); }}
                      />
                    </ModuleCard>
                    <PresetQuickPanel
                      selectedPreset={selectedPreset}
                      record={selectedPresetRecord}
                      card={card}
                      composed={composed}
                      onOpenCard={() => setPresetTab("selected")}
                      onEdit={() => setPresetTab("edit")}
                      onPolicy={() => setPresetTab("recommend")}
                      onLaunch={() => onSection("launch-plan")}
                    />
                  </div>
                </div>
              )
            },
            {
              id: "recommend",
              label: tr("Recommend & analytics"),
              icon: <Rocket size={15} />,
              render: () => {
                const allPresets = presets?.presets ?? [];
                const annotated = allPresets.filter((p) => p.has_card).length;
                const benchProven = allPresets.filter((p) => asNumber(asRecord(p.card?.primary_metric).value) > 0).length;
                const statusDist = countRecord(allPresets.map((p) => asText(p.card?.status, p.has_card ? "annotated" : "unannotated")));
                const visibilityDist = countRecord(allPresets.filter((p) => p.has_card).map((p) => asText(p.card?.evidence_visibility, "unknown")));
                const fallbacks = allPresets.filter((p) => p.card?.fallback_preset);
                const bar = (counts: Record<string, number>): Array<[string, number, string]> => {
                  const max = Math.max(1, ...Object.values(counts));
                  return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, Math.round((v / max) * 100), String(v)]);
                };
                const kpis: Array<[string, number]> = [
                  [tr("Presets"), allPresets.length], [tr("Annotated"), annotated], [tr("Bench-proven"), benchProven],
                  [tr("Fallbacks"), fallbacks.length], [tr("Families"), Object.keys(familyCounts).length], [tr("Workloads"), Object.keys(workloadCounts).length]
                ];
                return (
                <>
                  <ModuleGrid>
                    <ModuleCard title={tr("Recommend a preset")} icon={<Rocket size={18} />} desc={tr("Rank presets for a workload + rig + concurrency target, then inspect the winner.")} wide>
                      <PresetRecommendPanel
                        hardwareOptions={Array.from(new Set((presets?.presets ?? []).map((preset) => preset.hardware))).filter(Boolean)}
                        workloadCounts={overview?.catalog.workload_counts ?? {}}
                        onSelect={(id) => { onPreset(id); setPresetTab("selected"); }}
                      />
                    </ModuleCard>
                  </ModuleGrid>
                  <div className="preset-analytics-heading"><BarChart3 size={15} /> {tr("Catalog analytics")} <span>{tr("policy, coverage and annotation across")} {allPresets.length} {tr("presets")}</span></div>
                  <div className="preset-analytics-kpis">
                    {kpis.map(([label, value]) => (
                      <div className="preset-stat" key={label}><span className="preset-stat-value">{value}</span><span className="preset-stat-label">{label}</span></div>
                    ))}
                  </div>
                  <ModuleGrid className="preset-analytics-grid">
                    <ModuleCard title={tr("Workload Policy")} icon={<SlidersHorizontal size={18} />} desc={`${tr("Allow/deny for")} ${selectedPreset}.`}>
                      <PresetPolicyGraph card={card} />
                    </ModuleCard>
                    <ModuleCard title={tr("Status Distribution")} icon={<ShieldCheck size={18} />} desc={`${annotated} ${tr("annotated")} · ${Object.keys(statusDist).length} ${tr("statuses")}`}>
                      <BarList rows={bar(statusDist)} />
                    </ModuleCard>
                    <ModuleCard title={tr("Evidence Visibility")} icon={<FileText size={18} />} desc={`${Object.keys(visibilityDist).length} ${Object.keys(visibilityDist).length === 1 ? tr("visibility level") : tr("visibility levels")}`}>
                      {Object.keys(visibilityDist).length ? <BarList rows={bar(visibilityDist)} /> : <p className="muted">{tr("No annotated presets.")}</p>}
                    </ModuleCard>
                    <ModuleCard title={tr("Workload Coverage")} icon={<Layers3 size={18} />} desc={`${Object.keys(workloadCounts).length} ${tr("workload classes")}`}>
                      <BarList rows={bar(workloadCounts)} />
                    </ModuleCard>
                    <ModuleCard title={tr("Family Coverage")} icon={<Box size={18} />} desc={`${Object.keys(familyCounts).length} ${tr("routing families")}`}>
                      <BarList rows={bar(familyCounts)} />
                    </ModuleCard>
                    <ModuleCard title={tr("Fallback Chains")} icon={<GitBranch size={18} />} desc={`${fallbacks.length} ${tr("of")} ${allPresets.length} ${tr("presets")}`}>
                      {fallbacks.length ? (
                        <CompactList rows={fallbacks.map((p) => [p.id, `→ ${asText(p.card?.fallback_preset, "-")}`] as [string, string])} />
                      ) : (
                        <p className="muted">{tr("No fallback chains declared.")}</p>
                      )}
                    </ModuleCard>
                  </ModuleGrid>
                </>
                );
              }
            },
            {
              id: "selected",
              label: tr("Selected"),
              icon: <FileText size={15} />,
              render: () => (
                <PresetSelectedView
                  selectedPreset={selectedPreset}
                  record={selectedPresetRecord}
                  card={card}
                  composed={composed}
                  explain={explain}
                  runtimeTargets={runtimeTargets}
                  runtimeTarget={runtimeTarget}
                  patchPolicy={patchPolicy}
                  onEdit={() => setPresetTab("edit")}
                  onLaunch={() => onSection("launch-plan")}
                  onConfigs={() => onSection("configs")}
                />
              )
            },
            {
              id: "edit",
              label: tr("Edit"),
              icon: <SlidersHorizontal size={15} />,
              render: () => (
                <ModuleGrid>
                  <ModuleCard
                    title={`${tr("Visual Editor")} — ${selectedPreset}`}
                    icon={<Wrench size={18} />}
                    desc={tr("Full preset editing: pointers, card metadata and any other fields the preset defines. Saves an operator-local copy.")}
                    wide
                  >
                    <LayerEditor kind="preset" layerId={selectedPreset} />
                  </ModuleCard>
                </ModuleGrid>
              )
            }
          ]}
        />
  );
}
