// SPDX-License-Identifier: Apache-2.0
// Pin-bump preflight panel — diffs two pin manifests (default previous -> active)
// and reports what a bump changed: newly retired/gated patches, retire-broken
// dependents (HIGH unmitigated = the dev301-class silent perf regression the gate
// blocks; mitigated HIGH edges have a native-form fallback), and perf-bearing
// patches dropped between the pins. Read-only; self-fetches
// /api/v1/patches/bump-preflight.
import { CircleAlert, CircleCheck, Loader2, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { tr } from "../i18n";
import { useApiQuery } from "../hooks/useApiQuery";
import { api } from "../api";

function Row({ label, ids, tone }: { label: string; ids: string[]; tone: "danger" | "warn" | "ok" | "neutral" }) {
  if (!ids.length) return null;
  return (
    <div className="shadow-block">
      <span className={`guidance-label ${tone === "danger" ? "danger" : tone === "warn" ? "warn" : ""}`}>{label}</span>
      <div className="chip-row">{ids.map((id) => <span key={id} className={`chip ${tone === "neutral" || tone === "ok" ? "" : tone}`}>{id}</span>)}</div>
    </div>
  );
}

export function BumpPreflightPanel() {
  const { data, state, error, reload } = useApiQuery(
    ["bump-preflight"],
    (signal) => api.bumpPreflight(signal),
    { staleTime: 60_000 },
  );

  if (state === "loading" || state === "idle") {
    return <div className="muted"><Loader2 size={14} /> {tr("Loading bump preflight…")}</div>;
  }
  if (state === "error") {
    return <div className="chat-advisory"><CircleAlert size={13} /> <span>{error ?? tr("Failed to load bump preflight.")}</span></div>;
  }
  if (data?.error) {
    return <div className="muted">{tr("Bump preflight unavailable")} ({data.error})</div>;
  }

  const pass = data?.gate_pass ?? true;
  return (
    <div className="retire-impact">
      <div className="retire-impact-head">
        <span className={pass ? "retire-summary ok" : "retire-summary danger"}>
          {pass
            ? <><ShieldCheck size={13} /> {tr("bump gate: pass")}</>
            : <><ShieldAlert size={13} /> {tr("bump gate: FAIL")}</>}
          <span className="muted"> · {data?.old_pin ?? "?"} → {data?.new_pin ?? "?"}</span>
        </span>
        <button className="ghost-button" onClick={reload}><RefreshCw size={12} /> {tr("Refresh")}</button>
      </div>

      <Row label={tr("HIGH unmitigated (blocks the bump)")} ids={data?.high_unmitigated ?? []} tone="danger" />
      <Row label={tr("HIGH mitigated (native-form fallback)")} ids={data?.high_mitigated ?? []} tone="warn" />
      <Row label={tr("Newly retired / version-gated")} ids={data?.newly_retired ?? []} tone="warn" />
      <Row label={tr("Perf patches dropped on the new pin")} ids={data?.perf_landmines ?? []} tone="danger" />

      {pass && !(data?.high_unmitigated?.length || data?.newly_retired?.length || data?.perf_landmines?.length || data?.high_mitigated?.length) && (
        <div className="muted"><CircleCheck size={13} /> {tr("Clean bump — no retires, no broken dependents, no perf drops.")} ({data?.medium_count ?? 0} {tr("MEDIUM")})</div>
      )}
    </div>
  );
}
