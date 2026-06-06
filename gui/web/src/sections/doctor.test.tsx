// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { DoctorSummary, DoctorFindings } from "./doctor";

afterEach(cleanup);

const report = {
  summary: { ok: 3, info: 1, warning: 2, blocked: 1 },
  categories: ["Runtime", "Storage"],
  warnings: ["disk almost full"],
  findings: [
    { id: "f1", category: "Runtime", severity: "blocked", title: "Engine down", detail: "no heartbeat", evidence: "exit 137", action: "restart", cli: "sndr engine restart" },
    { id: "f2", category: "Runtime", severity: "ok", title: "Pins healthy", detail: "all good" },
    { id: "f3", category: "Storage", severity: "warning", title: "Low disk", detail: "12% left" },
  ],
};

describe("DoctorSummary", () => {
  it("renders a skeleton message when report is null", () => {
    render(<DoctorSummary report={null} />);
    expect(screen.getByText("Running diagnostics…")).toBeTruthy();
  });

  it("renders severity stats + a warning note", () => {
    render(<DoctorSummary report={report as never} />);
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.getByText("Blocked")).toBeTruthy();
    expect(screen.getByText("disk almost full")).toBeTruthy();
  });
});

describe("DoctorFindings", () => {
  it("renders one collapsible category per report category", () => {
    render(<DoctorFindings report={report as never} />);
    expect(screen.getByText("Runtime")).toBeTruthy();
    expect(screen.getByText("Storage")).toBeTruthy();
    // Runtime has a blocked finding → expanded by default, so its title shows.
    expect(screen.getByText("Engine down")).toBeTruthy();
  });

  it("reveals finding evidence + cli on expand", () => {
    render(<DoctorFindings report={report as never} />);
    fireEvent.click(screen.getByText("Engine down"));
    expect(screen.getByText("exit 137")).toBeTruthy();
    expect(screen.getByText("sndr engine restart")).toBeTruthy();
  });
});
