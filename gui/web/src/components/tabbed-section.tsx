// SPDX-License-Identifier: Apache-2.0
// Reusable WCAG APG tablist: roving tabindex + arrow/Home/End keyboard nav,
// aria-selected/controls wiring and a labelled tabpanel. Supports an optional
// controlled mode so a parent can drive the active tab.
import { useEffect, useState, type ReactNode } from "react";

export function TabbedSection({
  id,
  tabs,
  activeTab,
  onTabChange
}: {
  id: string;
  tabs: Array<{ id: string; label: string; icon?: ReactNode; render: () => ReactNode }>;
  // Optional controlled mode: when provided, the parent owns the active tab so
  // in-panel buttons (e.g. "Edit preset") can switch tabs programmatically.
  activeTab?: string;
  onTabChange?: (id: string) => void;
}) {
  const [internal, setInternal] = useState(tabs[0]?.id ?? "");
  const active = activeTab ?? internal;
  const setActive = (next: string) => {
    if (onTabChange) onTabChange(next);
    else setInternal(next);
  };
  // Reset to the first tab when the section changes (component is keyed per section).
  useEffect(() => {
    if (activeTab === undefined) setInternal(tabs[0]?.id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];
  const activeIndex = Math.max(0, tabs.findIndex((tab) => tab.id === current?.id));
  // WCAG APG tabs pattern: roving tabindex + arrow/Home/End keyboard navigation.
  const onTabKey = (event: { key: string; preventDefault: () => void }) => {
    const keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
    if (!keys.includes(event.key) || tabs.length === 0) return;
    event.preventDefault();
    let next = activeIndex;
    if (event.key === "ArrowRight") next = (activeIndex + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (activeIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    setActive(tabs[next].id);
  };
  return (
    <div className="section-tabs-wrap">
      {/* eslint-disable-next-line jsx-a11y/interactive-supports-focus -- ARIA tablist uses roving tabindex on the tabs; the container itself is not focusable by design */}
      <div className="section-tabs" role="tablist" onKeyDown={onTabKey}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`${id}-tab-${tab.id}`}
            aria-selected={tab.id === current?.id}
            aria-controls={`${id}-panel-${tab.id}`}
            tabIndex={tab.id === current?.id ? 0 : -1}
            className={tab.id === current?.id ? "active" : ""}
            onClick={() => setActive(tab.id)}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>
      <div
        className="section-tab-body"
        role="tabpanel"
        id={`${id}-panel-${current?.id}`}
        aria-labelledby={`${id}-tab-${current?.id}`}
      >
        {current?.render()}
      </div>
    </div>
  );
}
