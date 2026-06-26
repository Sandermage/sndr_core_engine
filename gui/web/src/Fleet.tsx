import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Box, ChevronRight, Cpu, Heart, Link2, Loader2, RefreshCw, Server, ShieldCheck } from "lucide-react";
import { api, type FleetHost } from "./api";
import { SkeletonCards } from "./Skeleton";
import { tr } from "./i18n";

type Status = "online" | "partial" | "offline";

function statusOf(h: FleetHost): Status {
  if (!h.ssh_ok && (h.error || h.engines.length === 0)) return "offline";
  if (h.engines.some((e) => e.reachable)) return "online";
  return "partial";  // SSH reachable but no engine answering
}
const STATUS_LABEL: Record<Status, string> = { online: "online", partial: "ssh only", offline: "offline" };

const mib = (v: string | null | undefined) => parseInt(v || "0", 10) || 0;
const gpb = (m: number) => Math.round(m / 1024); // MiB -> GiB
const pct = (v: string | null | undefined) => Math.max(0, Math.min(100, parseInt(v || "0", 10) || 0));
const shortGpu = (name: string) => name.replace(/^NVIDIA\s+/i, "").replace(/\s+(GPU|Graphics)$/i, "");
const shortVer = (v: string) => v.replace(/^(\d+\.\d+\.\d+).*/, "$1");

