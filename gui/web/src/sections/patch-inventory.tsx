// SPDX-License-Identifier: Apache-2.0
// Patch inventory control — the patches-tab registry browser: search + lifecycle
// /default filters, by-family or flat view, and a linked PatchExplainPanel for
// the selected patch. Extracted from App.tsx (modularization).
//
// Enterprise hardening over the inline originals (classes unchanged):
//   * filter input + the two selects carry aria-labels (placeholders aren't
//     reliable accessible names);
//   * the by-family/flat segmented control is a role="group" with aria-pressed;
//   * each family group is a WCAG disclosure — aria-controls points at its rows.
import { useEffect, useId, useMemo, useState } from "react";
import { Search, PackageCheck, X, ChevronRight } from "lucide-react";
import { api, type PatchRow, type PatchExplainResult } from "../api";
import { StatusBadge } from "../components/primitives";
import { EmptyState } from "../components/empty-state";
import { PatchExplainPanel } from "./patch-explain";
import { tr } from "../i18n";

function PatchFamilyGroup({
  family,
  rows,
  selectedId,
  onSelect
}: {
  family: string;
  rows: PatchRow[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rowsId = useId();
  const applied = rows.filter((row) => row.production_default === "applied").length;
  const hasSelected = rows.some((row) => row.patch_id === selectedId);
  // Auto-open the group when a patch inside it becomes selected, but only on the
  // transition — so a manual collapse still wins while the selection stays here.
  useEffect(() => {
    if (hasSelected) setOpen(true);
  }, [hasSelected]);
  const expanded = open;
  return (
    <section className={`patch-family ${expanded ? "open" : ""}`}>
      <button className="patch-family-head" onClick={() => setOpen((value) => !value)} aria-expanded={expanded} aria-controls={rowsId}>
        <ChevronRight className="coll-caret" size={14} />
        <strong>{family}</strong>
        <span className="patch-family-count">{rows.length}</span>
        <em>{applied} {tr("applied")}</em>
      </button>
      {expanded && (
        <div className="patch-family-rows" id={rowsId}>
          {rows.map((patch) => (
            <button
              key={patch.patch_id}
              className={`patch-row-mini ${patch.patch_id === selectedId ? "active" : ""}`}
              onClick={() => onSelect(patch.patch_id)}
            >
              <strong>{patch.patch_id}</strong>
              <StatusBadge status={patch.lifecycle} />
              <span className="patch-row-default">{tr(patch.production_default)}</span>
              <small>{patch.title}</small>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function PatchInventoryControl({ patches }: { patches: PatchRow[] }) {
  const [needle, setNeedle] = useState("");
  const [lifecycle, setLifecycle] = useState("all");
  const [productionDefault, setProductionDefault] = useState("all");
  const [groupByFamily, setGroupByFamily] = useState(true);
  const [selectedPatchId, setSelectedPatchId] = useState<string>("");
  const [patchExplain, setPatchExplain] = useState<PatchExplainResult | null>(null);
  const [patchExplainState, setPatchExplainState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [patchExplainError, setPatchExplainError] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, { state: string; env_flag: string }>>({});
  useEffect(() => { api.patchOverrides().then((o) => setOverrides(o.overrides)).catch(() => {}); }, []);
  const lifecycleOptions = Array.from(new Set(patches.map((patch) => patch.lifecycle))).sort();
  const defaultOptions = Array.from(new Set(patches.map((patch) => patch.production_default))).sort();
  const visibleRows = patches.filter((patch) => {
    const haystack = [
      patch.patch_id,
      patch.title,
      patch.family,
      patch.tier,
      patch.lifecycle,
      patch.production_default,
      patch.env_flag,
      patch.apply_module
    ].join(" ").toLowerCase();
    return (
      (!needle.trim() || haystack.includes(needle.trim().toLowerCase())) &&
      (lifecycle === "all" || patch.lifecycle === lifecycle) &&
      (productionDefault === "all" || patch.production_default === productionDefault)
    );
  });
  const selectedPatch = visibleRows.find((patch) => patch.patch_id === selectedPatchId) ?? visibleRows[0] ?? null;
  // Set of every registered patch id — lets the explain panel turn
  // requires/conflicts into clickable links to navigable patches.
  const patchIdSet = useMemo(() => new Set(patches.map((p) => p.patch_id)), [patches]);
  const familyGroups = useMemo(() => {
    const map = new Map<string, PatchRow[]>();
    visibleRows.forEach((patch) => {
      const family = patch.family || "other";
      map.set(family, [...(map.get(family) ?? []), patch]);
    });
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length);
    // visibleRows is recomputed per render; intentional for ~230 rows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needle, lifecycle, productionDefault, patches]);

  useEffect(() => {
    if (!selectedPatch?.patch_id) {
      setPatchExplain(null);
      setPatchExplainState("idle");
      return;
    }
    let cancelled = false;
    setPatchExplainState("loading");
    setPatchExplainError(null);
    api.patchExplain(selectedPatch.patch_id)
      .then((detail) => {
        if (cancelled) return;
        setPatchExplain(detail);
        setPatchExplainState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setPatchExplain(null);
        setPatchExplainState("error");
        setPatchExplainError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPatch?.patch_id]);

  return (
    <div className="patch-control">
      <div className="patch-control-toolbar">
        <label className="search-box">
          <Search size={15} />
          <input
            value={needle}
            onChange={(event) => setNeedle(event.target.value)}
            placeholder={tr("Filter patch id, family, env flag")}
            aria-label={tr("Filter patches")}
          />
        </label>
        <select value={lifecycle} onChange={(event) => setLifecycle(event.target.value)} aria-label={tr("Filter by lifecycle")}>
          <option value="all">{tr("All lifecycles")}</option>
          {lifecycleOptions.map((item) => <option key={item} value={item}>{tr(item)}</option>)}
        </select>
        <select value={productionDefault} onChange={(event) => setProductionDefault(event.target.value)} aria-label={tr("Filter by production default")}>
          <option value="all">{tr("All defaults")}</option>
          {defaultOptions.map((item) => <option key={item} value={item}>{tr(item)}</option>)}
        </select>
        <div className="settings-segmented" role="group" aria-label={tr("Patch grouping")}>
          <button className={groupByFamily ? "active" : ""} aria-pressed={groupByFamily} onClick={() => setGroupByFamily(true)}>{tr("By family")}</button>
          <button className={!groupByFamily ? "active" : ""} aria-pressed={!groupByFamily} onClick={() => setGroupByFamily(false)}>{tr("Flat list")}</button>
        </div>
        <span>{visibleRows.length} {tr("matched")} · {familyGroups.length} {tr("families")}</span>
      </div>
      <div className="patch-control-grid">
        <div className="patch-table-scroll">
          {groupByFamily ? (
            <div className="patch-family-groups">
              {familyGroups.map(([family, rows]) => (
                <PatchFamilyGroup
                  key={family}
                  family={family}
                  rows={rows}
                  selectedId={selectedPatch?.patch_id ?? ""}
                  onSelect={setSelectedPatchId}
                />
              ))}
              {familyGroups.length === 0 && (() => {
                const filtered = needle.trim() !== "" || lifecycle !== "all" || productionDefault !== "all";
                return (
                  <EmptyState
                    icon={<PackageCheck size={22} />}
                    title={tr("No patches match")}
                    message={filtered ? tr("No patches in the registry match the active filters.") : tr("The patch registry is empty.")}
                    action={filtered ? { label: tr("Clear filters"), icon: <X size={14} />, onClick: () => { setNeedle(""); setLifecycle("all"); setProductionDefault("all"); } } : undefined}
                  />
                );
              })()}
            </div>
          ) : (
            <table className="module-table patch-table patch-table--flat">
              <colgroup>
                <col style={{ width: "17%" }} />
                <col style={{ width: "12%" }} />
                <col style={{ width: "11%" }} />
                <col style={{ width: "12%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "38%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">{tr("Patch")}</th>
                  <th scope="col">{tr("Lifecycle")}</th>
                  <th scope="col">{tr("Default")}</th>
                  <th scope="col">{tr("Family")}</th>
                  <th scope="col">{tr("Upstream")}</th>
                  <th scope="col">{tr("Title")}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((patch) => (
                  <tr
                    className={`patch-flat-row ${selectedPatch?.patch_id === patch.patch_id ? "selected-row" : ""}`}
                    key={patch.patch_id}
                  >
                    <td>
                      <button className="link-button" onClick={() => setSelectedPatchId(patch.patch_id)}>
                        <strong>{patch.patch_id}</strong>
                        <small>{patch.env_flag || patch.tier}</small>
                      </button>
                    </td>
                    <td><StatusBadge status={patch.lifecycle} /></td>
                    <td>{tr(patch.production_default)}</td>
                    <td>{patch.family || "-"}</td>
                    <td>{patch.upstream_pr ? `#${patch.upstream_pr}` : "-"}</td>
                    <td>{patch.title}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <PatchExplainPanel
          patch={selectedPatch}
          detail={patchExplain}
          state={patchExplainState}
          error={patchExplainError}
          allPatchIds={patchIdSet}
          onSelectPatch={(id) => setSelectedPatchId(id)}
          override={overrides[selectedPatch?.patch_id ?? ""]?.state ?? "default"}
          overrideCount={Object.keys(overrides).length}
          onSetOverride={async (state) => {
            if (!selectedPatch) return;
            try {
              const res = await api.setPatchOverride(selectedPatch.patch_id, state, selectedPatch.env_flag);
              setOverrides(res.overrides);
            } catch { /* surfaced inline */ }
          }}
        />
      </div>
    </div>
  );
}
