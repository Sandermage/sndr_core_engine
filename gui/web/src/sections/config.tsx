// SPDX-License-Identifier: Apache-2.0
// Config section panels: preset diff (compare) + read-only apply plan + apply
// result. Extracted from App.tsx (modularization) with no behavior change.
import { useState } from "react";
import { GitBranch, AlertCircle } from "lucide-react";
import { api } from "../api";
import {
  type V2ConfigItem,
  type V2ConfigPlan,
  type V2ConfigApplyResult,
  type PresetExplainResult
} from "../api";
import { StatusBadge, InfoRows, CompactList } from "../components/primitives";
import { CodeBlock } from "../components/code-block";

export function ConfigComparePanel({ presets }: { presets: V2ConfigItem[] }) {
  const [aId, setAId] = useState(presets[0]?.id ?? "");
  const [bId, setBId] = useState(presets[1]?.id ?? presets[0]?.id ?? "");
  const [left, setLeft] = useState<PresetExplainResult | null>(null);
  const [right, setRight] = useState<PresetExplainResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diffOnly, setDiffOnly] = useState(true);
  const fmt = (value: unknown) => value === undefined || value === null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);

  async function run() {
    if (!aId || !bId || aId === bId) return;
    setLoading(true);
    setError(null);
    try {
      const [la, ra] = await Promise.all([api.explainPreset(aId), api.explainPreset(bId)]);
      setLeft(la);
      setRight(ra);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const allKeys = left && right ? Array.from(new Set([...Object.keys(left.composed), ...Object.keys(right.composed)])).sort() : [];
  const isDiff = (key: string) => fmt(left?.composed[key]) !== fmt(right?.composed[key]);
  const diffCount = allKeys.filter(isDiff).length;
  const rows = diffOnly ? allKeys.filter(isDiff) : allKeys;

  return (
    <div className="cfg-compare">
      <div className="cfg-compare-bar">
        <label className="param-field"><span>Preset A</span>
          <select value={aId} onChange={(event) => setAId(event.target.value)}>
            {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.id}</option>)}
          </select>
        </label>
        <GitBranch size={16} className="cfg-compare-vs" />
        <label className="param-field"><span>Preset B</span>
          <select value={bId} onChange={(event) => setBId(event.target.value)}>
            {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.id}</option>)}
          </select>
        </label>
        <button className="primary-action" onClick={() => void run()} disabled={loading || aId === bId}>
          <GitBranch size={15} /> {loading ? "Comparing…" : "Compare"}
        </button>
      </div>
      {aId === bId && <p className="muted">Pick two different presets to compare.</p>}
      {error && <div className="config-plan-error"><AlertCircle size={15} /><span>{error}</span></div>}
      {left && right && (
        <>
          <div className="cfg-compare-meta">
            <span className={diffCount > 0 ? "fleet-status danger" : "fleet-status ok"}><span className="fleet-dot" />{diffCount} of {allKeys.length} parameters differ</span>
            <label className="cfg-compare-toggle">
              <input type="checkbox" checked={diffOnly} onChange={(event) => setDiffOnly(event.target.checked)} /> differences only
            </label>
          </div>
          <div className="patch-table-scroll">
            <table className="module-table cfg-compare-table">
              <thead><tr><th>Parameter</th><th>{left.id}</th><th>{right.id}</th></tr></thead>
              <tbody>
                {rows.map((key) => (
                  <tr key={key} className={isDiff(key) ? "cfg-diff" : ""}>
                    <td><em>{key}</em></td>
                    <td>{fmt(left.composed[key])}</td>
                    <td>{fmt(right.composed[key])}</td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={3} className="muted">Identical composed configuration.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!left && !error && <p className="muted">Select two presets and press Compare to diff their composed runtime configuration.</p>}
    </div>
  );
}

export function ConfigPlanPanel({ plan }: { plan: V2ConfigPlan }) {
  const status = plan.valid ? "available" : "missing";
  const notes = [
    ...plan.blocked_reasons.map((item) => ["Blocked", item] as [string, string]),
    ...plan.warnings.map((item) => ["Warning", item] as [string, string])
  ];
  return (
    <section className="config-plan-panel">
      <div className="config-plan-head">
        <div>
          <strong>{plan.plan_id}</strong>
          <span>{plan.action} / read-only plan / apply disabled</span>
        </div>
        <StatusBadge status={status} />
      </div>
      <InfoRows
        rows={[
          ["Preset", plan.preset_id],
          ["Target", plan.target_path],
          ["Backup", plan.backup_path ?? "-"],
          ["Apply", plan.apply_enabled ? "enabled" : "disabled"]
        ]}
      />
      {notes.length > 0 && <CompactList rows={notes} />}
      <CompactList rows={[["Pipeline", `${plan.steps.length} guarded steps: validate, render, diff, require explicit apply.`]]} />
      <CodeBlock lines={plan.diff_lines.length ? plan.diff_lines : ["# No file diff"]} />
    </section>
  );
}

export function ConfigApplyPanel({ result }: { result: V2ConfigApplyResult }) {
  const tone =
    result.status === "applied" ? "available" : result.status === "conflict" ? "partial" : "missing";
  return (
    <section className="config-plan-panel apply">
      <div className="config-plan-head">
        <div>
          <strong>{result.status === "applied" ? "Applied to disk" : result.status}</strong>
          <span>{result.message}</span>
        </div>
        <StatusBadge status={tone} />
      </div>
      <InfoRows
        rows={[
          ["Target", result.target_path],
          ["Backup", result.backup_path ?? "-"],
          ["Action", result.action],
          ["Bytes", String(result.bytes_written || 0)]
        ]}
      />
      {result.blocked_reasons.length > 0 && (
        <CompactList rows={result.blocked_reasons.map((reason) => ["Blocked", reason] as [string, string])} />
      )}
    </section>
  );
}
