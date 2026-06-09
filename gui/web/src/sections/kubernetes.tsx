// SPDX-License-Identifier: Apache-2.0
// Kubernetes mode (read-only, P1) — cluster status + nodes with GPU. Degrades to
// a clear "connect a cluster" card when no kubeconfig/client is configured (the
// operator's setup is Docker by default, so this is the common state).
import { useEffect, useState, type ReactNode } from "react";
import { Boxes, Cpu, RefreshCw, Loader2, AlertTriangle, ShieldCheck, ShieldAlert, Server, Info, ChevronDown, Rocket, Copy, Layers, Package } from "lucide-react";
import { api, type K8sStatus, type K8sNode, type K8sPod, type K8sEvent, type DeploymentPlan } from "../api";
import { onKeyActivate } from "../dialog";
import { tr } from "../i18n";

type K8sTab = "nodes" | "pods" | "events" | "deploy";

export function KubernetesPanel() {
  const [status, setStatus] = useState<K8sStatus | null>(null);
  const [nodes, setNodes] = useState<K8sNode[] | null>(null);
  const [pods, setPods] = useState<K8sPod[] | null>(null);
  const [events, setEvents] = useState<K8sEvent[] | null>(null);
  const [tab, setTab] = useState<K8sTab>("nodes");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true); setErr(null);
    try {
      const s = await api.k8sStatus();
      setStatus(s);
      if (s.available) {
        const [n, p, e] = await Promise.all([api.k8sNodes(), api.k8sPods(), api.k8sEvents()]);
        setNodes(n.nodes); setPods(p.pods); setEvents(e.events);
      } else { setNodes(null); setPods(null); setEvents(null); }
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  const clusterGated = (body: ReactNode) =>
    !status ? <div className="containers-empty"><Loader2 size={20} className="spin" /></div>
      : !status.available ? <ConnectCard error={status.error} /> : body;

  return (
    <div className="k8s">
      <div className="section-head">
        <div><h2><Boxes size={18} /> Kubernetes</h2><p className="muted">{tr("Monitor your cluster and deploy vLLM to it — honours your kubeconfig & RBAC.")}</p></div>
        <button className="ghost-button" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} {tr("Refresh")}
        </button>
      </div>

      <K8sIntro available={status?.available} />
      {err && <div className="containers-err"><AlertTriangle size={13} /> {err}</div>}

      {status?.available && (
        <div className="k8s-kpis">
          <Kpi label={tr("Server")} value={status.version ?? "—"} />
          <Kpi label={tr("Nodes")} value={`${status.nodes_ready ?? 0}/${status.node_count ?? 0} ${tr("ready")}`} />
          <Kpi label={tr("GPU nodes")} value={String(status.gpu_node_count ?? 0)} accent />
          <Kpi label={tr("Namespaces")} value={String(status.namespace_count ?? 0)} />
        </div>
      )}

      <div className="k8s-tabs">
        {(["nodes", "pods", "events", "deploy"] as K8sTab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "deploy" ? tr("deploy vLLM") : tr(t)}
            {t === "nodes" && nodes ? ` (${nodes.length})` : ""}{t === "pods" && pods ? ` (${pods.length})` : ""}
            {t === "events" && events ? ` (${events.filter((e) => e.type === "Warning").length}⚠)` : ""}
          </button>
        ))}
      </div>

      {tab === "deploy" && <K8sDeploy />}

      {tab === "nodes" && clusterGated(
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead><tr><th>{tr("Node")}</th><th>{tr("Status")}</th><th>{tr("Roles")}</th><th>{tr("Kubelet")}</th><th>{tr("GPU (free / alloc)")}</th><th>{tr("GPU labels")}</th><th>{tr("Taints")}</th></tr></thead>
            <tbody>{(nodes ?? []).map((n) => <NodeRow key={n.name} n={n} />)}</tbody>
          </table>
          {nodes && nodes.length === 0 && <div className="containers-empty"><strong>{tr("Cluster has no nodes")}</strong></div>}
        </div>
      )}
      {tab === "pods" && clusterGated(
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead><tr><th>{tr("Pod")}</th><th>{tr("Namespace")}</th><th>{tr("Phase")}</th><th>{tr("Ready")}</th><th>{tr("Restarts")}</th><th>{tr("GPU")}</th><th>{tr("Node")}</th></tr></thead>
            <tbody>{(pods ?? []).map((p) => <PodRow key={`${p.namespace}/${p.name}`} p={p} />)}</tbody>
          </table>
          {pods && pods.length === 0 && <div className="containers-empty"><strong>{tr("No pods")}</strong></div>}
        </div>
      )}
      {tab === "events" && clusterGated(
        <div className="containers-table-wrap">
          <table className="containers-table">
            <thead><tr><th>{tr("Type")}</th><th>{tr("Reason")}</th><th>{tr("Object")}</th><th>{tr("Message")}</th><th>×</th></tr></thead>
            <tbody>{(events ?? []).map((e, i) => <EventRow key={i} e={e} />)}</tbody>
          </table>
          {events && events.length === 0 && <div className="containers-empty"><strong>{tr("No recent events")}</strong></div>}
        </div>
      )}
    </div>
  );
}

