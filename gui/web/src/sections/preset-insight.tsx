// SPDX-License-Identifier: Apache-2.0
// Preset insight panels: the runtime envelope (context/concurrency/patches/
// metric bars + KV/spec rows) and the workload policy graph (allow/deny pills +
// per-status distribution).
import { asRecord, asNumber, asText, asStringArray } from "../lib/coerce";
import { formatTokens } from "../lib/format";
import { BarList } from "../components/charts";
import { InfoRows } from "../components/primitives";
import { tr } from "../i18n";

export function RuntimeEnvelopePanel({
  card,
  composed,
  patchCount
}: {
  card: Record<string, unknown>;
  composed: Record<string, unknown>;
  patchCount: number;
}) {
  const metric = asRecord(card.primary_metric);
  const context = asNumber(composed.max_model_len);
  const sequences = asNumber(composed.max_num_seqs);
  const patches = asNumber(composed.enabled_patches_count);
  return (
    <div className="runtime-envelope">
      <BarList
        rows={[
          [tr("Context"), Math.min(100, Math.round(context / 4096)), formatTokens(context)],
          [tr("Concurrency"), Math.min(100, sequences * 10), String(sequences || "-")],
          [tr("Enabled patches"), patchCount ? Math.round((patches / patchCount) * 100) : 0, String(patches || 0)],
          [tr("Metric"), Math.min(100, Math.round(asNumber(metric.value) / 8)), String(asNumber(metric.value) || tr("pending"))]
        ]}
      />
      <InfoRows
        rows={[
          [tr("KV Cache"), asText(composed.kv_cache_dtype, "-")],
          [tr("Spec Decode"), asText(composed.spec_decode_method, "-")],
          [tr("Spec K"), String(asNumber(composed.spec_decode_K) || "-")],
          [tr("Evidence"), asText(card.evidence_visibility, tr("unknown"))]
        ]}
      />
    </div>
  );
}

export function PresetPolicyGraph({
  card
}: {
  card: Record<string, unknown>;
}) {
  const allow = asStringArray(card.workload_allow);
  const deny = asStringArray(card.workload_deny);
  return (
    <div className="policy-graph">
      <div className="policy-summary">
        <span className="policy-count allow">{allow.length} {tr("allowed")}</span>
        <span className="policy-count deny">{deny.length} {tr("denied")}</span>
      </div>
      {allow.length || deny.length ? (
        <div className="policy-pill-grid">
          {allow.map((item) => <span className="policy-pill allow" key={`allow-${item}`}>{item}</span>)}
          {deny.map((item) => <span className="policy-pill deny" key={`deny-${item}`}>{item}</span>)}
        </div>
      ) : (
        <p className="muted">{tr("No explicit workload policy — every workload is allowed.")}</p>
      )}
    </div>
  );
}
