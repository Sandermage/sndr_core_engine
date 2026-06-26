// SPDX-License-Identifier: Apache-2.0
// Apply-summary panel — the running engine's REAL patch-apply state, from its own
// self-test (passed/failed/warned/skipped). The robust source: the engine reports
// its in-process patch state rather than the daemon parsing boot logs.
// Read-only; self-fetches /api/v1/patches/apply-summary.
import { CircleAlert, CircleCheck, Loader2, RefreshCw, TriangleAlert, XCircle } from "lucide-react";
import { tr } from "../i18n";
import { useApiQuery } from "../hooks/useApiQuery";
import { api, type ApplyCheck } from "../api";

function statusTone(s: string) {
  return s === "fail" ? "danger" : s === "warn" ? "warn" : s === "skip" ? "info" : "ok";
}

export function ApplySummaryPanel() {
  const { data, state, error, reload } = useApiQuery(
    ["patch-apply-summary"],
    (signal) => api.applySummary(signal),
    { staleTime: 30_000 },
  );

  if (state === "loading" || state === "idle") {
    return <div className="muted"><Loader2 size={14} /> {tr("Running engine self-test…")}</div>;
  }
  if (state === "error") {
    return <div className="chat-advisory"><CircleAlert size={13} /> <span>{error ?? tr("Failed to load apply summary.")}</span></div>;
  }
  if (data?.error === "no_running_engine") {
    return <div className="muted">{tr("No running engine to query.")}</div>;
  }
  if (data?.error) {
    return <div className="muted">{tr("Apply summary unavailable")} ({data.error})</div>;
  }

  const s = data?.summary ?? {};
  const failed = s.failed ?? 0;
  const warned = s.warned ?? 0;
  const notable = (data?.checks ?? []).filter((c: ApplyCheck) => c.status === "fail" || c.status === "warn");

  return (
    <div className="retire-impact">
      <div className="retire-impact-head">
        <span className={failed > 0 ? "retire-summary danger" : warned > 0 ? "retire-summary warn" : "retire-summary ok"}>
          {failed > 0
            ? <><XCircle size={13} /> {failed} {tr("failed")}</>
            : warned > 0
              ? <><TriangleAlert size={13} /> {warned} {tr("warned")}</>
              : <><CircleCheck size={13} /> {tr("all patches healthy")}</>}
          <span className="muted"> · {s.passed ?? 0}/{s.total ?? 0} {tr("pass")}{s.skipped ? ` · ${s.skipped} ${tr("skipped")}` : ""}{data?.container ? ` · ${data.container}` : ""}</span>
        </span>
        <button className="ghost-button" onClick={reload}><RefreshCw size={12} /> {tr("Refresh")}</button>
      </div>
      {notable.length === 0
        ? <div className="muted">{tr("Every patch passed its self-test.")}</div>
        : <div className="preflight-checks">
            {notable.map((c, i) => (
              <div key={`${c.name}-${i}`} className={`preflight-check ${statusTone(c.status)}`}>
                <span className={`preflight-sev ${statusTone(c.status)}`}>{c.status}</span>
                <div className="preflight-body"><strong>{c.name}</strong>{c.message && <span className="preflight-msg">{c.message}</span>}</div>
              </div>
            ))}
          </div>}
    </div>
  );
}
