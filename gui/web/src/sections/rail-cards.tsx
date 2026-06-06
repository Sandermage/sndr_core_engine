// SPDX-License-Identifier: Apache-2.0
// Launch-plan rail cards: runtime endpoints, benchmark expectation, evidence
// status, and the patch-policy matrix. Extracted from App.tsx (modularization)
// with no behavior change.
import { useState } from "react";
import { Link2, Activity, ShieldCheck, PackageCheck, ChevronDown } from "lucide-react";
import { type LaunchPlanEndpoint, type PatchListResult } from "../api";
import { RailStat, RailCheck } from "../components/primitives";
import { CopyButton } from "../components/code-block";
import { formatTokens } from "../lib/format";

export function RuntimeEndpoint({
  host,
  endpoints
}: {
  host: string;
  endpoints?: LaunchPlanEndpoint[];
}) {
  const rows: Array<[string, string]> = endpoints?.length
    ? endpoints.map((endpoint) => [endpoint.label, endpoint.url])
    : [
        ["OpenAI API", `http://${host}:8000/v1`],
        ["Metrics", `http://${host}:8001/metrics`],
        ["Health", `http://${host}:8000/health`],
        ["Docs", `http://${host}:8000/docs`]
      ];
  return (
    <section className="rail-card">
      <h3>
        <Link2 size={16} />
        Runtime Endpoint
      </h3>
      {rows.map(([label, value]) => (
        <label className="endpoint-field" key={label}>
          <span>{label}</span>
          <div>
            <input value={value} readOnly />
            <CopyButton value={value} label={label} />
          </div>
        </label>
      ))}
    </section>
  );
}

export function BenchmarkCard({
  metricKind,
  metricValue,
  context,
  visibility,
  busy,
  onRun
}: {
  metricKind: string;
  metricValue: number;
  context: number;
  visibility: string;
  busy?: boolean;
  onRun?: () => void;
}) {
  return (
    <section className="rail-card">
      <h3>
        <Activity size={16} />
        Benchmark Expectation
      </h3>
      <RailStat label={metricKind} value={metricValue > 0 ? String(metricValue) : "pending"} />
      <RailStat label="Context" value={formatTokens(context)} />
      <RailStat label="Acceptance" value={metricValue > 0 ? "catalog baseline" : "needs proof"} />
      <RailStat label="Confidence" value={visibility === "public" ? "High" : "Medium"} />
      {onRun && (
        <button className="rail-action" onClick={onRun} disabled={busy}>
          <Activity size={14} /> {busy ? "Queuing…" : "Run benchmark"}
        </button>
      )}
    </section>
  );
}

export function EvidenceCard({
  visibility,
  evidenceCount,
  busy,
  onAttach
}: {
  visibility: string;
  evidenceCount: number;
  busy?: boolean;
  onAttach?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const isPublic = visibility === "public";
  return (
    <section className="rail-card">
      <h3>
        <ShieldCheck size={16} />
        Evidence Status
      </h3>
      <RailCheck label="Static Proof (catalog)" value="Verified" status="pass" />
      <RailCheck label="Benchmark Baseline" value={evidenceCount > 0 ? "Available" : "Missing"} status={evidenceCount > 0 ? "pass" : "warning"} />
      <RailCheck
        label="Release Check"
        value={evidenceCount > 0 ? (isPublic ? "Ready" : "Private evidence") : "No evidence"}
        status={evidenceCount > 0 && isPublic ? "pass" : "warning"}
      />
      <RailCheck label="Visibility" value={isPublic ? "Public" : "Private"} status={isPublic ? "pass" : "warning"} />
      {open && (
        <div className="rail-expand">
          <p>{evidenceCount} evidence reference{evidenceCount === 1 ? "" : "s"} attached to this preset.</p>
          <p>
            {isPublic
              ? "Visibility is public — evidence can ship in release proofs as-is."
              : "Visibility is private — redact before publishing externally."}
          </p>
        </div>
      )}
      <div className="rail-card-foot">
        <button className="ghost-button" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide details" : "Show details"}
        </button>
        {onAttach && (
          <button className="rail-action" onClick={onAttach} disabled={busy}>
            <ShieldCheck size={14} /> {busy ? "Queuing…" : "Attach evidence"}
          </button>
        )}
      </div>
    </section>
  );
}

export function PatchMatrix({
  summary,
  registryTotal,
  selectedCount,
  onExplain
}: {
  summary: PatchListResult["summary"] | null;
  registryTotal: number;
  selectedCount: number;
  onExplain: () => void;
}) {
  const [open, setOpen] = useState(false);
  const defaults = summary?.production_default_counts ?? {};
  const rows: Array<[string, number]> = [
    ["Applied", defaults.applied ?? 0],
    ["Marker", defaults.marker ?? 0],
    ["Opt-in", defaults["opt-in"] ?? 0],
    ["Blocked", defaults.blocked ?? 0],
    ["Plan enabled", selectedCount || 0]
  ];
  return (
    <section className="rail-card">
      <h3>
        <PackageCheck size={16} />
        Patch Policy Matrix
        <small>{registryTotal} in registry</small>
      </h3>
      <table className="mini-table">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>
                <span className={`matrix-dot ${label.toLowerCase().replace(/[^a-z]+/g, "-")}`} />
                {label}
              </td>
              <td>{value}</td>
              <td>
                <ChevronDown size={14} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && (
        <div className="rail-expand">
          <p><b>Applied</b> — default-on with a real apply module.</p>
          <p><b>Marker</b> — default-on, no runtime mutation.</p>
          <p><b>Opt-in</b> — off unless explicitly enabled.</p>
          <p><b>Blocked</b> — unsafe for production defaults.</p>
        </div>
      )}
      <div className="rail-actions">
        <button className="ghost-button" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide legend" : "Legend"}
        </button>
        <button className="ghost-button" onClick={onExplain}>Explain</button>
      </div>
    </section>
  );
}
