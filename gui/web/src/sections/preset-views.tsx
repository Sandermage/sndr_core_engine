// SPDX-License-Identifier: Apache-2.0
// Preset display views — the Presets tab summary strip, the selected-preset
// detail view (what-will-run + runtime + evidence + draft editor) and the
// fallback diff. Extracted from App.tsx (modularization) with no behavior change.
import { Box, Code2, Database, FileText, GitBranch, Network, Rocket, Server, ShieldCheck, SlidersHorizontal, Wrench } from "lucide-react";
import { type PresetRecord, type PresetExplainResult, type ProductCapability } from "../api";
import { asNumber, asStringArray, asText } from "../lib/coerce";
import { formatTokens, targetTitle } from "../lib/format";
import { InfoRows, StatusBadge } from "../components/primitives";
import { ModuleCard, ModuleGrid } from "../components/layout";
import { ConfigDraftEditor } from "./config-draft-editor";
import { EvidenceRows } from "./bench";

function PresetFallbackDiff({ explain }: { explain: PresetExplainResult | null }) {
  const fallback = (explain?.fallback_diff ?? null) as { fallback_preset?: string; diffs?: string[] } | null;
  if (!fallback || !fallback.fallback_preset) {
    return <p className="muted">No fallback declared for this preset.</p>;
  }
  const diffs = Array.isArray(fallback.diffs) ? fallback.diffs : [];
  return (
    <div className="fallback-diff">
      <div className="fallback-diff-head"><GitBranch size={14} /> overrides vs <strong>{fallback.fallback_preset}</strong></div>
      {diffs.length > 0 ? (
        <ul className="fallback-diff-list">
          {diffs.map((line, index) => <li key={index}>{line}</li>)}
        </ul>
      ) : <p className="muted">Matches its fallback exactly — no overrides.</p>}
    </div>
  );
}

