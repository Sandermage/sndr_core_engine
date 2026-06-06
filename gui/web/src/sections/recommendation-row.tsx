// SPDX-License-Identifier: Apache-2.0
// Preset recommendation table row: identity + routing family + workload icons +
// evidence visibility/risk. Extracted from App.tsx (modularization) with no
// behavior change.
import { CheckCircle2, Circle } from "lucide-react";
import { type PresetRecommendation } from "../api";
import { asText, asStringArray } from "../lib/coerce";
import { shortWorkload } from "../lib/format";
import { StatusBadge } from "../components/primitives";

export function RecommendationRow({
  row,
  active,
  onSelect
}: {
  row: PresetRecommendation;
  active: boolean;
  onSelect: () => void;
}) {
  const card = row.card ?? {};
  const family = asText(card.routing_family, row.model);
  const allowed = asStringArray(card.workload_allow);
  const fallback = asText(card.fallback_preset, "-");
  const visibility = asText(card.evidence_visibility, "unknown");
  const risk = visibility === "public" ? "Low" : visibility === "private" ? "Medium" : "Unknown";

  return (
    <tr className={active ? "active" : ""}>
      <td>
        <button className="preset-select" onClick={onSelect}>
          <span className="radio-dot">{active ? <CheckCircle2 size={15} /> : <Circle size={15} />}</span>
          <strong>{row.id}</strong>
        </button>
      </td>
      <td>{family}</td>
      <td>{asText(card.mode, row.profile ?? "-")}</td>
      <td>
        <StatusBadge status={asText(card.status, "missing")} />
      </td>
      <td>
        <div className="workload-icons">
          {allowed.slice(0, 4).map((item) => (
            <span key={item}>{shortWorkload(item)}</span>
          ))}
        </div>
      </td>
      <td>
        <span className={`visibility ${visibility}`}>{visibility}</span>
      </td>
      <td>{fallback}</td>
      <td>
        <span className={`risk ${risk.toLowerCase()}`}>{risk}</span>
      </td>
    </tr>
  );
}
