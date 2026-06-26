// SPDX-License-Identifier: Apache-2.0
// Project Operations console — surfaces sndr_core's canonical CLI maintenance
// workflows as one-click, live-monitored jobs. Commands are server-defined; the
// client only sends an operation id.
import { useEffect, useState, type ReactNode } from "react";
import { Terminal, Activity, ShieldCheck, AlertCircle, Play, Stethoscope, Database, PackageCheck } from "lucide-react";
import { api, type OperationsResult } from "../api";
import { ModuleGrid, ModuleCard } from "../components/layout";
import { toast } from "../components/toast";
import { SkeletonCards } from "../Skeleton";
import { tr } from "../i18n";

const OP_GROUP_ICON: Record<string, ReactNode> = {
  "Diagnostics": <Stethoscope size={18} />,
  "Registry audits": <ShieldCheck size={18} />,
  "Config & catalog": <Database size={18} />,
  "Proof & release": <PackageCheck size={18} />
};

export function OperationsConsole({ onMonitor }: { onMonitor: (id: string) => void }) {
  const [data, setData] = useState<OperationsResult | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.operations()
      .then((result) => { if (!cancelled) setData(result); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); });
    return () => { cancelled = true; };
  }, []);

  async function run(opId: string) {
    setBusy(opId);
    setError(null);
    try {
      const job = await api.operationRun(opId);
      onMonitor(job.job_id);
      toast(`${tr("Operation started:")} ${opId}`, "success");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast(`${tr("Operation failed:")} ${msg}`, "error");
    } finally {
      setBusy("");
    }
  }

  if (!data) return <ModuleGrid><ModuleCard title={tr("Operations")} icon={<Terminal size={18} />} wide>{error ? <p className="muted">{error}</p> : <SkeletonCards count={4} />}</ModuleCard></ModuleGrid>;

  const groups: string[] = [];
  data.operations.forEach((op) => { if (!groups.includes(op.group)) groups.push(op.group); });
  const applyOn = data.apply_enabled;

  return (
    <>
      <div className={`ops-banner ${applyOn ? "live" : "readonly"}`}>
        {applyOn ? <Activity size={16} /> : <ShieldCheck size={16} />}
        <div>
          <strong>{applyOn ? tr("Apply enabled — operations run live on this host") : tr("Read-only daemon — operations return a dry-run")}</strong>
          <span>{applyOn
            ? tr("Each run executes the sndr_core CLI as a background job; watch it live in the monitor.")
            : tr("Commands are mirrored so you can copy them. Start the daemon with --enable-apply to run them here.")}</span>
        </div>
      </div>
      {error && <div className="inline-error"><AlertCircle size={15} /> {error}</div>}
      <ModuleGrid className="stretch-row">
        {groups.map((group) => (
          <ModuleCard key={group} title={group} icon={OP_GROUP_ICON[group] ?? <Terminal size={18} />} desc={`${data.operations.filter((op) => op.group === group).length} ${tr("operations")}`}>
            <div className="ops-list">
              {data.operations.filter((op) => op.group === group).map((op) => (
                <div className="ops-row" key={op.id}>
                  <div className="ops-row-text">
                    <strong>{op.label}</strong>
                    <small>{op.description}</small>
                    <code>{op.command.replace(/^\S*python\S*\s+-m\s+/, "")}</code>
                  </div>
                  <div className="ops-row-action">
                    <span className="ops-est">{op.estimate}</span>
                    <button className="primary-action" onClick={() => void run(op.id)} disabled={busy === op.id}>
                      <Play size={14} /> {busy === op.id ? tr("Starting…") : tr("Run")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </ModuleCard>
        ))}
      </ModuleGrid>
    </>
  );
}
