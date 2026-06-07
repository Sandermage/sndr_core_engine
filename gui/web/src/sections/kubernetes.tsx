// SPDX-License-Identifier: Apache-2.0
// Kubernetes mode (read-only, P1) — cluster status + nodes with GPU. Degrades to
// a clear "connect a cluster" card when no kubeconfig/client is configured (the
// operator's setup is Docker by default, so this is the common state).
import { useEffect, useState } from "react";
import { Boxes, Cpu, RefreshCw, Loader2, AlertTriangle, ShieldCheck, ShieldAlert, Server } from "lucide-react";
import { api, type K8sStatus, type K8sNode } from "../api";

export function KubernetesPanel() {
  const [status, setStatus] = useState<K8sStatus | null>(null);
  const [nodes, setNodes] = useState<K8sNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true); setErr(null);
    try {
      const s = await api.k8sStatus();
      setStatus(s);
      if (s.available) setNodes((await api.k8sNodes()).nodes);
      else setNodes(null);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  return (
    <div className="k8s">
      <div className="section-head">
        <div><h2><Boxes size={18} /> Kubernetes</h2><p className="muted">Read-only cluster view — honours your kubeconfig &amp; RBAC.</p></div>
        <button className="ghost-button" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>

      {err && <div className="containers-err"><AlertTriangle size={13} /> {err}</div>}

      {!status ? <div className="containers-empty"><Loader2 size={20} className="spin" /></div>
        : !status.available ? (
          <div className="k8s-disconnected">
            <Server size={24} />
            <strong>No cluster connected</strong>
            <p className="muted">{status.error}</p>
            <p className="upd-hint">Install the client and point the daemon at a kubeconfig:</p>
            <code className="apply-gate-cmd">pip install 'vllm-sndr-core[k8s]'  ·  export KUBECONFIG=/path/to/config</code>
          </div>
        ) : (
          <>
            <div className="k8s-kpis">
              <Kpi label="Server" value={status.version ?? "—"} />
              <Kpi label="Nodes" value={`${status.nodes_ready ?? 0}/${status.node_count ?? 0} ready`} />
              <Kpi label="GPU nodes" value={String(status.gpu_node_count ?? 0)} accent />
              <Kpi label="Namespaces" value={String(status.namespace_count ?? 0)} />
            </div>

            <div className="containers-table-wrap">
              <table className="containers-table">
                <thead>
                  <tr><th>Node</th><th>Status</th><th>Roles</th><th>Kubelet</th><th>GPU (free / alloc)</th><th>GPU labels</th><th>Taints</th></tr>
                </thead>
                <tbody>
                  {(nodes ?? []).map((n) => <NodeRow key={n.name} n={n} />)}
                </tbody>
              </table>
            </div>
            {nodes && nodes.length === 0 && <div className="containers-empty"><strong>Cluster has no nodes</strong></div>}
          </>
        )}
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return <div className={`k8s-kpi${accent ? " accent" : ""}`}><span className="k8s-kpi-label">{label}</span><b>{value}</b></div>;
}

function NodeRow({ n }: { n: K8sNode }) {
  const gpuAlloc = n.gpu_allocatable ?? 0;
  const gpuFree = n.gpu_free ?? gpuAlloc;
  const hasGpu = gpuAlloc > 0;
  const st = n.ready ? (n.schedulable ? "online" : "partial") : "offline";
  return (
    <tr className={`crow ${st}`}>
      <td className="crow-name"><span className={`container-dot ${st}`} />{n.name}</td>
      <td>
        <span className={`container-badge ${st}`}>{n.ready ? (n.schedulable ? "Ready" : "Ready (cordoned)") : "NotReady"}</span>
        {n.pressures.map((p) => <span key={p} className="k8s-pressure" title={`${p} = True`}><ShieldAlert size={10} /> {p.replace("Pressure", "")}</span>)}
      </td>
      <td className="muted">{n.roles.join(", ") || "—"}</td>
      <td className="muted">{n.kubelet_version ?? "—"}</td>
      <td>
        {hasGpu
          ? <span className={`k8s-gpu ${gpuFree === 0 ? "full" : "free"}`}><Cpu size={11} /> {gpuFree} / {gpuAlloc}{n.gpu_requested ? ` · ${n.gpu_requested} used` : ""}</span>
          : <span className="muted">—</span>}
      </td>
      <td className="muted k8s-gpulabels" title={Object.entries(n.gpu_labels).map(([k, v]) => `${k}=${v}`).join("\n")}>
        {n.gpu_labels["nvidia.com/gpu.product"] ?? (Object.keys(n.gpu_labels).length ? `${Object.keys(n.gpu_labels).length} labels` : "—")}
      </td>
      <td className="muted">{n.taints.length ? n.taints.map((t) => t.key).join(", ") : <ShieldCheck size={12} />}</td>
    </tr>
  );
}
