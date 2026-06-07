// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

vi.mock("../api", () => ({ api: { jobs: vi.fn().mockResolvedValue({ jobs: [] }) } }));
import { EventLog, CliMirror, OperationalConsole } from "./operational-console";

afterEach(cleanup);

describe("EventLog", () => {
  it("renders events inside a role=log region", () => {
    render(<EventLog events={[["12:00", "info", "engine up"]]} />);
    const log = screen.getByRole("log", { name: "Event feed" });
    expect(log).toBeTruthy();
    expect(screen.getByText("engine up")).toBeTruthy();
  });
});

describe("CliMirror", () => {
  it("renders the provided lines", () => {
    render(<CliMirror lines={["sndr doctor"]} />);
    expect(screen.getByText("sndr doctor")).toBeTruthy();
  });
});

describe("OperationalConsole", () => {
  const base = {
    selectedPreset: "p27b", presetCount: 11,
    gates: [{ id: "g1", label: "engine", detail: "up", status: "pass" as const, action: "" }],
    events: [["12:00", "info", "ok"]] as Array<[string, string, string]>,
    lines: ["sndr status"],
  };

  it("exposes a WCAG tablist with the active tab selected", () => {
    render(<OperationalConsole activeTab="events" setActiveTab={vi.fn()} {...base} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(4);
    const eventsTab = screen.getByRole("tab", { name: "Events" });
    expect(eventsTab.getAttribute("aria-selected")).toBe("true");
    // events panel shows the feed
    expect(screen.getByRole("log")).toBeTruthy();
  });

  it("switches tab via setActiveTab", () => {
    const setActiveTab = vi.fn();
    render(<OperationalConsole activeTab="events" setActiveTab={setActiveTab} {...base} />);
    fireEvent.click(screen.getByRole("tab", { name: "CLI Mirror" }));
    expect(setActiveTab).toHaveBeenCalledWith("cli");
  });
});