// Fleet overview — every registered engine host. Read-only: nothing here
// mutates a server.
export function FleetPanel({ onOpenHost }: { onOpenHost: (id: string) => void }) {
  const [hosts, setHosts] = useState<FleetHost[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const loadingRef = useRef(false);
  loadingRef.current = loading;

  async function load() {
    setLoading(true); setErr(null);
    try { setHosts((await api.fleetOverview()).hosts); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  // Auto-refresh the sweep every 60s (skip while one is in flight or tab hidden,
  // so we don't pile up SSH connections to the fleet).
  useEffect(() => {
    const t = window.setInterval(() => { if (!loadingRef.current && !document.hidden) void load(); }, 60000);
    return () => window.clearInterval(t);
     
  }, []);

  const online = (hosts || []).filter((h) => statusOf(h) === "online").length;
  const totalGpus = (hosts || []).reduce((n, h) => n + h.gpu_count, 0);
  const totalPatches = (hosts || []).reduce((n, h) => n + h.active_patches, 0);

  return (
    <div className="fleet">
      <div className="fleet-bar">
        <div className="fleet-stats">
          <span className="fleet-stat"><b>{hosts ? hosts.length : "—"}</b> {tr("servers")}</span>
          <span className="fleet-stat ok"><b>{online}</b> {tr("online")}</span>
          <span className="fleet-stat"><b>{totalGpus}</b> GPUs</span>
          <span className="fleet-stat"><b>{totalPatches}</b> {tr("live patches")}</span>
        </div>
        <span className="fleet-auto">{tr("auto")} · 60s</span>
        <button className="ghost-button" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} {tr("Refresh fleet")}
        </button>
      </div>
      {err && <div className="fleet-err"><AlertTriangle size={14} /> {err}</div>}

      {hosts !== null && hosts.length === 0 && (
        <div className="fleet-empty"><Server size={22} /><strong>{tr("No engine hosts yet")}</strong>
          <span>{tr("Add a GPU server in")} <b>{tr("Hosts")}</b> — {tr("it shows up here with its live state.")}</span></div>
      )}

      {loading && hosts === null && <SkeletonCards count={4} />}

      <div className="fleet-overview-grid">
        {(hosts || []).map((h) => {
          const st = statusOf(h);
          return (
            <button key={h.id} className={`fleet-server ${st}`} onClick={() => onOpenHost(h.id)} title={tr("Open this host's card")}>
              <div className="fleet-server-head">
                <span className={`fleet-server-dot ${st}`} />
                <strong>{h.label}</strong>
                {h.role && <span className="fleet-server-role">{h.role}</span>}
                <span className="fleet-server-status">{tr(STATUS_LABEL[st])}</span>
                <ChevronRight size={15} className="fleet-server-go" />
              </div>
              <code className="fleet-server-host">{h.host}</code>

              {h.error && <div className="fleet-server-err"><AlertTriangle size={12} /> {h.error}</div>}

              {h.gpus.length > 0 && (() => {
                const totalVram = h.gpus.reduce((n, g) => n + mib(g.memory_total_mib), 0);
                return (
                  <div className="fleet-gpu">
                    <div className="fleet-gpu-head">
                      <Cpu size={12} /> {h.gpus.length}× {shortGpu(h.gpus[0]!.name)}
                      {totalVram > 0 && <span className="fleet-gpu-vram">{gpb(totalVram)} GB</span>}
                      {h.interconnect && <span className="fleet-gpu-ic"><Link2 size={10} /> {h.interconnect}</span>}
                    </div>
                    <div className="fleet-gpu-bars">
                      {h.gpus.map((g, i) => {
                        const u = pct(g.utilization);
                        return (
                          <div key={i} className="fleet-gpu-bar" title={`GPU ${i} · ${shortGpu(g.name)} · ${gpb(mib(g.memory_total_mib))}GB · ${u}% ${tr("util")}`}>
                            <div className="fleet-gpu-fill" style={{ width: `${Math.max(u, 2)}%` }} />
                            <span>{u}%</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}

              {h.engines.length > 0 && (
                <div className="fleet-eng">
                  <div className="fleet-eng-head"><Box size={11} /> {h.engines.length} {h.engines.length > 1 ? tr("containers") : tr("container")}</div>
                  {h.engines.slice(0, 4).map((e, i) => (
                    <div key={i} className="fleet-eng-row" title={`${e.container ?? tr("container")}${e.port ? " · :" + e.port : ""} · ${e.reachable ? tr("reachable") : tr("not reachable")}`}>
                      <span className={`fleet-eng-dot ${e.reachable ? "up" : "down"}`} />
                      <code className="fleet-eng-name">{e.container ?? "—"}</code>
                      {e.port && <span className="fleet-eng-port">:{e.port}</span>}
                      {e.reachable && e.version && <span className="fleet-eng-ver">{shortVer(e.version)}</span>}
                      {e.patches > 0 && <span className="fleet-eng-patches"><ShieldCheck size={9} /> {e.patches}</span>}
                    </div>
                  ))}
                </div>
              )}

              {h.models.length > 0 && (
                <div className="fleet-server-models">{h.models.map((m) => <span key={m} className="fleet-server-model" title={m}><Box size={10} />{m.split("/").pop()}</span>)}</div>
              )}

              <div className="fleet-server-meta">
                {h.vllm_version && <span title={tr("vLLM build")}><Heart size={11} /> vLLM {shortVer(h.vllm_version)}</span>}
                {h.active_patches > 0 && <span className="fleet-server-patches" title={tr("active Genesis patches")}><ShieldCheck size={11} /> {h.active_patches} {tr("patches")}</span>}
                <span className="fleet-server-open"><ChevronRight size={11} /> {tr("open host card")}</span>
              </div>
            </button>
          );
        })}
      </div>

      {(hosts || []).length > 0 && <FleetDeployPlanner hosts={hosts!} />}
    </div>
  );
}

// Fleet deploy orchestrator — render the install plan for one preset/target
// across N selected hosts at once. Read-only (dry-run): the actual apply stays
// per-host in the Hosts/Setup flow, which is apply+confirm gated.
function FleetDeployPlanner({ hosts }: { hosts: FleetHost[] }) {
  const [presets, setPresets] = useState<{ id: string; title?: string }[]>([]);
  const [targets, setTargets] = useState<{ id: string; label?: string }[]>([]);
  const [preset, setPreset] = useState("");
  const [target, setTarget] = useState("");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [plan, setPlan] = useState<import("./api").FleetDeployPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.presets({}).then((r) => {
      const list = (r.presets || []).map((p: Record<string, unknown>) => ({ id: String(p.id), title: p.title ? String(p.title) : undefined }));
      setPresets(list);
      if (list[0]) setPreset(list[0].id);
    }).catch(() => {});
    api.deployTargets().then((r) => {
      const list = (r.targets || []).map((t: Record<string, unknown>) => ({ id: String(t.id), label: t.label ? String(t.label) : undefined }));
      setTargets(list);
      if (list[0]) setTarget(list[0].id);
    }).catch(() => {});
  }, []);

  const chosen = hosts.filter((h) => picked[h.id]).map((h) => h.id);
  async function runPlan() {
    if (!preset || !target || chosen.length === 0) return;
    setBusy(true); setErr(null); setPlan(null);
    try { setPlan(await api.fleetDeployPlan({ preset_id: preset, target, host_ids: chosen })); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="fleet-deploy">
      <div className="fleet-deploy-head"><Server size={15} /> <strong>{tr("Deploy to fleet")}</strong> <span className="muted">— {tr("dry-run plan across N hosts")}</span></div>
      <div className="fleet-deploy-controls">
        <label>{tr("Preset")}
          <select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {presets.map((p) => <option key={p.id} value={p.id}>{p.title || p.id}</option>)}
          </select>
        </label>
        <label>{tr("Target")}
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {targets.map((t) => <option key={t.id} value={t.id}>{t.label || t.id}</option>)}
          </select>
        </label>
        <button className="primary-button" disabled={busy || !preset || !target || chosen.length === 0} onClick={() => void runPlan()}>
          {busy ? <Loader2 size={14} className="spin" /> : <Server size={14} />} {tr("Plan deploy")} ({chosen.length})
        </button>
      </div>
      <div className="fleet-deploy-hosts">
        {hosts.map((h) => (
          <label key={h.id} className={`fleet-deploy-host ${picked[h.id] ? "on" : ""}`}>
            <input type="checkbox" checked={!!picked[h.id]} onChange={(e) => setPicked((m) => ({ ...m, [h.id]: e.target.checked }))} />
            {h.label} <span className="muted">{h.host}</span>
          </label>
        ))}
      </div>
      {err && <div className="fleet-err"><AlertTriangle size={14} /> {err}</div>}
      {plan && (
        <div className="fleet-deploy-result">
          <div className="fleet-deploy-rollup">
            <span className="chip ok">{plan.rollup.ready} {tr("ready")}</span>
            {plan.rollup.errors > 0 && <span className="chip danger">{plan.rollup.errors} {tr("errors")}</span>}
            <span className="chip">{plan.rollup.mutating_steps_total} {tr("mutating steps")}</span>
            <span className="muted">{plan.rollup.apply_enabled ? tr("apply enabled — run per-host in Hosts to execute") : tr("read-only daemon — plan only")}</span>
          </div>
          {plan.results.map((r) => (
            <div className={`fleet-deploy-row ${r.ok ? "ok" : "bad"}`} key={r.host_id}>
              <span className={`container-dot ${r.ok ? "online" : "offline"}`} />
              <strong>{r.label || r.host_id}</strong>
              {r.ok
                ? <span className="muted">{r.mutating_steps ?? 0} {tr("mutating steps")}</span>
                : <span className="fleet-deploy-err">{r.error}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
