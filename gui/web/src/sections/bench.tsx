// SPDX-License-Identifier: Apache-2.0
// Benchmark / evidence section panels: baseline hero + runtime-under-test, and
// evidence-ref rows.
import { type PresetRecord } from "../api";
import { asRecord, asNumber, asText } from "../lib/coerce";
import { formatTokens } from "../lib/format";
import { StatusBadge, InfoRows } from "../components/primitives";
import { tr } from "../i18n";

export function BenchmarkBaselinePanel({
  card,
  composed,
  record,
  selectedPreset
}: {
  card: Record<string, unknown>;
  composed: Record<string, unknown>;
  record: PresetRecord | null;
  selectedPreset: string;
}) {
  const metric = asRecord(card.primary_metric);
  const value = asNumber(metric.value);
  const hasValue = value > 0;
  return (
    <div className="bench-baseline">
      <div className="bench-hero">
        <div className="bench-hero-metric">
          <span className="bench-hero-value">{hasValue ? value.toLocaleString() : "—"}</span>
          <span className="bench-hero-unit">{asText(metric.kind, tr("no baseline metric"))}</span>
        </div>
        <InfoRows
          rows={[
            [tr("Measured at"), asText(metric.measured_at, tr("not measured"))],
            [tr("Source"), asText(metric.source, "-")],
            [tr("Preset"), selectedPreset || "-"]
          ]}
        />
      </div>
      <div className="bench-runtime">
        <h5>{tr("Runtime under test")}</h5>
        <InfoRows
          rows={[
            [tr("Model"), asText(composed.model ?? record?.model, "-")],
            [tr("Hardware"), asText(composed.hardware ?? record?.hardware, "-")],
            [tr("Profile"), asText(composed.profile ?? record?.profile, "-")],
            [tr("Max context"), formatTokens(asNumber(composed.max_model_len))],
            [tr("Max sequences"), asText(composed.max_num_seqs, "-")],
            [tr("GPU mem util"), asText(composed.gpu_memory_utilization, "-")],
            [tr("KV cache"), asText(composed.kv_cache_dtype, "-")],
            [tr("Spec decode"), `${asText(composed.spec_decode_method, "-")} / K=${asText(composed.spec_decode_K, "-")}`],
            [tr("Enabled patches"), asText(composed.enabled_patches_count, "-")]
          ]}
        />
      </div>
    </div>
  );
}

export function EvidenceRows({ card }: { card: Record<string, unknown> }) {
  const refs = Array.isArray(card.evidence_refs) ? card.evidence_refs : [];
  return (
    <div className="action-rows">
      {refs.length ? refs.map((ref, index) => {
        const row = asRecord(ref);
        return (
          <div key={`${asText(row.path, "ref")}-${index}`}>
            <div>
              <strong>{asText(row.type, "evidence")}</strong>
              <small>{asText(row.path, "-")}</small>
            </div>
            <StatusBadge status={asText(row.visibility, "missing")} />
          </div>
        );
      }) : (
        <div>
          <div>
            <strong>{tr("No evidence refs")}</strong>
            <small>{tr("Selected preset does not expose evidence metadata yet.")}</small>
          </div>
          <StatusBadge status="missing" />
        </div>
      )}
    </div>
  );
}
