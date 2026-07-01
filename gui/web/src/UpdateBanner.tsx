// Auto-reload-on-new-build banner. The daemon stamps a `gui_build_id` into
// /api/v1/health (from web_static/build-id.txt, written by `make gui-build`).
// We capture it on first load and poll it; when it changes — i.e. the served
// Control Center bundle was redeployed (e.g. after a pin/version bump) — we
// surface a one-click Reload instead of the operator needing a manual
// hard-refresh. Self-contained: no App-level state, safe to mount once.
import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "./api";
import { tr } from "./i18n";

const POLL_MS = 120_000; // 2 min — cheap, well under any deploy cadence

export function UpdateBanner() {
  const baseline = useRef<string | null | undefined>(undefined);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const h = await api.health();
        const id = h.gui_build_id ?? null;
        if (baseline.current === undefined) {
          baseline.current = id; // first successful read = the build we loaded
          return;
        }
        // Only fire when we have two real, differing ids (null build-id = an
        // older daemon without the stamp; never nag in that case).
        if (id && baseline.current && id !== baseline.current && alive) setStale(true);
      } catch {
        /* transient — ignore, retry next tick */
      }
    };
    void check();
    const t = window.setInterval(() => void check(), POLL_MS);
    return () => { alive = false; window.clearInterval(t); };
  }, []);

  if (!stale) return null;
  return (
    <div
      role="status"
      style={{
        position: "fixed", bottom: 16, right: 16, zIndex: 9999,
        display: "flex", alignItems: "center", gap: 10,
        padding: "10px 14px", borderRadius: 10,
        background: "#1e293b", color: "#e2e8f0",
        border: "1px solid #3b82f6", boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
        fontSize: "0.9em",
      }}
    >
      <RefreshCw size={15} />
      <span>{tr("A new Control Center build is available.")}</span>
      <button
        onClick={() => window.location.reload()}
        style={{
          cursor: "pointer", padding: "4px 10px", borderRadius: 6,
          background: "#3b82f6", color: "white", border: "none", fontWeight: 600,
        }}
      >
        {tr("Reload")}
      </button>
    </div>
  );
}
