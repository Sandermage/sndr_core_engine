// SPDX-License-Identifier: Apache-2.0
// Command palette (Cmd/Ctrl-K): a combobox over built-in commands + searchable
// sections/presets/models. Extracted from App.tsx (modularization).
//
// Enterprise hardening over the inline original (markup classes unchanged):
//   * the combobox input and the listbox carry explicit aria-labels (a
//     placeholder is not a reliable accessible name) and aria-expanded={true};
//   * Home/End jump to the first/last result, on top of ArrowUp/Down/Enter.
import { useEffect, useRef, useState, type ReactNode, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { RefreshCw, Rocket, Terminal, ShieldCheck, PackageCheck, Rows3, Command, Settings, Search, ChevronRight } from "lucide-react";
import { type SectionId } from "../nav";
import { type GuiSettings, themeIcon, nextTheme, themeLabel } from "../settings";
import { useDialogFocus, closeOnBackdrop } from "../dialog";

export function CommandPalette({
  onClose,
  onSection,
  onRefresh,
  onShortcuts,
  settings,
  onSettings,
  searchItems
}: {
  onClose: () => void;
  onSection: (section: SectionId) => void;
  onRefresh: () => void;
  onShortcuts: () => void;
  settings: GuiSettings;
  onSettings: (patch: Partial<GuiSettings>) => void;
  searchItems: Array<{ icon: ReactNode; title: string; detail: string; keep?: boolean; run: () => void }>;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  useDialogFocus(dialogRef);
  const commands: Array<{ icon: ReactNode; title: string; detail: string; keep?: boolean; run: () => void }> = [
    { icon: <RefreshCw size={16} />, title: "Sync Catalog", detail: "Refresh overview, presets, patch registry and doctor state", run: onRefresh },
    { icon: <Rocket size={16} />, title: "Open Launch Plan", detail: "Recommendation builder and launch composer", run: () => onSection("launch-plan") },
    { icon: <Terminal size={16} />, title: "Open Operations", detail: "Run project maintenance and diagnostic workflows", run: () => onSection("operations") },
    { icon: <ShieldCheck size={16} />, title: "Run Doctor View", detail: "Readiness gates and registry doctor panel", run: () => onSection("doctor") },
    { icon: <PackageCheck size={16} />, title: "Patch Matrix", detail: "Patch lifecycle, default policy and registry coverage", run: () => onSection("patches") },
    { icon: themeIcon(nextTheme(settings.theme)), title: "Toggle Theme", detail: `Cycle themes (next: ${themeLabel(nextTheme(settings.theme))})`, keep: true, run: () => onSettings({ theme: nextTheme(settings.theme) }) },
    { icon: <Rows3 size={16} />, title: "Toggle Density", detail: "Switch comfortable/compact density", keep: true, run: () => onSettings({ density: settings.density === "compact" ? "comfortable" : "compact" }) },
    { icon: <Command size={16} />, title: "Keyboard Shortcuts", detail: "Show all shortcuts and navigation chords (?)", run: onShortcuts },
    { icon: <Settings size={16} />, title: "Settings", detail: "Appearance, API, schema and admin", run: () => onSection("advanced") }
  ];
  const all = [...commands, ...searchItems];
  const q = query.trim().toLowerCase();
  const shown = (q ? all.filter((item) => `${item.title} ${item.detail}`.toLowerCase().includes(q)) : commands).slice(0, 40);
  // Keep the highlighted index in range as the filtered set shrinks/grows.
  const activeIndex = Math.min(active, Math.max(0, shown.length - 1));
  // Reset the highlight to the top whenever the query changes.
  useEffect(() => { setActive(0); }, [q]);
  // Scroll the highlighted row into view as it moves past the visible window.
  useEffect(() => {
    const row = listRef.current?.children[activeIndex] as HTMLElement | undefined;
    row?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);
  const runAt = (index: number) => {
    const item = shown[index];
    if (!item) return;
    item.run();
    if (!item.keep) onClose();
  };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, shown.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(Math.max(0, shown.length - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      runAt(activeIndex);
    }
  };
  return (
    <div className="dialog-backdrop" role="presentation" onClick={closeOnBackdrop(onClose)}>
      <section ref={dialogRef} className="command-dialog" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="command-search">
          <Search size={16} />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search commands, sections, presets, models, configs, patches…" spellCheck={false}
            role="combobox" aria-label="Search commands and sections" aria-expanded={true} aria-controls="command-list" aria-activedescendant={shown[activeIndex] ? `command-item-${activeIndex}` : undefined}
            onKeyDown={onKeyDown} />
          <kbd>esc</kbd>
        </div>
        <div className="command-list" id="command-list" role="listbox" aria-label="Commands" ref={listRef}>
          {shown.map((item, index) => (
            <button
              key={`${item.title}-${index}`}
              id={`command-item-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              className={index === activeIndex ? "active" : ""}
              onMouseMove={() => setActive(index)}
              onClick={() => runAt(index)}
            >
              {item.icon}
              <span>
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </span>
              <ChevronRight size={16} />
            </button>
          ))}
          {shown.length === 0 && <p className="muted command-empty">No matches for “{query}”.</p>}
        </div>
      </section>
    </div>
  );
}
