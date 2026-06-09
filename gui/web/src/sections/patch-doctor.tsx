// SPDX-License-Identifier: Apache-2.0
// Patch-doctor section panels: apply-module coverage + validation drill-down,
// and the admin API surface matrix.
import { useState } from "react";
import { type PatchDoctorReport, type ProductCapability } from "../api";
import { StatusBadge, InfoRows } from "../components/primitives";
import { PercentBar } from "../components/charts";
import { tr } from "../i18n";

export function DoctorCoveragePanel({ report }: { report: PatchDoctorReport | null }) {
  const coverage = report?.coverage;
  const total = coverage?.total ?? 0;
  const mapped = coverage?.mapped ?? 0;
  const issues = report?.issues ?? [];
  const [sev, setSev] = useState<"" | "ERROR" | "WARNING" | "INFO">("");
  const order: Record<string, number> = { ERROR: 0, WARNING: 1, INFO: 2 };
  const counts = issues.reduce<Record<string, number>>((a, i) => { a[i.severity] = (a[i.severity] ?? 0) + 1; return a; }, {});
  const shown = [...issues]
    .filter((i) => !sev || i.severity === sev)
    .sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  const unmapped = coverage?.unmapped ?? [];
  return (
    <div className="doctor-coverage">
      <PercentBar value={mapped} max={total} label={tr("apply modules mapped")} caption={`${mapped} ${tr("of")} ${total} ${tr("patches")}`} tone="accent" />
      <InfoRows
        rows={[
          [tr("Registry Size"), report?.registry_size ?? "-"],
          [tr("Validation Issues"), issues.length],
          [tr("Mapped"), coverage?.mapped ?? "-"],
          [tr("Intentionally Unmapped"), coverage?.intentionally_unmapped.length ?? "-"],
          [tr("Unmapped"), unmapped.length]
        ]}
      />

      {issues.length > 0 && (
        <div className="audit-drill">
          <div className="audit-drill-bar">
            <strong>{tr("Validation issues")}</strong>
            {(["ERROR", "WARNING", "INFO"] as const).map((s) => (counts[s] ? (
              <button key={s} className={`audit-sevchip ${s.toLowerCase()} ${sev === s ? "active" : ""}`}
                onClick={() => setSev(sev === s ? "" : s)}>{tr(s.toLowerCase())} {counts[s]}</button>
            ) : null))}
            {sev && <button className="audit-clear" onClick={() => setSev("")}>{tr("clear")}</button>}
          </div>
          <div className="audit-list">
            {shown.slice(0, 200).map((i, idx) => (
              <div key={`${i.patch_id}-${idx}`} className={`audit-issue ${i.severity.toLowerCase()}`}>
                <span className={`audit-sev ${i.severity.toLowerCase()}`}>{tr(i.severity)}</span>
                <span className="audit-pid">{i.patch_id}</span>
                <span className="audit-msg">{i.message}</span>
              </div>
            ))}
            {shown.length > 200 && <div className="audit-more">+{shown.length - 200} {tr("more…")}</div>}
          </div>
        </div>
      )}

      {unmapped.length > 0 && (
        <div className="audit-drill">
          <div className="audit-drill-bar"><strong>{tr("Unmapped patches")}</strong> <span className="muted">({unmapped.length} {tr("— no apply_module")})</span></div>
          <div className="audit-chips">{unmapped.map((p) => <span key={p} className="audit-chip">{p}</span>)}</div>
        </div>
      )}
    </div>
  );
}

export function AdminSurfaceMatrix({
  featureRows,
  patchDoctor
}: {
  featureRows: ProductCapability[];
  patchDoctor: PatchDoctorReport | null;
}) {
  const rows: Array<[string, string, string, string]> = [
    [tr("Catalog"), "GET", "Ready", tr("models, hardware, profiles, presets")],
    [tr("Preset Workbench"), "GET", "Ready", tr("list, explain, recommend")],
    [tr("Patch Inventory"), "GET", "Ready", `${patchDoctor?.registry_size ?? "-"} ${tr("registry entries")}`],
    [tr("Patch Doctor"), "GET", "Ready", `${patchDoctor?.issues.length ?? "-"} ${tr("validation issues")}`],
    [tr("Service Lifecycle"), "POST", "Ready", tr("plan/apply start-stop (gated by --enable-apply + confirm)")],
    [tr("Launch Apply"), "POST", "Ready", tr("launch a preset (gated + confirm)")],
    [tr("Jobs and Events"), "GET/SSE", "Ready", tr("dry-run/executed jobs + /events stream")],
    [tr("Reports"), "POST", "Ready", tr("redacted bundle generation to $SNDR_HOME")],
    [tr("Bench / Evidence"), "POST", "Ready", tr("queue dry-run jobs (full runs on rig)")],
    [tr("Remote Host Profiles"), "GET/POST/DELETE", "Ready", tr("operator-local profiles + SSH tunnel command")]
  ];
  const featureStatus = new Map(featureRows.map((feature) => [feature.id, feature.status]));
  return (
    <table className="module-table">
      <thead>
        <tr>
          <th>{tr("Surface")}</th>
          <th>{tr("Transport")}</th>
          <th>{tr("Status")}</th>
          <th>{tr("Contract")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([surface, transport, status, contract]) => (
          <tr key={surface}>
            <td><strong>{surface}</strong></td>
            <td>{transport}</td>
            <td><StatusBadge status={status === "Ready" ? "available" : featureStatus.get("service_lifecycle") ?? "deferred"} /></td>
            <td>{contract}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
