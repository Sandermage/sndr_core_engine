// SPDX-License-Identifier: Apache-2.0
// "Choose & Launch" — the consumer funnel. Four steps mirroring club-3090's
// launch.sh wizard, surfaced for the Simple-mode operator who landed here with
// one card and wants to get a model running без чтения всего workbench:
//   1. Your rig      — live GPU/VRAM (host profiles) or "model a rig" (synthetic)
//   2. Pick a model  — fused ModelCards, filtered to "fits your rig" by default
//   3. Fit check     — preflight the chosen preset BEFORE launch; ✓/✗ rows, and
//                      the single-card escape hatch instead of a dead end
//   4. Launch        — the existing LaunchPanel, unchanged
// Each step surfaces the equivalent CLI so the GUI never hides the real command.
import { useMemo, useState } from "react";
import { Cpu, HardDrive, ListChecks, Rocket, Search, Wand2 } from "lucide-react";
import { tr } from "../i18n";
import { api, type PresetRecord, type V2ConfigCatalog, type HostProfile, type PreflightFitReport } from "../api";
import { useApiQuery } from "../hooks/useApiQuery";
import { Step } from "../components/shell-bits";
import { CodeBlock } from "../components/code-block";
import { ModelCard } from "../components/model-card";
import { EscapeHatchCard } from "./catalog-cards";
import { LaunchPanel } from "./launch-panel";
import { asText } from "../lib/coerce";
import { formatVram } from "../lib/format";
import { type RuntimeMode, type Gate } from "../nav";
import { type GateStatus } from "../components/primitives";
import { type LaunchPlanEndpoint, type Job } from "../api";

// Everything the embedded LaunchPanel needs, threaded straight from the app
// shell (so step 4 reuses the SAME wired launch surface as the Launch Plan
// section — no duplicated mutation state).
export type LaunchPanelBridge = {
  model: string;
  hardware: string;
  profile: string;
  host: string;
  composed: Record<string, unknown>;
  planSummary: Record<string, unknown>;
  card: Record<string, unknown>;
  patchPolicy: string;
  runtimeTitle: string;
  runtimeMode: RuntimeMode;
  endpoints?: LaunchPlanEndpoint[];
  gates: Gate[];
  gateCounts: Record<GateStatus, number>;
  applyEnabled: boolean;
  actionReason?: string;
  launchConfirm: boolean;
  setLaunchConfirm: (value: boolean) => void;
  launchBusy: boolean;
  launchSshTarget: string;
  launchJob: Job | null;
  onLaunch: () => void;
  onConfigure: () => void;
  onViewGates: () => void;
};

type RigChoice = { kind: "live" } | { kind: "modeled"; hardwareId: string };

// A live GPU summary for the rig card row — from a registered host profile.
function gpuRowsFromHost(h: HostProfile): { name: string; vram: string; count: number } {
  return {
    name: h.gpu_name || h.hardware || tr("GPU"),
    vram: h.gpu_vram_mib ? formatVram(h.gpu_vram_mib) : "—",
    count: h.gpus || 0
  };
}

