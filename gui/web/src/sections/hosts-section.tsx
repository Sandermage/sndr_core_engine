// SPDX-License-Identifier: Apache-2.0
// Hosts section — the Hosts tab: fleet overview with live probes (FleetHostCard),
// this-host inventory, host-profile CRUD (HostFormModal + table), runtime-target
// matrix and an SSH terminal modal.
 
import { lazy, Suspense, useEffect, useState } from "react";
import { Cpu, Database, Network, PackageCheck, Pencil, Server, SlidersHorizontal, Trash2 } from "lucide-react";
import {
  api, type HostProfile, type EnvironmentReport, type ProductOverview, type ProductCapability,
  type HostInventory, type FleetHost, type ReliabilitySnapshot
} from "../api";
import { type RuntimeMode } from "../nav";
import { tr } from "../i18n";
import { InfoRows } from "../components/primitives";
import { ModuleCard, ModuleGrid } from "../components/layout";
import { CodeBlock, CopyButton } from "../components/code-block";
import { TabbedSection } from "../components/tabbed-section";
import { ConfirmDialog } from "../components/dialogs";
import { CapabilityTable } from "../components/capability-table";
import { toast } from "../components/toast";
import { DependencyStackPanel, HostInventoryPanel } from "./environment";
import { FleetHostCard, roleTone, tunnelCommand } from "./fleet-host-card";
import { HostFormModal } from "./host-form-modal";
import { ProjectCatalogPanel } from "./project-catalog";
import { ThisHostCard } from "./this-host-card";

const TerminalModal = lazy(() => import("../Terminal").then((m) => ({ default: m.TerminalModal })));