// Enterprise "selected preset" detail view: a hero with identity + quick
// actions, a row of runtime metric tiles, then equal-height detail cards
// (identity, evidence, workload rules, fallback) and the editable draft.
export function PresetSelectedView({
  selectedPreset,
  record,
  card,
  composed,
  explain,
  runtimeTargets,
  runtimeTarget,
  patchPolicy,
  onEdit,
  onLaunch,
  onConfigs
}: {
  selectedPreset: string;
  record: PresetRecord | null;
  card: Record<string, unknown>;
  composed: Record<string, unknown>;
  explain: PresetExplainResult | null;
  runtimeTargets: ProductCapability[];
  runtimeTarget: string;
  patchPolicy: string;
  onEdit: () => void;
  onLaunch: () => void;
  onConfigs: () => void;
}) {
  const cm = { ...composed, ...(explain?.composed ?? {}) } as Record<string, unknown>;
  // asText only accepts strings; composed numerics (max_num_seqs, spec K, patch
  // count) need a numeric-aware formatter or they fall back to a dash.
  const val = (value: unknown) =>
    typeof value === "number" ? String(value) : typeof value === "string" && value.trim() ? value : "—";
  const status = asText(card.status, record?.has_card ? "available" : "missing");
  const util = asNumber(cm.gpu_memory_utilization);
  const specMethod = asText(cm.spec_decode_method, "");
  const allow = asStringArray(card.workload_allow);
  const deny = asStringArray(card.workload_deny);
  const metrics: Array<{ label: string; value: string }> = [
    { label: "Max context", value: formatTokens(asNumber(cm.max_model_len)) },
    { label: "Max sequences", value: val(cm.max_num_seqs) },
    { label: "GPU mem util", value: util > 0 ? `${Math.round(util * 100)}%` : "—" },
    { label: "KV cache", value: val(cm.kv_cache_dtype) },
    { label: "Spec decode", value: specMethod ? `${specMethod} · K=${val(cm.spec_decode_K)}` : "—" },
    { label: "Enabled patches", value: val(cm.enabled_patches_count) }
  ];
  return (
    <div className="preset-selected">
      <header className="preset-hero">
        <div className="preset-hero-main">
          <div className="preset-hero-id">
            <span className="preset-hero-icon"><Database size={20} /></span>
            <div className="preset-hero-text">
              <h2>{asText(card.title, "Unannotated preset")}</h2>
              <code>{selectedPreset}</code>
            </div>
            <StatusBadge status={status} />
          </div>
          <div className="preset-hero-chips">
            <span className="hero-chip"><Box size={12} />{record?.model ?? "—"}</span>
            <span className="hero-chip"><Server size={12} />{record?.hardware ?? "—"}</span>
            {record?.profile && <span className="hero-chip"><SlidersHorizontal size={12} />{record.profile}</span>}
            <span className="hero-chip"><Network size={12} />{targetTitle(runtimeTargets, runtimeTarget)}</span>
            <span className="hero-chip"><Wrench size={12} />{patchPolicy} policy</span>
          </div>
        </div>
        <div className="preset-hero-actions">
          <button className="primary-action" onClick={onLaunch}><Rocket size={15} /> Launch</button>
          <button className="ghost-button" onClick={onEdit}><Wrench size={15} /> Edit</button>
          <button className="ghost-button" onClick={onConfigs}><SlidersHorizontal size={15} /> Open in Configs</button>
        </div>
      </header>

      <div className="preset-metrics">
        {metrics.map((metric) => (
          <div className="preset-metric" key={metric.label}>
            <strong>{metric.value}</strong>
            <span>{metric.label}</span>
          </div>
        ))}
      </div>

      <ModuleGrid className="stretch-row">
        <ModuleCard title="Identity" icon={<FileText size={18} />} desc="What composes this preset.">
          <InfoRows
            rows={[
              ["Model", record?.model ?? asText(cm.model, "—")],
              ["Hardware", record?.hardware ?? asText(cm.hardware, "—")],
              ["Profile", record?.profile ?? asText(cm.profile, "—")],
              ["Mode", asText(card.mode, "—")],
              ["Runtime target", targetTitle(runtimeTargets, runtimeTarget)],
              ["Fallback", asText(card.fallback_preset, "none")],
              ["Evidence", asText(card.evidence_visibility, "—")]
            ]}
          />
        </ModuleCard>
        <ModuleCard title="Workload Rules" icon={<SlidersHorizontal size={18} />} desc="Where this preset is allowed or denied.">
          <div className="wl-rules">
            {allow.length > 0 && (
              <div className="wl-group">
                <span className="wl-label ok">Allow</span>
                <div className="fleet-caps">{allow.map((item) => <span className="cap-chip on" key={item}>{item.replace(/_/g, " ")}</span>)}</div>
              </div>
            )}
            {deny.length > 0 && (
              <div className="wl-group">
                <span className="wl-label danger">Deny</span>
                <div className="fleet-caps">{deny.map((item) => <span className="cap-chip off" key={item}>{item.replace(/_/g, " ")}</span>)}</div>
              </div>
            )}
            {allow.length === 0 && deny.length === 0 && <p className="muted">No workload restrictions — usable for any workload.</p>}
          </div>
        </ModuleCard>
        <ModuleCard title="Evidence References" icon={<ShieldCheck size={18} />} desc="Proof refs attached to this preset.">
          <EvidenceRows card={card} />
        </ModuleCard>
        <ModuleCard title="Overrides vs Fallback" icon={<GitBranch size={18} />} desc="What this preset changes relative to its fallback.">
          <PresetFallbackDiff explain={explain} />
        </ModuleCard>
      </ModuleGrid>

      <ModuleGrid>
        <ModuleCard title="Editable Runtime Draft" icon={<Code2 size={18} />} desc="Tune a local copy and render artifacts — operator-safe." wide>
          <ConfigDraftEditor
            selectedPreset={selectedPreset}
            composed={composed}
            runtimeTarget={runtimeTarget}
            patchPolicy={patchPolicy}
          />
        </ModuleCard>
      </ModuleGrid>
    </div>
  );
}

