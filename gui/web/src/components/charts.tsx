// SPDX-License-Identifier: Apache-2.0
// Lightweight, dependency-free chart/KPI primitives shared across panels.
// Props-only, no closure/data deps.
import { type ReactNode } from "react";
import { tr } from "../i18n";

export const CHART_PALETTE = [
  "var(--accent)",
  "var(--info)",
  "var(--warn)",
  "var(--ok)",
  "var(--danger)",
  "#a855f7",
  "#06b6d4",
  "#f472b6",
];

export type DonutSegment = { label: string; value: number; color?: string };

export function SegmentBar({
  segments,
  total,
  totalLabel,
}: {
  segments: DonutSegment[];
  total: number;
  totalLabel: string;
}) {
  const sum = total || segments.reduce((acc, seg) => acc + seg.value, 0) || 1;
  return (
    <div className="segment-chart">
      <div className="segment-head">
        <strong>{total}</strong>
        <span>{totalLabel}</span>
      </div>
      <div className="segment-track" role="img" aria-label={`${totalLabel} ${tr("distribution")}`}>
        {segments.map((seg, index) => (
          <span
            key={seg.label}
            style={{ width: `${(seg.value / sum) * 100}%`, background: seg.color ?? CHART_PALETTE[index % CHART_PALETTE.length] }}
            title={`${seg.label}: ${seg.value}`}
          />
        ))}
      </div>
      <div className="segment-legend">
        {segments.map((seg, index) => (
          <div key={seg.label}>
            <i style={{ background: seg.color ?? CHART_PALETTE[index % CHART_PALETTE.length] }} />
            <span>{seg.label.replace(/_/g, " ")}</span>
            <strong>{seg.value}</strong>
            <em>{Math.round((seg.value / sum) * 100)}%</em>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PercentBar({
  value,
  max,
  label,
  caption,
  tone = "ok",
}: {
  value: number;
  max: number;
  label: string;
  caption?: string;
  tone?: "ok" | "accent" | "warn" | "info";
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className={`percent-bar tone-${tone}`}>
      <div className="percent-head">
        <strong>{pct}<small>%</small></strong>
        <span>{label}</span>
      </div>
      <div className="percent-track">
        <span style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
      </div>
      {caption && <small className="percent-caption">{caption}</small>}
    </div>
  );
}

export function segmentsFromCounts(
  counts: Record<string, number>,
  colorMap?: Record<string, string>,
): DonutSegment[] {
  return Object.entries(counts)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value, color: colorMap?.[label] }));
}

export function BarList({ rows }: { rows: Array<[string, number, string]> }) {
  return (
    <div className="bar-list">
      {rows.map(([label, percent, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          <i><b style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} /></i>
        </div>
      ))}
    </div>
  );
}

export function OvKpi({
  icon,
  label,
  value,
  sub,
  tone,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  sub?: string;
  tone?: "ok" | "warn";
  onClick?: () => void;
}) {
  const Tag = onClick ? "button" : "div";
  // Content-aware value sizing: a short number ("15", "321") stays large and
  // punchy, but a long text value (a model id like "qwen3.6-35b-a3b-fp8", a
  // version, "16 findings", "reachable") shrinks so it reads on one/two lines
  // instead of wrapping into a blob. Length-bucketed so it's stable across
  // window sizes — the tile itself flexes via the auto-fit grid.
  const valStr = typeof value === "string" || typeof value === "number" ? String(value) : null;
  const valLen = valStr?.length ?? 0;
  const valSize = valStr == null ? undefined
    : valLen <= 4 ? 22
    : valLen <= 8 ? 18
    : valLen <= 14 ? 15
    : 13;
  return (
    // Layout: icon · (label + sub) on the left, the value pushed to the right so
    // a wide tile is filled rather than left-packed. `.ov-hero .ov-kpi` styles it.
    <Tag className={`ov-kpi ${tone ?? ""} ${onClick ? "clickable" : ""}`} onClick={onClick}>
      <span className="ov-kpi-icon">{icon}</span>
      <span className="ov-kpi-body">
        <span className="ov-kpi-label">{label}</span>
        {sub && <span className="ov-kpi-sub" title={sub}>{sub}</span>}
      </span>
      <strong className="ov-kpi-value" style={valSize ? { fontSize: valSize } : undefined}
        title={valStr ?? undefined}>{value}</strong>
    </Tag>
  );
}
