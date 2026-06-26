// SPDX-License-Identifier: Apache-2.0
// Proof / evidence section panel: bucket distribution + per-patch drill-down.
import { useState } from "react";
import { type ProofStatusReport } from "../api";
import { asText, countRecord } from "../lib/coerce";
import { SegmentBar, BarList, segmentsFromCounts } from "../components/charts";
import { InfoRows } from "../components/primitives";
import { SkeletonLines } from "../Skeleton";
import { tr } from "../i18n";

const PROOF_PROBLEM_BUCKETS = new Set(["dead", "static_failed"]);

function ProofPatchDrilldown({
  patches,
  colors,
}: {
  patches: Array<Record<string, unknown>>;
  colors: Record<string, string>;
}) {
  const [bucket, setBucket] = useState<string>("all");
  const [expanded, setExpanded] = useState(false);
  if (!patches.length) return null;
  const patchBucket = (p: Record<string, unknown>) => asText(p.bucket, "unknown");
  const problemRank = (b: string) => (PROOF_PROBLEM_BUCKETS.has(b) ? 0 : 1);
  const buckets = Array.from(new Set(patches.map(patchBucket))).sort(
    (a, b) => problemRank(a) - problemRank(b) || a.localeCompare(b)
  );
  const filtered = patches
    .filter((p) => bucket === "all" || patchBucket(p) === bucket)
    .slice()
    .sort((a, b) => {
      const ab = patchBucket(a);
      const bb = patchBucket(b);
      return (
        problemRank(ab) - problemRank(bb) ||
        ab.localeCompare(bb) ||
        asText(a.patch_id ?? a.id, "").localeCompare(asText(b.patch_id ?? b.id, ""))
      );
    });
  const LIMIT = 12;
  const shown = expanded ? filtered : filtered.slice(0, LIMIT);
  return (
    <div className="proof-drilldown">
      <div className="proof-drill-head">
        <h5>{tr("Per-patch proof")}</h5>
        <div className="chip-row">
          <button
            type="button"
            className={`chip chip-link ${bucket === "all" ? "active" : ""}`}
            onClick={() => setBucket("all")}
          >
            {tr("all")} ({patches.length})
          </button>
          {buckets.map((b) => {
            const n = patches.filter((p) => patchBucket(p) === b).length;
            return (
              <button
                type="button"
                key={b}
                className={`chip chip-link ${bucket === b ? "active" : ""} ${PROOF_PROBLEM_BUCKETS.has(b) ? "danger" : ""}`}
                onClick={() => setBucket(b)}
              >
                {b.replace(/_/g, " ")} ({n})
              </button>
            );
          })}
        </div>
      </div>
      <table className="proof-drill-table">
        <thead>
          <tr>
            <th>{tr("Patch")}</th><th>{tr("Bucket")}</th><th>{tr("Family")}</th><th>{tr("Tier")}</th><th>{tr("Lifecycle")}</th><th>{tr("Artifacts")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((p, index) => {
            const id = asText(p.patch_id ?? p.id, `#${index}`);
            const b = patchBucket(p);
            const arte = Array.isArray(p.artefacts) ? p.artefacts.length : 0;
            return (
              <tr key={id}>
                <td><strong>{id}</strong></td>
                <td>
                  <span className="proof-bucket-dot" style={{ background: colors[b] ?? "var(--border-strong)" }} />
                  {" "}{b.replace(/_/g, " ")}
                </td>
                <td>{asText(p.family, "-")}</td>
                <td>{asText(p.tier, "-")}</td>
                <td>{asText(p.lifecycle, "-")}</td>
                <td>{arte}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {filtered.length > LIMIT && (
        <button type="button" className="proof-drill-more" onClick={() => setExpanded((v) => !v)}>
          {expanded ? tr("Show fewer") : `${tr("Show all")} ${filtered.length}`}
        </button>
      )}
    </div>
  );
}

export function ProofStatusPanel({ report }: { report: ProofStatusReport | null }) {
  if (!report) {
    return <SkeletonLines count={5} />;
  }
  if (!report.available) {
    return (
      <InfoRows
        rows={[
          [tr("Proof subsystem"), tr("Unavailable")],
          [tr("Reason"), report.reason ?? tr("not initialized")],
          [tr("Hint"), tr("Run sndr patches prove to generate artifacts")]
        ]}
      />
    );
  }
  const entries = Object.entries(report.counts);
  const proofColors: Record<string, string> = {
    bench_with_baseline: "var(--ok)",
    bench_attached: "var(--accent)",
    static_only: "var(--info)",
    static_failed: "var(--warn)",
    dead: "var(--danger)"
  };
  const bucketMeaning: Record<string, string> = {
    bench_with_baseline: tr("Has a measured TPS/TPOT baseline"),
    bench_attached: tr("Benchmark evidence attached"),
    static_only: tr("Static artifact only — no live run"),
    static_failed: tr("Static check failed"),
    dead: tr("No artifact / dead reference")
  };
  const patches = report.patches ?? [];
  const totalArtefacts = patches.reduce(
    (sum, patch) => sum + (Array.isArray(patch.artefacts) ? patch.artefacts.length : 0),
    0
  );
  const bar = (counts: Record<string, number>, limit = 99): Array<[string, number, string]> => {
    const max = Math.max(1, ...Object.values(counts));
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([key, value]) => [key.replace(/_/g, " "), Math.round((value / max) * 100), String(value)]);
  };
  const byFamily = countRecord(patches.map((patch) => asText(patch.family, "unknown")));
  const byTier = countRecord(patches.map((patch) => asText(patch.tier, "unknown")));
  const byLifecycle = countRecord(patches.map((patch) => asText(patch.lifecycle, "unknown")));
  const familyShown = Math.min(10, Object.keys(byFamily).length);
  const familyHidden = Object.keys(byFamily).length - familyShown;
  return (
    <div className="proof-status">
      {entries.length ? (
        <SegmentBar
          segments={segmentsFromCounts(report.counts, proofColors)}
          total={report.total}
          totalLabel={tr("proof artifacts")}
        />
      ) : (
        <p className="muted">{tr("No proof artifacts collected yet.")}</p>
      )}
      <div className="proof-buckets">
        {entries.map(([key, value]) => (
          <div className="proof-bucket" key={key}>
            <span className="proof-bucket-dot" style={{ background: proofColors[key] ?? "var(--border-strong)" }} />
            <div>
              <span className="proof-bucket-head"><strong>{value}</strong> {key.replace(/_/g, " ")}</span>
              <small>{bucketMeaning[key] ?? "—"}</small>
            </div>
          </div>
        ))}
      </div>
      <div className="proof-dists">
        <div className="proof-dist">
          <h5>{tr("By family")} {familyHidden > 0 && <em>{tr("top")} {familyShown}</em>}</h5>
          <BarList rows={bar(byFamily, 10)} />
          {familyHidden > 0 && <small className="muted">+{familyHidden} {familyHidden === 1 ? tr("more family") : tr("more families")}</small>}
        </div>
        <div className="proof-dist">
          <h5>{tr("By tier")}</h5>
          <BarList rows={bar(byTier)} />
        </div>
        <div className="proof-dist">
          <h5>{tr("By lifecycle")}</h5>
          <BarList rows={bar(byLifecycle)} />
        </div>
      </div>
      <ProofPatchDrilldown patches={patches} colors={proofColors} />
      <p className="proof-foot muted">{patches.length} {tr("patches indexed")} · {totalArtefacts} {totalArtefacts === 1 ? tr("artifact file") : tr("artifact files")}</p>
    </div>
  );
}
