// SPDX-License-Identifier: Apache-2.0
// Operational console — a unified tabbed surface over jobs, events, synthesized
// logs and the CLI mirror. Extracted from App.tsx (modularization).
//
// Enterprise hardening over the inline originals (markup classes unchanged):
//   * the tab strip is a real WCAG tablist — role="tablist"/"tab" with
//     aria-selected, and the body is a role="tabpanel"; assistive tech now
//     announces the tab relationship and the selected tab;
//   * the event feed is a role="log" so screen readers treat it as a live log.
import { type ConsoleTab } from "../settings";
import { type Gate } from "../nav";
import { CodeBlock } from "../components/code-block";
import { JobsTable } from "./jobs";

export function EventLog({ events }: { events: Array<[string, string, string]> }) {
  return (
    <section className="event-log">
      <div className="event-list" role="log" aria-label="Event feed">
        {events.map(([time, tone, text], index) => (
          <div className="event-row" key={`${index}-${time}`}>
            <span>{time}</span>
            <em className={tone}>{tone}</em>
            <p>{text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function CliMirror({ lines }: { lines: string[] }) {
  return (
    <section className="cli-mirror">
      <CodeBlock lines={lines} title="CLI mirror" />
    </section>
  );
}

const CONSOLE_TABS: Array<{ id: ConsoleTab; label: string }> = [
  { id: "jobs", label: "Jobs" },
  { id: "events", label: "Events" },
  { id: "logs", label: "Logs" },
  { id: "cli", label: "CLI Mirror" }
];

export function OperationalConsole({
  activeTab,
  setActiveTab,
  selectedPreset,
  presetCount,
  gates,
  events,
  lines,
  onMonitor
}: {
  activeTab: ConsoleTab;
  setActiveTab: (tab: ConsoleTab) => void;
  selectedPreset: string;
  presetCount: number;
  gates: Gate[];
  events: Array<[string, string, string]>;
  lines: string[];
  onMonitor?: (id: string) => void;
}) {
  const blockedGates = gates.filter((gate) => gate.status === "blocked");
  const warnGates = gates.filter((gate) => gate.status === "warning");
  const logLines = [
    `[catalog] registry loaded ${presetCount} presets`,
    `[planner] dry-run launch plan ready for ${selectedPreset}`,
    `[doctor] ${gates.filter((gate) => gate.status === "pass").length}/${gates.length} readiness gates passing`,
    ...warnGates.map((gate) => `[gate] warning: ${gate.label} — ${gate.detail}`),
    ...blockedGates.map((gate) => `[gate] blocked: ${gate.label} — ${gate.detail}`)
  ];

  return (
    <section className="operational-console">
      <div className="console-tabs unified" role="tablist" aria-label="Operational console">
        {CONSOLE_TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? "active" : ""}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={CONSOLE_TABS.find((t) => t.id === activeTab)?.label ?? "Console"}>
        {activeTab === "jobs" && <JobsTable onMonitor={onMonitor} />}
        {activeTab === "events" && <EventLog events={events} />}
        {activeTab === "logs" && (
          <section className="cli-mirror">
            <CodeBlock lines={logLines} title="Logs" />
          </section>
        )}
        {activeTab === "cli" && <CliMirror lines={lines} />}
      </div>
    </section>
  );
}
