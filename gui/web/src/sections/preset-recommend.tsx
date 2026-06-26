// SPDX-License-Identifier: Apache-2.0
// Preset recommender — pick a workload + target hardware + concurrency, rank the
// catalogue presets that fit.
import { useEffect, useState } from "react";
import { Rocket, AlertCircle, FileText, Database } from "lucide-react";
import { api, type PresetRecommendResult } from "../api";
import { asText } from "../lib/coerce";
import { EmptyState } from "../components/empty-state";
import { PresetBaselineCell } from "./preset-catalog";
import { defaultRecommend, workloadChoices } from "../recommend";
import { tr } from "../i18n";

export function PresetRecommendPanel({
  hardwareOptions,
  workloadCounts,
  onSelect
}: {
  hardwareOptions: string[];
  workloadCounts: Record<string, number>;
  onSelect: (id: string) => void;
}) {
  const [workload, setWorkload] = useState("free_chat");
  const [hardware, setHardware] = useState(hardwareOptions[0] ?? defaultRecommend.hardware);
  const [concurrency, setConcurrency] = useState(8);
  const [top, setTop] = useState(5);
  const [result, setResult] = useState<PresetRecommendResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.recommendPresets({ workload, hardware, concurrency, top }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot load on mount
  useEffect(() => { void run(); }, []);

  return (
    <div className="preset-recommend">
      <div className="rec-workloads" role="group" aria-label={tr("Workload")}>
        {workloadChoices.map((choice) => (
          <button
            key={choice.id}
            className={workload === choice.id ? "active" : ""}
            aria-pressed={workload === choice.id}
            onClick={() => setWorkload(choice.id)}
          >
            {tr(choice.label)}<small>{workloadCounts[choice.id] ?? 0}</small>
          </button>
        ))}
      </div>
      <div className="rec-controls">
        <label className="param-field"><span>{tr("Target hardware")}</span>
          <select value={hardware} onChange={(event) => setHardware(event.target.value)}>
            {hardwareOptions.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <label className="param-field"><span>{tr("Concurrency")}</span>
          <input type="number" min={1} value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} />
        </label>
        <label className="param-field"><span>{tr("Top N")}</span>
          <input type="number" min={1} max={20} value={top} onChange={(event) => setTop(Number(event.target.value))} />
        </label>
        <button className="primary-action" onClick={() => void run()} disabled={loading}>
          <Rocket size={15} /> {loading ? tr("Ranking…") : tr("Recommend")}
        </button>
      </div>
      {error && <div className="config-plan-error"><AlertCircle size={15} /><span>{error}</span></div>}
      {result && (
        <>
          <div className="rec-summary">
            <span className={result.total_matches > 0 ? "fleet-status ok" : "fleet-status danger"}>
              <span className="fleet-dot" />{result.total_matches} {tr("of")} {result.total_candidates} {tr("candidates match")}
            </span>
          </div>
          {result.results.length > 0 ? (
            <div className="patch-table-scroll">
              <table className="module-table rec-table">
                <thead><tr><th scope="col">#</th><th scope="col">{tr("Preset")}</th><th scope="col">{tr("Model")}</th><th scope="col">{tr("Hardware")}</th><th scope="col">{tr("Profile")}</th><th scope="col">{tr("Baseline")}</th><th scope="col" aria-label={tr("Actions")} /></tr></thead>
                <tbody>
                  {result.results.map((rec) => (
                    <tr key={rec.id}>
                      <td><span className="rec-rank">{rec.rank}</span></td>
                      <td><strong>{rec.id}</strong>{asText(rec.card?.status, "") && <small className="rec-status">{asText(rec.card?.status, "")}</small>}</td>
                      <td>{rec.model}</td>
                      <td>{rec.hardware}</td>
                      <td>{rec.profile ?? "—"}</td>
                      <td><PresetBaselineCell card={rec.card} /></td>
                      <td><button className="ghost-button" onClick={() => onSelect(rec.id)}><FileText size={13} /> {tr("Inspect")}</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={<Database size={22} />}
              title={tr("No presets match")}
              message={tr("No preset fits this workload on the selected hardware. Try a different rig or workload above, or relax the concurrency target.")}
            />
          )}
        </>
      )}
    </div>
  );
}