// OperationsConsole (+ OP_GROUP_ICON) extracted to ./sections/operations.
// OperationsConsole moved to ./sections/operations (see import).

export function PresetSummaryStrip({ presets, selectedPreset }: { presets: PresetRecord[]; selectedPreset: string }) {
  const annotated = presets.filter((preset) => preset.has_card).length;
  const missing = presets.length - annotated;
  const models = new Set(presets.map((preset) => preset.model)).size;
  const hardware = new Set(presets.map((preset) => preset.hardware)).size;
  const tiles: Array<{ label: string; value: string; tone?: string }> = [
    { label: "Presets", value: String(presets.length) },
    { label: "Annotated", value: String(annotated), tone: "ok" },
    { label: "Missing card", value: String(missing), tone: missing ? "warn" : "ok" },
    { label: "Models", value: String(models) },
    { label: "Hardware", value: String(hardware) },
    { label: "Selected", value: selectedPreset || "—" }
  ];
  return (
    <div className="preset-summary-strip">
      {tiles.map((tile) => (
        <div className={`preset-stat ${tile.tone ?? ""}`} key={tile.label}>
          <span className="preset-stat-value">{tile.value}</span>
          <span className="preset-stat-label">{tile.label}</span>
        </div>
      ))}
    </div>
  );
}

// PresetQuickPanel extracted to ./sections/preset-quick.

// Benchmark-baseline chip for the preset catalog: surfaces the measured
// reference metric (primary_metric) at the list level, so bench-proven presets
// are distinguishable from pending ones at a glance. value 0 / missing = pending.
// PresetBaselineCell + PresetCatalogTable extracted to ./sections/preset-catalog.

// PatchSummaryPanel + PatchLifecycleGraph + PatchRegistryInsight + PatchModelSupport extracted to ./sections/patch-overview.

// PatchInventoryControl + PatchFamilyGroup extracted to ./sections/patch-inventory.

// formatAppliesTo extracted to ./lib/format.

// PatchExplainPanel (+ lifecycle/default explanation helpers) extracted to ./sections/patch-explain.

// CaveatsPanel / ConfigKeysPanel / TracesPanel extracted to ./sections/diagnostics.
// DoctorStat extracted to ./components/primitives.
// SEVERITY_META + DoctorSummary / DoctorFindings (+ DoctorCategory / SeverityDot /
// DoctorFindingRow) extracted to ./sections/doctor.

// WizardStatus + SetupWizard extracted to ./sections/setup-wizard.

// fmtParam extracted to ./lib/format.
// DeploymentConsole (+ DEPLOY_TARGET_ICONS + downloadText) extracted to ./sections/deployment.



// EnvironmentPanel extracted to ./sections/environment.

// SERVICE_RUNTIME_TARGETS + ServiceLifecyclePlanner extracted to ./sections/services.

// DoctorCoveragePanel + AdminSurfaceMatrix extracted to ./sections/patch-doctor.
// (BundlesPanel + UpstreamDiffPanel previously extracted to ./sections/registry;
//  ProofStatusPanel + drill-down to ./sections/proof.)

// BenchmarkBaselinePanel + EvidenceRows extracted to ./sections/bench.

// EndpointRows extracted to ./sections/rail-cards.

// Reusable confirmation dialog for destructive/irreversible actions. Focus is
// trapped, Cancel is the autofocused default, Esc/backdrop cancel, and the
// confirm button can be styled as danger. Keeps destructive paths deliberate.
// ConfirmDialog + InfoDialog extracted to ./components/dialogs.

// toast + ToastHost (+ ToastTone) extracted to ./components/toast.

// ── Audit log (surfaces the daemon's recorded events: auth, jobs, system) ──
// AuditLogPanel extracted to ./sections/audit-log.
