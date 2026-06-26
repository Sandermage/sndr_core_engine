// SPDX-License-Identifier: Apache-2.0
// Preset catalog table: status + bench filters, sortable columns, a measured
// baseline chip per row, and an illustrated empty state.
import { useState } from "react";
import { ChevronRight, Wrench, Database, X } from "lucide-react";
import { type PresetRecord } from "../api";
import { asText, asNumber, asRecord } from "../lib/coerce";
import { StatusBadge } from "../components/primitives";
import { EmptyState } from "../components/empty-state";
import { tr } from "../i18n";

// Benchmark-baseline chip for the preset catalog: surfaces the measured
// reference metric (primary_metric) at the list level, so bench-proven presets
// are distinguishable from pending ones at a glance. value 0 / missing = pending.
export function PresetBaselineCell({ card }: { card: Record<string, any> }) {
  const m = asRecord(card?.primary_metric);
  const value = asNumber(m.value);
  if (!m.kind && !value) return <span className="muted">—</span>;
  const tip = [asText(m.source, ""), asText(m.measured_at, "")].filter(Boolean).join(" · ");
  if (value > 0) {
    const kind = asText(m.kind, "TPS").replace(/^agg_/, "");
    return <span className="bench-chip ok" title={tip || undefined}>{value.toLocaleString()} {kind}</span>;
  }
  return <span className="bench-chip pending" title={tip || undefined}>{tr("pending")}</span>;
}

export function PresetCatalogTable({
  presets,
  selectedPreset,
  onPreset,
  onEdit
}: {
  presets: PresetRecord[];
  selectedPreset: string;
  onPreset: (id: string) => void;
  onEdit?: (id: string) => void;
}) {
  const [statusFilter, setStatusFilter] = useState("all");
  const [benchFilter, setBenchFilter] = useState<"all" | "proven" | "pending">("all");
  const [sortKey, setSortKey] = useState<"id" | "model" | "status" | "baseline">("id");
  const [sortDir, setSortDir] = useState<1 | -1>(1);

  const statusOf = (preset: PresetRecord) =>
    preset.has_card ? asText(preset.card?.status, "available") : "missing";
  // Measured reference throughput (0 = pending) — used for the Baseline sort.
  const baselineOf = (preset: PresetRecord) => asNumber(asRecord(preset.card?.primary_metric).value);
  const statuses = Array.from(new Set(presets.map(statusOf))).sort();
  const counts = presets.reduce<Record<string, number>>((acc, preset) => {
    const key = statusOf(preset);
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  const provenCount = presets.filter((preset) => baselineOf(preset) > 0).length;
  const rows = presets
    .filter((preset) => statusFilter === "all" || statusOf(preset) === statusFilter)
    .filter((preset) => benchFilter === "all" || (benchFilter === "proven") === (baselineOf(preset) > 0))
    .sort((a, b) => {
      if (sortKey === "baseline") return (baselineOf(a) - baselineOf(b)) * sortDir;
      const va = sortKey === "status" ? statusOf(a) : String(a[sortKey] ?? "");
      const vb = sortKey === "status" ? statusOf(b) : String(b[sortKey] ?? "");
      return va.localeCompare(vb) * sortDir;
    });

  const toggleSort = (key: "id" | "model" | "status" | "baseline") => {
    if (sortKey === key) setSortDir((dir) => (dir === 1 ? -1 : 1));
    // Baseline defaults to descending — operators want the fastest presets first.
    else { setSortKey(key); setSortDir(key === "baseline" ? -1 : 1); }
  };
  const caret = (key: string) => (sortKey === key ? (sortDir === 1 ? " ↑" : " ↓") : "");

  return (
    <div className="preset-catalog">
      <div className="filter-chips">
        <button className={statusFilter === "all" ? "active" : ""} onClick={() => setStatusFilter("all")}>
          {tr("All")} <em>{presets.length}</em>
        </button>
        {statuses.map((status) => (
          <button key={status} className={statusFilter === status ? "active" : ""} onClick={() => setStatusFilter(status)}>
            {status.replace(/_/g, " ")} <em>{counts[status]}</em>
          </button>
        ))}
        <span className="filter-chips-sep" aria-hidden="true" />
        <span className="filter-chips-label">{tr("Baseline")}</span>
        <button className={benchFilter === "all" ? "active" : ""} onClick={() => setBenchFilter("all")}>{tr("any")} <em>{presets.length}</em></button>
        <button className={benchFilter === "proven" ? "active" : ""} onClick={() => setBenchFilter("proven")}>{tr("bench-proven")} <em>{provenCount}</em></button>
        <button className={benchFilter === "pending" ? "active" : ""} onClick={() => setBenchFilter("pending")}>{tr("pending")} <em>{presets.length - provenCount}</em></button>
      </div>
      <div className="catalog-scroll">
        <table className="module-table">
          <thead>
            <tr>
              <th className="sortable" onClick={() => toggleSort("id")}>{tr("Preset")}{caret("id")}</th>
              <th className="sortable" onClick={() => toggleSort("model")}>{tr("Model")}{caret("model")}</th>
              <th>{tr("Hardware")}</th>
              <th>{tr("Profile")}</th>
              <th className="sortable" onClick={() => toggleSort("status")}>{tr("Card")}{caret("status")}</th>
              <th className="sortable" onClick={() => toggleSort("baseline")}>{tr("Baseline")}{caret("baseline")}</th>
              <th aria-label={tr("Actions")} />
            </tr>
          </thead>
          <tbody>
            {rows.map((preset) => (
              <tr
                className={`preset-catalog-row ${preset.id === selectedPreset ? "selected-row" : ""}`}
                key={preset.id}
                onClick={() => onPreset(preset.id)}
              >
                <td>
                  <button className="link-button" onClick={(event) => { event.stopPropagation(); onPreset(preset.id); }}>
                    {preset.id === selectedPreset && <ChevronRight size={13} className="row-active-caret" />}
                    {preset.id}
                  </button>
                </td>
                <td>{preset.model}</td>
                <td>{preset.hardware}</td>
                <td>{preset.profile ?? "-"}</td>
                <td><StatusBadge status={statusOf(preset)} /></td>
                <td><PresetBaselineCell card={preset.card} /></td>
                <td className="preset-row-actions">
                  {onEdit && (
                    <button
                      className="icon-button"
                      title={`${tr("Edit")} ${preset.id}`}
                      aria-label={`${tr("Edit")} ${preset.id}`}
                      onClick={(event) => { event.stopPropagation(); onEdit(preset.id); }}
                    >
                      <Wrench size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (() => {
              const filtered = statusFilter !== "all" || benchFilter !== "all";
              return (
              <tr><td colSpan={7}>
                <EmptyState
                  icon={<Database size={22} />}
                  title={tr("No presets for this filter")}
                  message={filtered ? tr("No presets match the active filters.") : tr("The preset catalog is empty.")}
                  action={filtered ? { label: tr("Clear filters"), icon: <X size={14} />, onClick: () => { setStatusFilter("all"); setBenchFilter("all"); } } : undefined}
                />
              </td></tr>
              );
            })()}
          </tbody>
        </table>
      </div>
    </div>
  );
}
