import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Activity, AlertTriangle, Cpu, Gauge, HardDrive, MemoryStick, RefreshCw,
  Server, Thermometer, Zap,
} from "lucide-react";
import { api, type GpuInfo, type HardwareTelemetry } from "./api";

type HostOption = { id: string; label: string };
type Source = { kind: "local" } | { kind: "host"; hostId: string };

const num = (v: number | null | undefined, d = 0) => (typeof v === "number" && !Number.isNaN(v) ? v : d);
const gib = (mib: number | null | undefined) => Math.round(num(mib) / 1024);
const clamp = (v: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v));

// Tone thresholds shared by the hero bars (util / temp / power).
function tone(pct: number): "ok" | "warn" | "hot" {
  if (pct >= 90) return "hot";
  if (pct >= 70) return "warn";
  return "ok";
}

function Bar({ label, icon, value, pct, sub }: {
  label: string; icon: ReactNode; value: string; pct: number; sub?: string;
}) {
  const t = tone(pct);
  return (
    <div className="hw-bar">
      <div className="hw-bar-head">
        <span className="hw-bar-label">{icon} {label}</span>
        <strong className={`hw-bar-value ${t}`}>{value}</strong>
      </div>
      <div className="hw-bar-track"><div className={`hw-bar-fill ${t}`} style={{ width: `${clamp(pct)}%` }} /></div>
      {sub && <span className="hw-bar-sub">{sub}</span>}
    </div>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return <div className="hw-row"><span className="hw-row-k">{k}</span><span className="hw-row-v">{v}</span></div>;
}

function GpuCard({ gpu, index }: { gpu: GpuInfo; index: number }) {
  const util = num(gpu.gpu_util);
  const temp = num(gpu.temp_gpu);
  const power = num(gpu.power);
  const powerMax = num(gpu.power_max_limit) || num(gpu.power_default_limit);
  const memUsed = num(gpu.mem_used);
  const memTotal = num(gpu.mem_total) || 1;
  const memPct = clamp((memUsed / memTotal) * 100);
  const tempPct = clamp((temp / 90) * 100); // ~90°C as the visual ceiling
  const powerPct = powerMax ? clamp((power / powerMax) * 100) : 0;

  return (
    <div className="hw-gpu">
      <div className="hw-gpu-head">
        <span className="hw-gpu-idx">{index}</span>
        <strong className="hw-gpu-name" title={gpu.name ?? ""}>{(gpu.name ?? "GPU").replace(/^NVIDIA\s+/i, "")}</strong>
        {gpu.pstate && <span className="hw-pstate" title="performance state">{gpu.pstate}</span>}
        {gpu.driver_version && <span className="hw-gpu-driver">drv {gpu.driver_version}</span>}
      </div>

      <div className="hw-heroes">
        <Bar label="Util" icon={<Gauge size={12} />} value={`${util}%`} pct={util} />
        <Bar label="Temp" icon={<Thermometer size={12} />} value={`${temp}°C`} pct={tempPct} />
        <Bar label="Power" icon={<Zap size={12} />} value={`${Math.round(power)}W`} pct={powerPct}
          sub={powerMax ? `of ${Math.round(powerMax)}W limit` : undefined} />
      </div>

      <div className="hw-mem">
        <div className="hw-bar-head">
          <span className="hw-bar-label"><MemoryStick size={12} /> VRAM</span>
          <strong className="hw-bar-value">{gib(memUsed)} / {gib(memTotal)} GB</strong>
        </div>
        <div className="hw-bar-track"><div className={`hw-bar-fill ${tone(memPct)}`} style={{ width: `${memPct}%` }} /></div>
      </div>

      <div className="hw-grid">
        <div className="hw-sect">
          <div className="hw-sect-t">Clocks</div>
          <Row k="Graphics" v={`${num(gpu.clock_gpu)} / ${num(gpu.clock_gpu_max)} MHz`} />
          <Row k="Memory" v={`${num(gpu.clock_mem)} / ${num(gpu.clock_mem_max)} MHz`} />
          <Row k="SM" v={`${num(gpu.clock_sm)} MHz`} />
        </div>
        <div className="hw-sect">
          <div className="hw-sect-t">Link & state</div>
          <Row k="PCIe" v={gpu.pcie_gen ? `gen${gpu.pcie_gen}×${num(gpu.pcie_width)} / gen${num(gpu.pcie_gen_max)}×${num(gpu.pcie_width_max)}` : "—"} />
          <Row k="Fan" v={gpu.fan_speed !== null ? `${gpu.fan_speed}%` : "—"} />
          <Row k="Compute" v={gpu.compute_mode ?? "—"} />
        </div>
        <div className="hw-sect">
          <div className="hw-sect-t">ECC & firmware</div>
          <Row k="ECC corrected" v={gpu.ecc_corrected ?? "—"} />
          <Row k="ECC uncorrect." v={<span className={num(Number(gpu.ecc_uncorrected)) > 0 ? "hw-bad" : ""}>{gpu.ecc_uncorrected ?? "—"}</span>} />
          <Row k="VBIOS" v={gpu.vbios_version ?? "—"} />
        </div>
      </div>
    </div>
  );
}

export function HardwarePanel({ hosts, initialHostId }: { hosts: HostOption[]; initialHostId?: string }) {
  const [source, setSource] = useState<Source>(
    initialHostId && hosts.some((h) => h.id === initialHostId) ? { kind: "host", hostId: initialHostId } : { kind: "local" });
  const [data, setData] = useState<HardwareTelemetry | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const loadingRef = useRef(false);
  loadingRef.current = loading;

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const r = source.kind === "host" ? await api.hostGpuRemote(source.hostId) : await api.hostGpu();
      setData(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e)); setData(null);
    } finally { setLoading(false); }
  }, [source]);

  useEffect(() => { setData(null); void load(); }, [load]);
  // Live refresh every 4s while the tab is visible and no request is in flight.
  useEffect(() => {
    const t = window.setInterval(() => { if (!loadingRef.current && !document.hidden) void load(); }, 4000);
    return () => window.clearInterval(t);
  }, [load]);

  const sys = data?.system;
  const gpus = data?.gpus ?? [];

  return (
    <div className="hw">
      <div className="hw-bar-top">
        <label className="hw-source">
          <Server size={14} />
          <select value={source.kind === "local" ? "__local__" : source.hostId}
            onChange={(e) => { const v = e.target.value; setSource(v === "__local__" ? { kind: "local" } : { kind: "host", hostId: v }); }}>
            <option value="__local__">This daemon host</option>
            {hosts.map((h) => <option key={h.id} value={h.id}>{h.label} · SSH</option>)}
          </select>
        </label>
        <span className="hw-auto">live · 4s</span>
        <button className="ghost-button" onClick={() => void load()} disabled={loading}>
          {loading ? <RefreshCw size={14} className="spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>

      {sys && (sys.cpu || sys.ram_total_gb) && (
        <div className="hw-system">
          <span className="hw-sys-item"><HardDrive size={13} /> {sys.hostname ?? "host"}</span>
          {sys.cpu && <span className="hw-sys-item"><Cpu size={13} /> {sys.cpu}{sys.cpu_count ? ` · ${sys.cpu_count} cores` : ""}</span>}
          {sys.ram_total_gb && <span className="hw-sys-item"><MemoryStick size={13} /> RAM {sys.ram_used_gb ?? "?"} / {sys.ram_total_gb} GB</span>}
          {gpus.length > 0 && <span className="hw-sys-item"><Activity size={13} /> {gpus.length} GPU{gpus.length > 1 ? "s" : ""}</span>}
        </div>
      )}

      {err && <div className="hw-empty err"><AlertTriangle size={22} /><strong>Telemetry unavailable</strong><span>{err}</span></div>}

      {!err && data && gpus.length === 0 && (
        <div className="hw-empty"><Activity size={22} /><strong>No GPU telemetry</strong>
          <span>{data.error ?? "nvidia-smi reported no devices on this host."}</span></div>
      )}

      {gpus.length > 0 && (
        <div className="hw-gpus">
          {gpus.map((g, i) => <GpuCard key={g.uuid ?? i} gpu={g} index={i} />)}
        </div>
      )}

      {!data && loading && <div className="hw-empty"><RefreshCw size={20} className="spin" /><span>Reading hardware telemetry…</span></div>}
    </div>
  );
}
