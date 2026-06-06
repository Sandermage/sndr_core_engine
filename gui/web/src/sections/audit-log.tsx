// SPDX-License-Identifier: Apache-2.0
// Audit-log section panel: live event feed with a kind/message filter, polling
// the daemon every 5s while the tab is visible. Extracted from App.tsx
// (modularization) with no behavior change.
import { useEffect, useState } from "react";
import { api, type BackendEvent } from "../api";
import { SkeletonTable } from "../Skeleton";

export function AuditLogPanel() {
  const [events, setEvents] = useState<BackendEvent[]>([]);
  const [filter, setFilter] = useState("");
  const [state, setState] = useState<"loading" | "ready">("loading");
  useEffect(() => {
    let cancelled = false;
    const load = () => api.eventsRecent(0)
      .then((result) => { if (!cancelled) { setEvents(result.events.slice().reverse()); setState("ready"); } })
      .catch(() => { if (!cancelled) setState("ready"); });
    load();
    // Skip the poll while the tab is hidden — no point hammering the daemon in the background.
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  const rows = events.filter((event) => !filter || `${event.kind} ${event.message}`.toLowerCase().includes(filter.toLowerCase()));
  const stamp = (ts: number) => new Date(ts * 1000).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const tone = (kind: string) => kind === "auth" ? "warn" : kind.startsWith("op") || kind === "job" ? "info" : "muted";
  if (state === "loading") return <SkeletonTable rows={6} cols={4} />;
  return (
    <div className="audit-log">
      <div className="audit-bar">
        <span className="muted">{events.length} recorded event{events.length === 1 ? "" : "s"} · live</span>
        <input className="audit-filter" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter by kind or message…" spellCheck={false} />
      </div>
      {rows.length === 0 ? <p className="muted">No events match.</p> : (
        <div className="patch-table-scroll">
          <table className="module-table audit-table">
            <thead><tr><th>Time</th><th>Kind</th><th>Event</th><th>Seq</th></tr></thead>
            <tbody>
              {rows.map((event) => (
                <tr key={event.seq}>
                  <td className="audit-ts">{stamp(event.ts)}</td>
                  <td><span className={`audit-kind tone-${tone(event.kind)}`}>{event.kind}</span></td>
                  <td>{event.message}</td>
                  <td className="muted">{event.seq}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