export function HostsSection({
  hostProfiles,
  environment,
  overview,
  runtimeTargets,
  apiBase,
  runtimeMode,
  onHostsRefresh,
  onChatWithHost,
  onAddServer,
  focusHostId,
  onFocusConsumed,
  onSetupNode,
  onContainers,
  onHardware,
  applyEnabled
}: {
  hostProfiles: HostProfile[];
  environment: EnvironmentReport | null;
  overview: ProductOverview | null;
  runtimeTargets: ProductCapability[];
  apiBase: string;
  runtimeMode: RuntimeMode;
  onHostsRefresh: () => void;
  onChatWithHost: (profile: HostProfile) => void;
  onAddServer: (profile: HostProfile) => Promise<boolean>;
  focusHostId: string | null;
  onFocusConsumed: () => void;
  onSetupNode: (id: string) => void;
  onContainers: (id: string) => void;
  onHardware: (id: string) => void;
  applyEnabled?: boolean;
}) {
  const [inventory, setInventory] = useState<HostInventory | null>(null);
  const [modal, setModal] = useState<{ profile: HostProfile | null } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; label: string } | null>(null);
  const askDelete = (id: string) => setConfirmDelete({ id, label: hostProfiles.find((h) => h.id === id)?.label ?? id });
  const [terminalHost, setTerminalHost] = useState<HostProfile | null>(null);
  const [reliability, setReliability] = useState<ReliabilitySnapshot>({});
  const [fleetById, setFleetById] = useState<Record<string, FleetHost>>({});
  useEffect(() => {
    let cancelled = false;
    api.hostInventory().then((data) => { if (!cancelled) setInventory(data); }).catch(() => {});
    const loadRel = () => api.hostsReliability().then((r) => { if (!cancelled) setReliability(r); }).catch(() => {});
    // Live fleet sweep (GPU util / containers / patches) to enrich each card.
    const loadFleet = () => api.fleetOverview().then((r) => {
      if (!cancelled) setFleetById(Object.fromEntries(r.hosts.map((h) => [h.id, h])));
    }).catch(() => {});
    void loadRel();
    void loadFleet();
    const tf = window.setInterval(() => { if (!document.hidden) void loadFleet(); }, 60000);
    const t = window.setInterval(() => { if (!document.hidden) void loadRel(); }, 8000);
    return () => { cancelled = true; window.clearInterval(t); window.clearInterval(tf); };
  }, []);
  async function remove(id: string) {
    try { await api.hostDelete(id); onHostsRefresh(); toast(`${tr("Host removed:")} ${id}`, "success"); } catch { toast(tr("Failed to remove host"), "error"); }
  }
  return (
    <>
      <TabbedSection
        id="hosts"
        tabs={[
          {
            id: "fleet",
            label: tr("Fleet"),
            icon: <Server size={15} />,
            render: () => (
              <ModuleGrid>
                <ModuleCard title={tr("Host fleet")} icon={<Server size={18} />} desc={tr("The daemon host plus every saved target, with a live per-host engine probe.")} wide>
                  <div className="fleet-toolbar">
                    <span className="muted">{hostProfiles.length} {hostProfiles.length === 1 ? tr("saved host") : tr("saved hosts")}</span>
                    <button className="primary-action" onClick={() => setModal({ profile: null })}><Server size={15} /> {tr("Add host")}</button>
                  </div>
                  {(() => {
                    const fl = Object.values(fleetById);
                    const online = fl.filter((h) => h.engines.some((e) => e.reachable)).length;
                    const gpus = fl.reduce((n, h) => n + (h.gpu_count || 0), 0);
                    const livePatches = fl.reduce((n, h) => n + (h.active_patches || 0), 0);
                    return (
                      <div className="fleet-kpis">
                        <span className="fleet-kpi"><strong>{hostProfiles.length}</strong> {tr("servers")}</span>
                        <span className="fleet-kpi ok"><strong>{online}</strong> {tr("online")}</span>
                        <span className="fleet-kpi"><strong>{gpus}</strong> GPUs</span>
                        <span className="fleet-kpi"><strong>{livePatches}</strong> {tr("live patches")}</span>
                      </div>
                    );
                  })()}
                  <div className="fleet-grid">
                    <ThisHostCard inventory={inventory} environment={environment} apiBase={apiBase} />
                    {hostProfiles.map((profile) => (
                      <FleetHostCard key={profile.id} profile={profile} onEdit={(p) => setModal({ profile: p })} onDelete={askDelete} onChat={onChatWithHost} onAddServer={onAddServer} onRefresh={onHostsRefresh} onTerminal={setTerminalHost} focused={focusHostId === profile.id} onFocusConsumed={onFocusConsumed} onSetupNode={onSetupNode} onContainers={onContainers} onHardware={onHardware} reliability={reliability[profile.id] ?? null} fleet={fleetById[profile.id] ?? null} applyEnabled={applyEnabled} restartCommand={environment?.restart_command} />
                    ))}
                  </div>
                  {hostProfiles.length === 0 && <p className="muted">{tr("No remote hosts yet — add your GPU box to probe its engine from here.")}</p>}
                </ModuleCard>
              </ModuleGrid>
            )
          },
          {
            id: "inventory",
            label: tr("Inventory"),
            icon: <Cpu size={15} />,
            render: () => (
              <ModuleGrid className="stretch-row">
                <ModuleCard title={tr("Daemon host inventory")} icon={<Cpu size={18} />} desc={tr("Live OS / Python / Docker / GPU / vLLM snapshot of the host serving this UI.")} wide>
                  <HostInventoryPanel inventory={inventory} environment={environment} />
                </ModuleCard>
                <ModuleCard title={tr("Dependency stack")} icon={<PackageCheck size={18} />} desc={tr("Python libraries and runtime tools detected on the daemon host.")}>
                  <DependencyStackPanel env={environment} />
                </ModuleCard>
                <ModuleCard title={tr("Project & catalog")} icon={<Database size={18} />} desc={tr("Catalog coverage and project parameters this daemon serves.")}>
                  <ProjectCatalogPanel overview={overview} environment={environment} />
                </ModuleCard>
                <ModuleCard title={tr("Runtime target matrix")} icon={<Network size={18} />} desc={tr("Which runtime backends can be rendered or controlled on this host.")} wide>
                  <CapabilityTable rows={runtimeTargets} />
                </ModuleCard>
              </ModuleGrid>
            )
          },
          {
            id: "profiles",
            label: tr("Profiles"),
            icon: <SlidersHorizontal size={15} />,
            render: () => (
              <ModuleGrid>
                <ModuleCard title={tr("Saved host profiles")} icon={<Server size={18} />} desc={tr("Operator-local registry of hosts. Edit role, hardware, ports and tags — execution stays manual.")} wide>
                  <div className="fleet-toolbar">
                    <span className="muted">{hostProfiles.length} {hostProfiles.length === 1 ? tr("profile") : tr("profiles")}</span>
                    <button className="primary-action" onClick={() => setModal({ profile: null })}><Server size={15} /> {tr("Add host")}</button>
                  </div>
                  <HostProfileTable profiles={hostProfiles} onEdit={(p) => setModal({ profile: p })} onDelete={askDelete} />
                </ModuleCard>
              </ModuleGrid>
            )
          },
          {
            id: "access",
            label: tr("Access"),
            icon: <Network size={15} />,
            render: () => (
              <ModuleGrid>
                <ModuleCard title={tr("Current connection")} icon={<Network size={18} />} desc={tr("How this UI reaches the Product API.")}>
                  <InfoRows rows={[
                    [tr("API base"), apiBase],
                    [tr("Mode"), runtimeMode === "remote" ? tr("Remote (SSH tunnel)") : tr("Local server")],
                    [tr("Engine"), `${environment?.engine_name ?? "vLLM"} ${environment?.engine_version ?? (environment?.engine_installed ? "" : tr("(not installed)"))}`.trim()],
                    [tr("Saved profiles"), String(hostProfiles.length)]
                  ]} />
                </ModuleCard>
                <ModuleCard title={tr("Remote access (SSH tunnel)")} icon={<Server size={18} />} desc={tr("Keep the daemon on 127.0.0.1; forward a loopback port from your laptop.")} wide>
                  <CodeBlock lines={[
                    "# on your laptop — forward the daemon's loopback port",
                    "ssh -L 8765:127.0.0.1:8765 user@gpu-host",
                    "# then open the UI at http://127.0.0.1:8765"
                  ]} />
                </ModuleCard>
              </ModuleGrid>
            )
          }
        ]}
      />
      {modal && <HostFormModal initial={modal.profile} onClose={() => setModal(null)} onSaved={onHostsRefresh} />}
      {confirmDelete && (
        <ConfirmDialog
          title={tr("Remove host profile?")}
          message={<>{tr("This deletes the saved profile")} <strong>{confirmDelete.label}</strong> {tr("(connection details, SSH target, stored key reference). The remote host is not touched, but the profile must be re-added to manage it from here.")}</>}
          confirmLabel={tr("Remove host")}
          danger
          onConfirm={() => { const id = confirmDelete.id; setConfirmDelete(null); void remove(id); }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
      {terminalHost && <Suspense fallback={null}><TerminalModal host={terminalHost} onClose={() => setTerminalHost(null)} /></Suspense>}
    </>
  );
}

// Dense table view of saved profiles for the Profiles tab.
function HostProfileTable({
  profiles,
  onEdit,
  onDelete
}: {
  profiles: HostProfile[];
  onEdit: (profile: HostProfile) => void;
  onDelete: (id: string) => void;
}) {
  if (profiles.length === 0) return <p className="muted">{tr("No saved profiles yet — add one above.")}</p>;
  return (
    <table className="module-table host-table">
      <thead>
        <tr><th>{tr("Label")}</th><th>{tr("Host")}</th><th>{tr("Role")}</th><th>{tr("Hardware")}</th><th>{tr("Ports")}</th><th>{tr("Tags")}</th><th></th></tr>
      </thead>
      <tbody>
        {profiles.map((profile) => (
          <tr key={profile.id}>
            <td><strong>{profile.label}</strong></td>
            <td>{profile.host}<br /><small className="muted">{profile.transport}{profile.ssh_target ? ` · ${profile.ssh_target}` : ""}</small></td>
            <td>{profile.role ? <span className={`fleet-role tone-${roleTone(profile.role)}`}>{profile.role}</span> : <span className="muted">—</span>}</td>
            <td>{profile.hardware || "—"}{profile.gpus ? ` · ${profile.gpus} GPU` : ""}</td>
            <td><small>gui {profile.port}<br />engine {profile.engine_port}</small></td>
            <td>{profile.tags.length ? <div className="fleet-tags">{profile.tags.map((t) => <span key={t} className="fleet-tag">{t}</span>)}</div> : <span className="muted">—</span>}</td>
            <td className="host-table-actions">
              <CopyButton value={tunnelCommand(profile)} label={tr("tunnel command")} />
              <button className="icon-only" onClick={() => onEdit(profile)} aria-label={`${tr("Edit")} ${profile.label}`}><Pencil size={14} /></button>
              <button className="icon-only danger" onClick={() => onDelete(profile.id)} aria-label={`${tr("Delete")} ${profile.label}`}><Trash2 size={14} /></button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