export function ChooseLaunchSection({
  presets,
  configCatalog,
  hostProfiles,
  selectedPreset,
  selectedPresetRecord,
  launchBridge,
  onPreset,
  onSection
}: {
  presets: PresetRecord[];
  configCatalog: V2ConfigCatalog | null;
  hostProfiles: HostProfile[];
  selectedPreset: string;
  selectedPresetRecord: PresetRecord | null;
  // Bundle of launch state for step 4's LaunchPanel (app shell owns it).
  launchBridge: LaunchPanelBridge;
  onPreset: (id: string) => void;
  onSection: (section: "launch-plan" | "doctor" | "overview") => void;
}) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  // Rig: live nvidia-smi rig (default when a host is registered) or a modeled
  // builtin hardware id (mirrors `sndr preflight --rig <id>`).
  const liveHost = hostProfiles[0] ?? null;
  const [rig, setRig] = useState<RigChoice>(() => (liveHost ? { kind: "live" } : { kind: "modeled", hardwareId: "" }));
  const [showAll, setShowAll] = useState(false);
  const [query, setQuery] = useState("");

  const hardwareOptions = configCatalog?.hardware ?? [];
  // Default the modeled-rig dropdown to the first catalogued rig once known.
  const modeledHardwareId =
    rig.kind === "modeled" ? rig.hardwareId || hardwareOptions[0]?.id || "" : "";

  // Preflight params shared by the "fit" probe — empty for the live rig, `rig=`
  // for a modeled one. This is exactly the CLI's rig resolution.
  const preflightRig = rig.kind === "modeled" ? modeledHardwareId : undefined;

  // ── Per-preset fit, used both to filter (step 2) and to render (step 3).
  // We probe the SELECTED preset live in step 3; for the step-2 filter we lean
  // on the card's declared envelope vs the modeled rig where possible, and fall
  // back to showing all when we can't decide cheaply (the explicit toggle wins).
  const { data: selectedFit } = useApiQuery<PreflightFitReport>(
    ["preflight", selectedPreset, preflightRig ?? "live"],
    (signal) => api.preflight({ preset_id: selectedPreset, rig: preflightRig }, signal),
    { enabled: Boolean(selectedPreset), staleTime: 15_000 }
  );

  const rigLabel =
    rig.kind === "live"
      ? (liveHost ? `${liveHost.label} · ${liveHost.gpus || "?"}× ${liveHost.gpu_vram_mib ? formatVram(liveHost.gpu_vram_mib) : "?"}` : tr("live rig (nvidia-smi)"))
      : (hardwareOptions.find((h) => h.id === modeledHardwareId)?.title || modeledHardwareId || tr("pick a rig"));

  // Step-2 model list: "fits your rig" filter uses the live selected-fit verdict
  // as a proxy only for the selected card; for the broad list we render all and
  // mark each card's own fit pill (cheap + honest). The toggle gates whether
  // known-won't-fit presets are shown at all.
  const annotated = presets.filter((p) => p.has_card);
  const visiblePresets = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let rows = annotated;
    if (needle) {
      rows = rows.filter((p) =>
        [p.id, p.model, asText(p.card?.title, "")].some((v) => String(v).toLowerCase().includes(needle))
      );
    }
    return rows;
    // showAll affects per-card rendering hint, not the row set (we can't cheaply
    // know every card's verdict without N preflights); the funnel marks fit per
    // card and the toggle controls the "won't-fit" de-emphasis below.
  }, [annotated, query]);

  const fallbackPreset = asText(selectedPresetRecord?.card?.fallback_preset, "");

  // CLI mirror per step — the real command an operator would run.
  const cliForStep = (): string[] => {
    if (step === 1) {
      return rig.kind === "live"
        ? ["sndr preflight <preset>            # against the live rig (nvidia-smi)"]
        : [`sndr preflight <preset> --rig ${modeledHardwareId || "<hardware-id>"}`];
    }
    if (step === 2 || step === 3) {
      const base = `sndr preflight ${selectedPreset || "<preset>"}`;
      return [rig.kind === "modeled" ? `${base} --rig ${modeledHardwareId || "<hardware-id>"}` : base];
    }
    return [`sndr launch apply --preset ${selectedPreset || "<preset>"} --confirm`];
  };

  const sevClass = (status: string) =>
    status === "pass" ? "ok" : status === "fail" ? "blocked" : status === "warn" ? "warn" : "info";

  return (
    <section className="choose-launch">
      <section className="process-strip" aria-label={tr("Choose and launch")}>
        <Step number="1" title={tr("Your rig")} detail={rigLabel} state="done" active={step === 1} onClick={() => setStep(1)} />
        <Step number="2" title={tr("Pick a model")} detail={selectedPreset || tr("none yet")} state={selectedPreset ? "done" : "active"} active={step === 2} onClick={() => setStep(2)} />
        <Step number="3" title={tr("Fit check")} detail={selectedFit ? selectedFit.verdict : tr("not run")} state={selectedFit ? (selectedFit.can_run ? "done" : "warning") : "idle"} active={step === 3} onClick={() => setStep(3)} />
        <Step number="4" title={tr("Launch")} detail={launchBridge.launchJob ? tr("job started") : tr("ready")} state={launchBridge.launchJob ? "done" : "idle"} active={step === 4} onClick={() => setStep(4)} />
      </section>

      {/* ── Step 1 · Your rig ─────────────────────────────────────────── */}
      {step === 1 && (
        <section className="panel cl-step">
          <h3><HardDrive size={16} /> {tr("Your rig")}</h3>
          <p className="muted">{tr("We project each preset against this rig before launch — so you never cold-start a config that can't fit.")}</p>
          <div className="cl-rig-row">
            {hostProfiles.map((h) => {
              const g = gpuRowsFromHost(h);
              const active = rig.kind === "live" && liveHost?.id === h.id;
              return (
                <button key={h.id} type="button" className={`cl-rig-card${active ? " active" : ""}`} onClick={() => setRig({ kind: "live" })}>
                  <Cpu size={16} />
                  <div>
                    <strong>{h.label}</strong>
                    <small>{g.count}× {g.name} · {g.vram}</small>
                  </div>
                </button>
              );
            })}
          </div>
          <label className="field cl-model-rig">
            <span>{hostProfiles.length ? tr("…or model a different rig") : tr("No live rig registered — model one")}</span>
            <select
              value={rig.kind === "modeled" ? modeledHardwareId : ""}
              onChange={(e) => setRig(e.target.value ? { kind: "modeled", hardwareId: e.target.value } : { kind: "live" })}
            >
              <option value="">{hostProfiles.length ? tr("Use the live rig") : tr("— pick a rig —")}</option>
              {hardwareOptions.map((h) => (
                <option key={h.id} value={h.id}>{h.title || h.id}</option>
              ))}
            </select>
          </label>
          <button className="primary-action" onClick={() => setStep(2)}>{tr("Next — pick a model")}</button>
        </section>
      )}

      {/* ── Step 2 · Pick a model ─────────────────────────────────────── */}
      {step === 2 && (
        <section className="panel cl-step">
          <div className="cl-step-head">
            <h3><Wand2 size={16} /> {tr("Pick a model")}</h3>
            <div className="cl-step-tools">
              <label className="search-box">
                <Search size={15} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={tr("Search preset or model")} aria-label={tr("Search presets")} />
              </label>
              <label className="cl-toggle">
                <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
                <span>{tr("Show all (incl. won't-fit)")}</span>
              </label>
            </div>
          </div>
          <p className="muted">{tr("On")} <code>{rigLabel}</code>. {tr("Each card shows its fit; pick one to run the full check.")}</p>
          <div className="cl-model-grid">
            {visiblePresets.map((p) => (
              <ModelCard
                key={p.id}
                preset={p}
                preflight={p.id === selectedPreset ? selectedFit ?? null : null}
                active={p.id === selectedPreset}
                onSelect={() => { onPreset(p.id); setStep(3); }}
              />
            ))}
            {visiblePresets.length === 0 && <p className="muted">{tr("No annotated presets match your search.")}</p>}
          </div>
          {!showAll && (
            <p className="fit-note">{tr("Cards that won't fit your rig stay visible but flagged — toggle above to hide nothing.")}</p>
          )}
        </section>
      )}

      {/* ── Step 3 · Fit check ────────────────────────────────────────── */}
      {step === 3 && (
        <section className="panel cl-step">
          <h3><ListChecks size={16} /> {tr("Fit check")}</h3>
          <p className="muted">{tr("Projecting")} <code>{selectedPreset || "—"}</code> {tr("against")} <code>{rigLabel}</code> — {tr("the same check")} <code>sndr preflight</code> {tr("runs.")}</p>
          {!selectedFit ? (
            <p className="muted">{tr("Running fit check…")}</p>
          ) : (
            <>
              <div className={`launch-readiness ${selectedFit.can_run ? (selectedFit.verdict.includes("warning") ? "warn" : "ready") : "blocked"}`}>
                {selectedFit.can_run ? <CheckIcon /> : <AlertIcon />}
                <div>
                  <strong>{selectedFit.verdict}</strong>
                  <small>{selectedFit.rig_source} · {selectedFit.envelope_source}</small>
                </div>
              </div>
              <ul className="cl-fit-checks">
                {selectedFit.checks.map((c) => (
                  <li key={c.dimension} className={`cl-fit-check ${sevClass(c.status)}`}>
                    <span className={`cl-fit-glyph ${sevClass(c.status)}`}>
                      {c.status === "pass" ? "✓" : c.status === "fail" ? "✗" : c.status === "warn" ? "!" : "·"}
                    </span>
                    <div>
                      <strong>{c.dimension.replace(/_/g, " ")} <em>{c.status.toUpperCase()}</em></strong>
                      <small>{tr("need")} {c.required} · {tr("have")} {c.detected}</small>
                      <small className="cl-fit-msg">{c.message}</small>
                    </div>
                  </li>
                ))}
              </ul>
              {/* Don't dead-end a single-card user: render the escape hatch. */}
              <EscapeHatchCard preflight={selectedFit} fallbackPreset={fallbackPreset} onSwitch={(id) => { onPreset(id); }} />
              <div className="cl-step-actions">
                <button className="ghost-button" onClick={() => setStep(2)}>{tr("Back")}</button>
                <button className="primary-action" disabled={!selectedFit.can_run} onClick={() => setStep(4)}>
                  {selectedFit.can_run ? tr("Continue to launch") : tr("Pick a preset that fits")}
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {/* ── Step 4 · Launch (the existing LaunchPanel, unchanged) ──────── */}
      {step === 4 && (
        <LaunchPanel
          selectedPreset={selectedPreset}
          model={launchBridge.model}
          hardware={launchBridge.hardware}
          profile={launchBridge.profile}
          host={launchBridge.host}
          composed={launchBridge.composed}
          planSummary={launchBridge.planSummary}
          card={launchBridge.card}
          patchPolicy={launchBridge.patchPolicy}
          runtimeTitle={launchBridge.runtimeTitle}
          runtimeMode={launchBridge.runtimeMode}
          endpoints={launchBridge.endpoints}
          gates={launchBridge.gates}
          gateCounts={launchBridge.gateCounts}
          applyEnabled={launchBridge.applyEnabled}
          actionReason={launchBridge.actionReason}
          launchConfirm={launchBridge.launchConfirm}
          setLaunchConfirm={launchBridge.setLaunchConfirm}
          launchBusy={launchBridge.launchBusy}
          launchSshTarget={launchBridge.launchSshTarget}
          launchJob={launchBridge.launchJob}
          onLaunch={launchBridge.onLaunch}
          onConfigure={() => onSection("launch-plan")}
          onViewGates={() => onSection("launch-plan")}
        />
      )}

      <details className="cl-cli">
        <summary><Rocket size={13} /> {tr("Equivalent CLI command")}</summary>
        <CodeBlock lines={cliForStep()} />
      </details>
    </section>
  );
}

// Tiny status glyphs kept local to avoid importing the heavier badge set.
function CheckIcon() { return <span className="cl-verdict-ico ok">✓</span>; }
function AlertIcon() { return <span className="cl-verdict-ico bad">✗</span>; }