function ConnectCard({ error }: { error: string | null }) {
  return (
    <div className="k8s-disconnected">
      <Server size={24} />
      <strong>{tr("No cluster connected")}</strong>
      <p className="muted">{error}</p>
      <p className="upd-hint">{tr("Install the client and point the daemon at a kubeconfig (the Deploy tab works without a cluster):")}</p>
      <code className="apply-gate-cmd">pip install 'vllm-sndr-core[k8s]'  ·  export KUBECONFIG=/path/to/config</code>
    </div>
  );
}

// What k8s mode is + the GPU prerequisites — so it's a real, explained option.
function K8sIntro({ available }: { available?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="k8s-intro">
      <div className="k8s-intro-head" role="button" tabIndex={0} onClick={() => setOpen((v) => !v)} onKeyDown={onKeyActivate(() => setOpen((v) => !v))}>
        <Info size={14} />
        <span><strong>{tr("Run vLLM on Kubernetes")}</strong> — {available ? tr("monitor this cluster (nodes · pods · events) and deploy presets to it.") : tr("generate a ready-to-apply manifest from any preset; connect a kubeconfig to also monitor the cluster.")}</span>
        <ChevronDown size={15} className={open ? "rot" : ""} />
      </div>
      {open && (
        <div className="k8s-intro-body">
          <p className="k8s-intro-lead">{tr("Today you run each vLLM engine as a Docker container you start/stop per host over SSH (the Containers tab). That is the right tool for")} <b>{tr("1–2 GPU boxes you operate by hand")}</b>. {tr("Kubernetes earns its keep once you have")} <b>{tr("3+ GPU hosts")}</b> — {tr("it treats them as one pool and runs your engines")} <i>{tr("for")}</i> {tr("you instead of you SSH-ing to each.")}</p>
          <p><b>{tr("Concretely, what it does that Docker can't")}</b> — {tr("by scenario:")}</p>
          <ul className="k8s-intro-list">
            <li><b>{tr("An engine dies at 3am")}</b> → {tr("k8s restarts it, and with >1 replica the endpoint never drops. Docker's")} <code>restart:</code> {tr("revives a process but can't drain a dead replica out of a load-balanced endpoint.")}</li>
            <li><b>{tr("You need to place a 2-GPU engine")}</b> → {tr("k8s finds a node with 2")} <i>{tr("free")}</i> <code>nvidia.com/gpu</code> {tr("and schedules it there, or tells you exactly why it can't")} (<code>Insufficient nvidia.com/gpu</code> {tr("in Events")}). {tr("Docker has no view of other hosts' free GPUs.")}</li>
            <li><b>{tr("Traffic spikes")}</b> → {tr("with KEDA, k8s adds replicas when the vLLM queue")} (<code>num_requests_waiting</code>) {tr("grows and removes them when it drains. CPU-based autoscaling is useless here — inference is GPU-bound.")}</li>
            <li><b>{tr("You bump the pin")}</b> dev338 → dev371 → {tr("k8s rolls pods one at a time, waits for")} <code>/health</code>, {tr("and")} <b>{tr("halts + keeps the old pin serving")}</b> {tr("if the new one never goes Ready (your exact patch-on-new-pin drift risk). That's your current/previous pin policy, enforced by the platform.")}</li>
            <li><b>{tr("A node reboots")}</b> → {tr("k8s reconciles back to \"3 replicas of preset X at pin Y\". Docker is imperative: if the box came back and the unit didn't, it's just down.")}</li>
            <li><b>{tr("A model won't fit on one box")}</b> → {tr("multi-node tensor/pipeline parallel needs gang-scheduled, co-placed pods (KubeRay). Docker-compose is single-host by definition.")}</li>
          </ul>
          <p className="muted"><b>{tr("When NOT to bother:")}</b> {tr("1–2 boxes, 1–2 engines you babysit — stay on Docker; the k8s tax (control plane, gpu-operator, RBAC) buys nothing. Use this tab purely as the")} <b>{tr("manifest generator")}</b> {tr("until you actually have a fleet.")}</p>
          <hr className="k8s-intro-sep" />
          <p><b>{tr("Why this is an SNDR panel, not a generic dashboard:")}</b> {tr("every manifest we render")} <b>{tr("stamps its SNDR identity")}</b> — {tr("preset, pin, and enabled-patch list — onto the Deployment")} (<code>sndr.io/preset</code>, <code>sndr.io/pin</code>, <code>sndr.io/patches</code>). {tr("So the")} <b>{tr("Pods")}</b> {tr("tab shows each pod's preset + pin + patch count inline (k9s/Lens show you anonymous pods; we show you")} <i>{tr("which engine, which pin, which patches")}</i>). {tr("That identity round-trip is the keystone the roadmap builds on — pod→preset drift badge, GPU-fleet capacity planner (\"which node fits which preset\"), autoscale bounds from the preset's measured concurrency envelope, and rolling pin upgrades driven by your pin policy.")}</p>
          <p><b>{tr("This panel today:")}</b> <b>{tr("Deploy")}</b> {tr("renders a ready, identity-stamped manifest from any preset (no cluster needed to generate it) —")} <code>kubectl apply</code> {tr("and you're running.")} <b>{tr("Nodes/Pods/Events")}</b> {tr("read a connected cluster via your kubeconfig (your RBAC): GPU free/alloc per node, each SNDR pod's identity, and why a pod is Pending.")}</p>
          <p className="muted"><b>{tr("GPU prerequisite:")}</b> {tr("the cluster needs the NVIDIA device plugin / gpu-operator so nodes advertise")} <code>nvidia.com/gpu</code> {tr("(it also bundles dcgm-exporter for fleet GPU telemetry) — otherwise GPU pods stay Pending and the Events tab shows exactly that.")}</p>
        </div>
      )}
    </div>
  );
}

