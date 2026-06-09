// SPDX-License-Identifier: Apache-2.0
// Registry-facing section panels: multi-patch bundles + upstream-PR diff.
import { type BundleSpec, type DiffUpstreamReport } from "../api";
import { StatusBadge, KpiGrid } from "../components/primitives";
import { SkeletonLines } from "../Skeleton";
import { tr } from "../i18n";

export function BundlesPanel({ bundles }: { bundles: BundleSpec[] }) {
  if (!bundles.length) {
    return <p className="muted">{tr("No multi-patch bundles reported by the registry.")}</p>;
  }
  return (
    <table className="module-table">
      <thead>
        <tr>
          <th>{tr("Bundle")}</th>
          <th>{tr("Tier")}</th>
          <th>{tr("Umbrella flag")}</th>
          <th>{tr("Description")}</th>
        </tr>
      </thead>
      <tbody>
        {bundles.map((bundle) => (
          <tr key={bundle.name}>
            <td><strong>{bundle.name}</strong></td>
            <td><StatusBadge status={bundle.tier} /></td>
            <td><code>{bundle.umbrella_flag}</code></td>
            <td>{bundle.description}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function UpstreamDiffPanel({ report }: { report: DiffUpstreamReport | null }) {
  if (!report) {
    return <SkeletonLines count={5} />;
  }
  const active = report.has_upstream_pr;
  return (
    <div className="runtime-envelope">
      <KpiGrid
        rows={[
          [tr("Active upstream PRs"), active.length],
          [tr("Merged upstream"), report.merged_upstream.length]
        ]}
      />
      {active.length === 0 ? (
        <p className="muted">{tr("No patches currently track an open upstream PR.")}</p>
      ) : (
        <div className="patch-table-scroll">
          <table className="module-table patch-table">
            <thead>
              <tr>
                <th>{tr("Patch")}</th>
                <th>{tr("Upstream PR")}</th>
                <th>{tr("Lifecycle")}</th>
              </tr>
            </thead>
            <tbody>
              {active.map((row, index) => (
                <tr key={`${String(row.patch_id)}-${index}`}>
                  <td>
                    <strong>{String(row.patch_id)}</strong>
                    <small>{String(row.title ?? "")}</small>
                  </td>
                  <td>{row.upstream_pr ? `#${row.upstream_pr}` : "-"}</td>
                  <td><StatusBadge status={String(row.lifecycle ?? "unknown")} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
