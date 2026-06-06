// SPDX-License-Identifier: Apache-2.0
// Environment section panels: host inventory (system/runtime/GPU/engine) +
// dependency stack (Python libs + runtime tools). Extracted from App.tsx
// (modularization) with no behavior change.
import { Cpu, Box, Server, PackageCheck, ShieldCheck, Activity, CheckCircle2, CircleAlert } from "lucide-react";
import { type HostInventory, type EnvironmentReport, type DependencyInfo } from "../api";
import { InfoRows, CapChip } from "../components/primitives";
import { totalVramGiB } from "../lib/format";
import { SkeletonMetrics, SkeletonLines } from "../Skeleton";

export function HostInventoryPanel({ inventory, environment }: { inventory: HostInventory | null; environment: EnvironmentReport | null }) {
  if (!inventory) return <SkeletonMetrics count={6} />;
  const { os, python, docker, nvidia, vllm } = inventory;
  const vram = nvidia.gpu_total_vram_mib ?? [];
  const total = totalVramGiB(vram);
  // Per-GPU rows: pair each detected GPU name with its VRAM.
  const gpuRows: Array<[string, string]> = nvidia.gpu_names.length
    ? nvidia.gpu_names.map((name, index) => [`GPU ${index}`, `${name}${vram[index] ? ` · ${Math.round((vram[index] ?? 0) / 1024)} GiB` : ""}`])
    : [["GPUs", "none detected"]];
  const canServe = nvidia.installed && nvidia.n_gpus > 0 && vllm.installed;
  return (
    <div className="host-inv-grid">
      <div className="host-inv-block">
        <h4><Cpu size={14} /> System</h4>
        <InfoRows rows={[["OS", `${os.distro || os.system}`], ["Arch", os.arch], ["Kernel", os.release || "—"], ["Python", `${python.version} (${python.implementation})`], ["Interpreter", python.binary_path || "—"], ["venv", python.venv_active ? "active" : "system"], ["pip", python.pip_present ? python.pip_version ?? "present" : "missing"]]} />
      </div>
      <div className="host-inv-block">
        <h4><Box size={14} /> Container runtime</h4>
        <InfoRows rows={[["Docker", docker.installed ? docker.version ?? "installed" : "missing"], ["Daemon", docker.daemon_running ? "running" : "stopped"], ["Server", docker.server_version ?? "—"], ["Path", docker.binary_path ?? "—"], ["NVIDIA runtime", docker.nvidia_runtime_present ? "present" : "absent"]]} />
        {docker.notes && <p className="muted">{docker.notes}</p>}
      </div>
      <div className="host-inv-block">
        <h4><Server size={14} /> GPU &amp; accelerators</h4>
        <InfoRows rows={[["Driver", nvidia.installed ? nvidia.driver_version ?? "present" : "not detected"], ["CUDA", nvidia.cuda_version ?? "—"], ["GPU count", nvidia.n_gpus ? String(nvidia.n_gpus) : "0"], ["Total VRAM", total ? `${total} GiB` : "—"], ...gpuRows]} />
        {nvidia.notes && <p className="muted">{nvidia.notes}</p>}
      </div>
      <div className="host-inv-block">
        <h4><PackageCheck size={14} /> Engine</h4>
        <InfoRows rows={[["vLLM", vllm.installed ? vllm.version ?? "installed" : "not installed"], ["Engine name", environment?.engine_name ?? "vLLM"], ["Location", vllm.location ?? "—"]]} />
      </div>
      <div className="host-inv-block">
        <h4><ShieldCheck size={14} /> Project · SNDR Core</h4>
        <InfoRows rows={[["Brand", environment?.brand ?? "—"], ["Package", environment?.package_name ?? "—"], ["Core version", environment ? `v${environment.sndr_core_version}` : "—"], ["Engine target", `${environment?.engine_name ?? "vLLM"} ${environment?.engine_version ?? ""}`.trim() || "—"], ["Dependencies", environment ? `${environment.dependencies.filter((d) => d.present).length}/${environment.dependencies.length} present` : "—"]]} />
      </div>
      <div className="host-inv-block">
        <h4><Activity size={14} /> Serving readiness</h4>
        <div className="fleet-caps inv-caps">
          <CapChip on={nvidia.installed && nvidia.n_gpus > 0} label="GPU present" />
          <CapChip on={docker.installed && docker.daemon_running} label="Docker ready" />
          <CapChip on={docker.nvidia_runtime_present} label="NVIDIA runtime" />
          <CapChip on={vllm.installed} label="vLLM installed" />
          <CapChip on={canServe} label="can serve" />
        </div>
        <p className="muted">{canServe ? "This host can launch the pinned vLLM stack." : "Resolve the unmet items above before launching here."}</p>
      </div>
    </div>
  );
}

