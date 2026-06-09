// SPDX-License-Identifier: Apache-2.0
// Self-contained diagnostic section panels (no props; fetch their own data via
// useFetch + api). Extracted from App.tsx (modularization) with no behavior
// change. Surface the CLI caveats / config-keys / trace registries.
import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api } from "../api";
import { useFetch } from "../hooks/useFetch";
import { SkeletonLines } from "../Skeleton";
import { tr } from "../i18n";

// Host caveats — known host-condition issues evaluated live against the
// daemon host (kernel/virtualization/GPU/pin). Surfaces the CLI `sndr
// caveats` registry the GUI never exposed.
export function CaveatsPanel() {
  const { data, state, error } = useFetch(() => api.caveats(), []);
  if (state === "loading") return <SkeletonLines count={4} />;
  if (state === "error") return <p className="muted">{tr("Caveats unavailable:")} {error}</p>;
  if (!data) return null;
  const sevTone: Record<string, string> = { error: "danger", warning: "warn", info: "info" };
  return (
    <div className="caveats-panel">
      <div className="caveats-head">
        {data.triggered_count > 0
          ? <span className="chip danger"><AlertTriangle size={11} /> {data.triggered_count} {tr("triggered on this host")}</span>
          : <span className="chip ok">{tr("none triggered")}{data.host_facts_available ? "" : ` ${tr("(host probe unavailable)")}`}</span>}
        <span className="muted">{data.total} {tr("known caveats")}</span>
      </div>
      <div className="caveats-list">
        {data.caveats.map((c) => (
          <div className={`caveat-row ${c.triggered ? "triggered" : ""}`} key={c.id}>
            <span className={`status-badge ${sevTone[c.severity] ?? "info"}`}>{c.severity}</span>
            <div className="caveat-body">
              <div className="caveat-title">
                <strong>{c.title}</strong>
                {c.triggered === true && <span className="chip danger">{tr("fires here")}</span>}
                {c.triggered === null && <span className="chip" title={tr("host facts unavailable")}>{tr("not evaluated")}</span>}
              </div>
              <p className="muted">{c.message}</p>
              {c.docs_url && <a href={c.docs_url} target="_blank" rel="noreferrer" className="caveat-doc">{tr("docs")} →</a>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Config-key glossary — every GENESIS_ENABLE_* / V1 / V2 / policy key with
// provenance, filterable. Surfaces the CLI `sndr config-keys` registry.
export function ConfigKeysPanel() {
  const { data, state, error } = useFetch(() => api.configKeys(), []);
  const [q, setQ] = useState("");
  const [src, setSrc] = useState("all");
  if (state === "loading") return <SkeletonLines count={6} />;
  if (state === "error") return <p className="muted">{tr("Config keys unavailable:")} {error}</p>;
  if (!data) return null;
  const needle = q.trim().toLowerCase();
  const entries = Object.entries(data.keys)
    .filter(([k, v]) => (src === "all" || v.source === src) && (!needle || k.toLowerCase().includes(needle)))
    .sort((a, b) => a[0].localeCompare(b[0]));
  const sources = Object.keys(data.by_source).sort();
  return (
    <div className="configkeys-panel">
      <div className="ck-controls">
        <input className="ck-search" placeholder={tr("Filter keys…")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={tr("Filter config keys")} />
        <div className="chip-row">
          <button type="button" className={`chip chip-link ${src === "all" ? "active" : ""}`} onClick={() => setSrc("all")}>{tr("all")} ({data.total})</button>
          {sources.map((s) => (
            <button type="button" key={s} className={`chip chip-link ${src === s ? "active" : ""}`} onClick={() => setSrc(s)}>{s} ({data.by_source[s]})</button>
          ))}
        </div>
      </div>
      <div className="ck-list">
        {entries.slice(0, 200).map(([k, v]) => (
          <div className="ck-row" key={k}>
            <code className="ck-key">{k}</code>
            <span className="ck-src">{v.source}</span>
          </div>
        ))}
        {entries.length > 200 && <p className="muted">+{entries.length - 200} {tr("more — refine the filter")}</p>}
        {entries.length === 0 && <p className="muted">{tr("No keys match.")}</p>}
      </div>
    </div>
  );
}

// Diagnostic trace catalog — per-patch debug traces, where they land on the
// container FS, and the env var that enables each. Surfaces `sndr trace list`.
export function TracesPanel() {
  const { data, state, error } = useFetch(() => api.traces(), []);
  const [cat, setCat] = useState("all");
  if (state === "loading") return <SkeletonLines count={5} />;
  if (state === "error") return <p className="muted">{tr("Traces unavailable:")} {error}</p>;
  if (!data) return null;
  const shown = data.traces.filter((t) => cat === "all" || t.category === cat);
  return (
    <div className="traces-panel">
      <div className="chip-row" style={{ marginBottom: 10 }}>
        <button type="button" className={`chip chip-link ${cat === "all" ? "active" : ""}`} onClick={() => setCat("all")}>{tr("all")} ({data.total})</button>
        {data.categories.map((c) => (
          <button type="button" key={c} className={`chip chip-link ${cat === c ? "active" : ""}`} onClick={() => setCat(c)}>{c} ({data.by_category[c] ?? 0})</button>
        ))}
      </div>
      <div className="traces-list">
        {shown.map((t) => (
          <div className="trace-row" key={t.id}>
            <div className="trace-head">
              <strong>{t.id}</strong>
              <span className="chip">{t.patch_id}</span>
              <span className="chip">{t.category}</span>
            </div>
            <p className="muted">{t.description}</p>
            <div className="trace-meta">
              <code title={tr("container path")}>{t.container_path}</code>
              {t.enable_env
                ? <code className="trace-env" title={tr("enable env")}>{t.enable_env}=1</code>
                : <span className="muted">{tr("always on")}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
