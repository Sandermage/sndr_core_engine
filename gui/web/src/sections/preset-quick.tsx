// SPDX-License-Identifier: Apache-2.0
// Selected-preset quick panel: status + runtime summary + allowed workloads and
// the edit/card/policy/launch actions. Extracted from App.tsx (modularization).
//
// Enterprise touch over the inline original (classes unchanged): the allowed-
// workload chips are grouped under role="group" + aria-label.
import { MousePointerClick, Wrench, FileText, BarChart3, Rocket } from "lucide-react";
import { type PresetRecord } from "../api";
import { asText, asStringArray, asNumber } from "../lib/coerce";
import { formatTokens } from "../lib/format";
import { StatusBadge, InfoRows } from "../components/primitives";
import { tr } from "../i18n";

export function PresetQuickPanel({
  selectedPreset,
  record,
  card,
  composed,
  onOpenCard,
  onEdit,
  onPolicy,
  onLaunch
}: {
  selectedPreset: string;
  record: PresetRecord | null;
  card: Record<string, unknown>;
  composed: Record<string, unknown>;
  onOpenCard: () => void;
  onEdit: () => void;
  onPolicy: () => void;
  onLaunch: () => void;
}) {
  if (!selectedPreset) {
    return (
      <section className="preset-quick empty">
        <div className="preset-quick-empty">
          <MousePointerClick size={26} />
          <strong>{tr("Select a preset")}</strong>
          <p>{tr("Click any row in the catalog to see its runtime, evidence and editing actions here.")}</p>
        </div>
      </section>
    );
  }
  const status = record?.has_card ? asText(card.status, "available") : "missing";
  const workloads = asStringArray(card.workload_allow);
  return (
    <section className="preset-quick">
      <div className="preset-quick-head">
        <div>
          <span className="preset-quick-kicker">{tr("Selected preset")}</span>
          <strong>{selectedPreset}</strong>
        </div>
        <StatusBadge status={status} />
      </div>
      <p className="preset-quick-title">{asText(card.title, tr("Unannotated preset — no card metadata yet."))}</p>
      <InfoRows
        rows={[
          [tr("Model"), asText(record?.model ?? composed.model, "-")],
          [tr("Hardware"), asText(record?.hardware ?? composed.hardware, "-")],
          [tr("Profile"), asText(record?.profile ?? composed.profile, "-")],
          [tr("Mode"), asText(card.mode, "-")],
          [tr("Max context"), formatTokens(asNumber(composed.max_model_len))],
          [tr("KV cache"), asText(composed.kv_cache_dtype, "-")],
          [tr("Spec decode"), `${asText(composed.spec_decode_method, "-")} / K=${asText(composed.spec_decode_K, "-")}`],
          [tr("Patches"), asText(composed.enabled_patches_count, "-")],
          [tr("Fallback"), asText(card.fallback_preset, tr("none"))]
        ]}
      />
      {workloads.length > 0 && (
        <div className="preset-quick-workloads">
          <span className="preset-quick-kicker">{tr("Allowed workloads")}</span>
          <div className="chip-row" role="group" aria-label={tr("Allowed workloads")}>
            {workloads.map((item) => <span className="chip" key={item}>{item}</span>)}
          </div>
        </div>
      )}
      <div className="preset-quick-actions">
        <button className="primary-button" onClick={onEdit}>
          <Wrench size={15} /> {tr("Edit preset")}
        </button>
        <button className="ghost-button" onClick={onOpenCard}>
          <FileText size={14} /> {tr("Full card")}
        </button>
        <button className="ghost-button" onClick={onPolicy}>
          <BarChart3 size={14} /> {tr("Policy")}
        </button>
        <button className="ghost-button" onClick={onLaunch}>
          <Rocket size={14} /> {tr("Launch")}
        </button>
      </div>
    </section>
  );
}