// Improved dependency stack: a health summary, the Python library list with
// versions, and runtime tools as availability chips.
const CRITICAL_LIBS = ["vllm", "torch", "transformers"];

export function DependencyStackPanel({ env }: { env: EnvironmentReport | null }) {
  if (!env) return <SkeletonLines count={5} />;
  const libsPresent = env.dependencies.filter((dep) => dep.present).length;
  const toolsPresent = env.tools.filter((tool) => tool.present).length;
  const criticalDeps = CRITICAL_LIBS
    .map((name) => env.dependencies.find((dep) => dep.name === name))
    .filter((dep): dep is DependencyInfo => Boolean(dep));
  const criticalReady = criticalDeps.length > 0 && criticalDeps.every((dep) => dep.present);
  const missing = env.dependencies.filter((dep) => !dep.present).map((dep) => dep.name);
  const missingTools = env.tools.filter((tool) => !tool.present).map((tool) => tool.name);
  return (
    <div className="dep-stack">
      <div className="dep-summary">
        <div className="dep-summary-item">
          <strong>{libsPresent}<span>/{env.dependencies.length}</span></strong>
          <span>Python libraries</span>
        </div>
        <div className="dep-summary-item">
          <strong>{toolsPresent}<span>/{env.tools.length}</span></strong>
          <span>Runtime tools</span>
        </div>
      </div>

      <div className="dep-section-label">Serving-critical</div>
      <div className="dep-critical">
        {criticalDeps.map((dep) => (
          <div className={`dep-crit ${dep.present ? "on" : "off"}`} key={dep.name}>
            <span className="dep-crit-name">{dep.present ? <CheckCircle2 size={12} /> : <CircleAlert size={12} />}{dep.name}</span>
            <strong>{dep.present ? (dep.version ?? "ok") : "missing"}</strong>
          </div>
        ))}
      </div>

      <div className="dep-section-label">All libraries</div>
      <div className="dep-list">
        {env.dependencies.map((dep) => (
          <div className={`dep-item ${dep.present ? "on" : "off"}`} key={dep.name}>
            <span className={`sev-dot ${dep.present ? "sev-ok" : "sev-warn"}`} />
            <em>{dep.name}</em>
            <code>{dep.version ?? (dep.present ? "present" : "missing")}</code>
          </div>
        ))}
      </div>

      <div className="dep-section-label">Runtime tools{missingTools.length > 0 ? ` · ${missingTools.length} missing` : ""}</div>
      <div className="fleet-caps">
        {env.tools.map((tool) => (
          <span className={`cap-chip ${tool.present ? "on" : "off"}`} key={tool.name}>
            {tool.present ? <CheckCircle2 size={11} /> : <CircleAlert size={11} />}{tool.name}
          </span>
        ))}
      </div>

      <div className={`dep-verdict ${criticalReady ? "ok" : "warn"}`}>
        {criticalReady ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
        <span>{criticalReady
          ? "Serving-critical libraries present — this host can run the engine."
          : `Missing ${missing.length ? missing.join(", ") : "dependencies"} — install the pinned build before serving here.`}</span>
      </div>
    </div>
  );
}
