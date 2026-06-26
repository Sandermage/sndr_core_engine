// SPDX-License-Identifier: Apache-2.0
// Runtime preflight panel — runs sndr.compat.preflight_checks against the RUNNING
// engine: PN60 quantization-arg validator (reads config.json via the daemon's
// /models mount) + club#43 grammar-rejection and club#34 spec-decode token-loop
// log scans. Read-only; self-fetches /api/v1/patches/preflight.
import { CircleAlert, CircleCheck, Info, Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { tr } from "../i18n";
import { useApiQuery } from "../hooks/useApiQuery";
import { api, type PreflightCheck } from "../api";

function sevIcon(sev: string) {
  if (sev === "ERROR") return <CircleAlert size={13} />;
  if (sev === "WARN") return <TriangleAlert size={13} />;
  if (sev === "INFO") return <Info size={13} />;
  return <CircleCheck size={13} />;
}
function sevTone(sev: string) {
  return sev === "ERROR" ? "danger" : sev === "WARN" ? "warn" : sev === "INFO" ? "info" : "ok";
}

function CheckRow({ c }: { c: PreflightCheck }) {
  const tone = sevTone(c.severity);
  return (
    <div className={`preflight-check ${tone}`}>
      <span className={`preflight-sev ${tone}`}>{sevIcon(c.severity)} {c.severity}</span>
      <div className="preflight-body">
        <strong>{c.name}</strong>
        {c.message && <span className="preflight-msg">{c.message}</span>}
        {c.remediation && <span className="preflight-fix">→ {c.remediation}</span>}
      </div>
    </div>
  );
}

export function PreflightPanel() {
  const { data, state, error, reload } = useApiQuery(
    ["patch-preflight"],
    (signal) => api.patchPreflight(signal),
    { staleTime: 30_000 },
  );

  if (state === "loading" || state === "idle") {
    return <div className="muted"><Loader2 size={14} /> {tr("Running preflight…")}</div>;
  }
  if (state === "error") {
    return <div className="chat-advisory"><CircleAlert size={13} /> <span>{error ?? tr("Failed to run preflight.")}</span></div>;
  }
  if (data?.error === "no_running_engine") {
    return <div className="muted">{tr("No running engine to preflight.")}</div>;
  }

  const checks = data?.checks ?? [];
  const bad = (data?.counts?.ERROR ?? 0) + (data?.counts?.WARN ?? 0);

  return (
    <div className="retire-impact">
      <div className="retire-impact-head">
        <span className={bad > 0 ? "retire-summary danger" : "retire-summary ok"}>
          {bad > 0
            ? <><TriangleAlert size={13} /> {bad} {tr("issue(s)")}</>
            : <><CircleCheck size={13} /> {tr("all checks clear")}</>}
          {data?.container && <span className="muted"> · {data.container}</span>}
        </span>
        <button className="ghost-button" onClick={reload}><RefreshCw size={12} /> {tr("Refresh")}</button>
      </div>
      {data?.error && data.error !== "no_running_engine" && <div className="muted">{tr("Preflight unavailable")} ({data.error})</div>}
      {checks.length === 0 && !data?.error
        ? <div className="muted">{tr("No preflight findings.")}</div>
        : <div className="preflight-checks">{checks.map((c, i) => <CheckRow key={`${c.name}-${i}`} c={c} />)}</div>}
    </div>
  );
}