export function K8sDeploy() {
  const [presets, setPresets] = useState<{ id: string; label: string }[]>([]);
  const [preset, setPreset] = useState("");
  const [plan, setPlan] = useState<DeploymentPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    api.presets({}).then((r) => {
      const items = r.presets.map((p) => ({ id: p.id, label: `${p.id} · ${p.model}` }));
      setPresets(items);
      if (items[0]) setPreset(items[0].id);
    }).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);
  async function generate() {
    if (!preset) return;
    setBusy(true); setErr(null); setPlan(null);
    try { setPlan(await api.deployPlan({ preset_id: preset, target: "kubernetes" })); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const yaml = plan?.artifact?.content ?? "";
  return (
    <div className="k8s-deploy">
      <div className="k8s-deploy-bar">
        <label>{tr("Preset")}
          <select value={preset} onChange={(e) => setPreset(e.target.value)} aria-label={tr("Preset to deploy")}>
            {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <button className="primary-button" disabled={!preset || busy} onClick={() => void generate()}>
          {busy ? <Loader2 size={14} className="spin" /> : <Rocket size={14} />} {tr("Generate manifest")}
        </button>
      </div>
      {err && <div className="containers-err"><AlertTriangle size={13} /> {err}</div>}
      {plan && (
        <>
          <div className="k8s-deploy-cmds">
            <span className="muted">{tr("Apply & watch:")}</span>
            <code>kubectl apply -f {plan.artifact.filename}</code>
            <code>kubectl rollout status deploy/sndr-{plan.preset_id.slice(0, 30)}</code>
            <button className="ghost-button" onClick={() => { navigator.clipboard?.writeText(yaml); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}>
              {copied ? <ShieldCheck size={13} /> : <Copy size={13} />} {copied ? tr("copied") : tr("copy YAML")}
            </button>
          </div>
          <pre className="k8s-yaml"><code>{yaml}</code></pre>
        </>
      )}
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return <div className={`k8s-kpi${accent ? " accent" : ""}`}><span className="k8s-kpi-label">{label}</span><b>{value}</b></div>;
}

export function NodeRow({ n }: { n: K8sNode }) {
  const gpuAlloc = n.gpu_allocatable ?? 0;
  const gpuFree = n.gpu_free ?? gpuAlloc;
  const hasGpu = gpuAlloc > 0;
  const st = n.ready ? (n.schedulable ? "online" : "partial") : "offline";
  return (
    <tr className={`crow ${st}`}>
      <td className="crow-name"><span className={`container-dot ${st}`} />{n.name}</td>
      <td>
        <span className={`container-badge ${st}`}>{n.ready ? (n.schedulable ? tr("Ready") : tr("Ready (cordoned)")) : tr("NotReady")}</span>
        {n.pressures.map((p) => <span key={p} className="k8s-pressure" title={`${p} = True`}><ShieldAlert size={10} /> {p.replace("Pressure", "")}</span>)}
      </td>
      <td className="muted">{n.roles.join(", ") || "—"}</td>
      <td className="muted">{n.kubelet_version ?? "—"}</td>
      <td>
        {hasGpu
          ? <span className={`k8s-gpu ${gpuFree === 0 ? "full" : "free"}`}><Cpu size={11} /> {gpuFree} / {gpuAlloc}{n.gpu_requested ? ` · ${n.gpu_requested} ${tr("used")}` : ""}</span>
          : <span className="muted">—</span>}
      </td>
      <td className="muted k8s-gpulabels" title={Object.entries(n.gpu_labels).map(([k, v]) => `${k}=${v}`).join("\n")}>
        {n.gpu_labels["nvidia.com/gpu.product"] ?? (Object.keys(n.gpu_labels).length ? `${Object.keys(n.gpu_labels).length} ${tr("labels")}` : "—")}
      </td>
      <td className="muted">{n.taints.length ? n.taints.map((t) => t.key).join(", ") : <ShieldCheck size={12} />}</td>
    </tr>
  );
}

export function PodRow({ p }: { p: K8sPod }) {
  const st = p.phase === "Running" && p.ready_ok ? "online" : p.phase === "Pending" || p.phase === "Unknown" ? "partial" : p.ready_ok ? "online" : "offline";
  return (
    <tr className={`crow ${st}`}>
      <td className="crow-name">
        <span className="k8s-pod-name"><span className={`container-dot ${st}`} />{p.name}</span>
        {p.sndr_managed && (
          <span className="k8s-sndr-id" title={p.sndr_patches.length ? `${tr("Enabled patches:")} ${p.sndr_patches.join(", ")}` : undefined}>
            <span className="k8s-sndr-chip preset"><Package size={9} /> {p.sndr_preset}</span>
            {p.sndr_pin && <span className="k8s-sndr-chip"><Boxes size={9} /> {p.sndr_pin}</span>}
            {p.sndr_patch_count != null && <span className="k8s-sndr-chip"><Layers size={9} /> {p.sndr_patch_count}p</span>}
          </span>
        )}
      </td>
      <td className="muted">{p.namespace}</td>
      <td>
        <span className={`container-badge ${st}`}>{p.phase}</span>
        {p.reason && <span className="k8s-pressure" title={p.reason}><ShieldAlert size={10} /> {p.reason}</span>}
      </td>
      <td className={p.ready_ok ? "" : "muted"}>{p.ready}</td>
      <td className={p.restarts > 0 ? "k8s-restarts" : "muted"}>{p.restarts}</td>
      <td>{p.gpu_request > 0 ? <span className="k8s-gpu free"><Cpu size={11} /> {p.gpu_request}</span> : <span className="muted">—</span>}</td>
      <td className="muted">{p.node ?? "—"}</td>
    </tr>
  );
}

export function EventRow({ e }: { e: K8sEvent }) {
  const warn = e.type === "Warning";
  return (
    <tr className={`crow ${warn ? "offline" : ""}`}>
      <td><span className={`container-badge ${warn ? "offline" : "online"}`}>{e.type}</span></td>
      <td className="muted">{e.reason}</td>
      <td className="muted">{e.object}</td>
      <td className="k8s-evmsg" title={e.message ?? ""}>{e.message}</td>
      <td className="muted">{e.count ?? ""}</td>
    </tr>
  );
}
