// SPDX-License-Identifier: Apache-2.0
// "This host" card — the daemon host's own inventory at a glance (OS, Python,
// Docker, GPU/VRAM, vLLM, SNDR Core) with capability chips. Extracted from
// App.tsx (modularization) with no behavior change.
import { HardDrive } from "lucide-react";
import { type HostInventory, type EnvironmentReport } from "../api";
import { totalVramGiB } from "../lib/format";
import { CapChip } from "../components/primitives";
import { tr } from "../i18n";

export function ThisHostCard({ inventory, environment, apiBase }: { inventory: HostInventory | null; environment: EnvironmentReport | null; apiBase: string }) {
  const gpuOk = !!(inventory?.nvidia.installed && inventory.nvidia.n_gpus > 0);
  const dockerOk = !!(inventory?.docker.installed && inventory.docker.daemon_running);
  const nvRuntime = !!inventory?.docker.nvidia_runtime_present;
  const vllmOk = !!inventory?.vllm.installed;
  const vram = inventory?.nvidia.gpu_total_vram_mib ?? [];
  const totalVram = totalVramGiB(vram);
  const perGpu = vram.length ? Math.round((vram[0] ?? 0) / 1024) : 0;
  return (
    <article className="fleet-card this-host">
      <header className="fleet-card-head">
        <div className="fleet-card-id">
          <HardDrive size={16} />
          <strong>{tr("This host")} <em className="host-tag">{tr("daemon")}</em></strong>
        </div>
        <span className="fleet-status ok"><span className="fleet-dot" />{tr("connected")}</span>
      </header>
      <dl className="fleet-meta">
        <div><dt>{tr("API base")}</dt><dd>{apiBase}</dd></div>
        <div><dt>OS</dt><dd>{inventory ? `${inventory.os.distro || inventory.os.system} ${inventory.os.arch}` : "…"}</dd></div>
        <div><dt>Python</dt><dd>{inventory ? `${inventory.python.version} · ${inventory.python.venv_active ? tr("venv") : tr("system")}` : "…"}</dd></div>
        <div><dt>Docker</dt><dd>{inventory ? (dockerOk ? `${tr("running")} ${inventory.docker.server_version ?? ""}`.trim() : inventory.docker.installed ? tr("stopped") : tr("missing")) : "…"}</dd></div>
        <div><dt>GPU</dt><dd>{inventory ? (gpuOk ? `${inventory.nvidia.n_gpus}× ${inventory.nvidia.gpu_names[0] ?? "GPU"}` : tr("none detected")) : "…"}</dd></div>
        {gpuOk && <div><dt>{tr("Driver / CUDA")}</dt><dd>{inventory?.nvidia.driver_version ?? "—"}{inventory?.nvidia.cuda_version ? ` · CUDA ${inventory.nvidia.cuda_version}` : ""}</dd></div>}
        {gpuOk && totalVram > 0 && <div><dt>VRAM</dt><dd>{totalVram} GiB{vram.length > 1 ? ` · ${perGpu} GiB/GPU` : ""}</dd></div>}
        <div><dt>vLLM</dt><dd>{inventory ? (vllmOk ? inventory.vllm.version ?? tr("installed") : tr("not installed")) : "…"}</dd></div>
        <div><dt>SNDR Core</dt><dd>{environment ? `v${environment.sndr_core_version}` : "…"}</dd></div>
      </dl>
      <div className="fleet-caps">
        <CapChip on={gpuOk} label="GPU" />
        <CapChip on={dockerOk} label="Docker" />
        <CapChip on={nvRuntime} label={tr("NVIDIA runtime")} />
        <CapChip on={vllmOk} label={tr("Engine")} />
      </div>
    </article>
  );
}
