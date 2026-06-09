// SPDX-License-Identifier: Apache-2.0
// Doctor / diagnostics section panels: severity summary + collapsible findings.
// Extracted from App.tsx (modularization) with no behavior change.
import { useState } from "react";
import { ChevronRight, CheckCircle2, Circle, CircleAlert, AlertCircle } from "lucide-react";
import { type DoctorReport, type DoctorFinding } from "../api";
import { DoctorStat, CompactList } from "../components/primitives";
import { SegmentBar } from "../components/charts";
import { CodeBlock } from "../components/code-block";
import { tr } from "../i18n";

const SEVERITY_META: Record<string, { tone: string; label: string }> = {
  ok: { tone: "ok", label: tr("Healthy") },
  info: { tone: "info", label: tr("Info") },
  warning: { tone: "warn", label: tr("Warning") },
  blocked: { tone: "danger", label: tr("Blocked") }
};

export function DoctorSummary({ report }: { report: DoctorReport | null }) {
  if (!report) return <p className="muted">{tr("Running diagnostics…")}</p>;
  const s = report.summary;
  const segments = [
    { label: tr("healthy"), value: s.ok ?? 0, color: "var(--ok)" },
    { label: tr("info"), value: s.info ?? 0, color: "var(--info)" },
    { label: tr("warning"), value: s.warning ?? 0, color: "var(--warn)" },
    { label: tr("blocked"), value: s.blocked ?? 0, color: "var(--danger)" }
  ].filter((seg) => seg.value > 0);
  return (
    <div className="doctor-summary">
      <div className="doctor-stat-row">
        <DoctorStat tone="ok" value={s.ok ?? 0} label={tr("Healthy")} />
        <DoctorStat tone="info" value={s.info ?? 0} label={tr("Info")} />
        <DoctorStat tone="warn" value={s.warning ?? 0} label={tr("Warnings")} />
        <DoctorStat tone="danger" value={s.blocked ?? 0} label={tr("Blocked")} />
      </div>
      <SegmentBar segments={segments} total={report.findings.length} totalLabel={tr("checks run")} />
      {report.warnings.length > 0 && (
        <CompactList rows={report.warnings.map((w, index) => [`${tr("note")} ${index + 1}`, w] as [string, string])} />
      )}
    </div>
  );
}

export function DoctorFindings({ report }: { report: DoctorReport | null }) {
  if (!report) return <p className="muted">{tr("Running diagnostics…")}</p>;
  if (!report.findings.length) return <p className="muted">{tr("No findings.")}</p>;
  return (
    <div className="doctor-findings">
      {report.categories.map((category) => (
        <DoctorCategory
          key={category}
          category={category}
          items={report.findings.filter((finding) => finding.category === category)}
        />
      ))}
    </div>
  );
}

function DoctorCategory({ category, items }: { category: string; items: DoctorFinding[] }) {
  const hasBlocked = items.some((finding) => finding.severity === "blocked");
  const hasWarn = items.some((finding) => finding.severity === "warning");
  const [open, setOpen] = useState(hasBlocked || hasWarn);
  const worst = hasBlocked ? "blocked" : hasWarn ? "warning" : "ok";
  return (
    <section className={`doctor-category ${open ? "open" : ""}`}>
      <button className="doctor-cat-head" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <ChevronRight className="coll-caret" size={14} />
        <strong>{category}</strong>
        <span className="doctor-cat-count">{items.length}</span>
        <SeverityDot severity={worst} />
      </button>
      {open && (
        <div className="doctor-cat-body">
          {items.map((finding) => (
            <DoctorFindingRow key={`${finding.category}-${finding.id}`} finding={finding} />
          ))}
        </div>
      )}
    </section>
  );
}

function SeverityDot({ severity }: { severity: string }) {
  return <span className={`sev-dot sev-${SEVERITY_META[severity]?.tone ?? "info"}`} title={severity} />;
}

function DoctorFindingRow({ finding }: { finding: DoctorFinding }) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(finding.evidence || finding.action || finding.cli);
  return (
    <div className={`doctor-finding sev-${SEVERITY_META[finding.severity]?.tone ?? "info"} ${open ? "open" : ""}`}>
      <button className="doctor-finding-head" onClick={() => expandable && setOpen((value) => !value)} aria-expanded={open}>
        <span className="finding-icon">
          {finding.severity === "ok" && <CheckCircle2 size={15} />}
          {finding.severity === "info" && <Circle size={15} />}
          {finding.severity === "warning" && <CircleAlert size={15} />}
          {finding.severity === "blocked" && <AlertCircle size={15} />}
        </span>
        <div>
          <strong>{finding.title}</strong>
          <small>{finding.detail}</small>
        </div>
        <span className="finding-sev">{finding.severity}</span>
        {expandable && <ChevronRight className="coll-caret" size={14} />}
      </button>
      {open && (
        <div className="doctor-finding-body">
          {finding.evidence && <p><em>{tr("Evidence")}</em>{finding.evidence}</p>}
          {finding.action && <p><em>{tr("Action")}</em>{finding.action}</p>}
          {finding.cli && <CodeBlock lines={[finding.cli]} />}
        </div>
      )}
    </div>
  );
}
