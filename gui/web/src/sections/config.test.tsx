// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", () => ({
  api: { explainPreset: vi.fn() },
}));
import { api } from "../api";
import { ConfigComparePanel, ConfigPlanPanel, ConfigApplyPanel } from "./config";

afterEach(cleanup);

describe("ConfigPlanPanel", () => {
  it("renders plan metadata + diff lines", () => {
    render(
      <ConfigPlanPanel
        plan={{
          plan_id: "plan-1", action: "write", preset_id: "p27b", target_path: "/etc/x.yaml",
          backup_path: "/etc/x.bak", apply_enabled: false, valid: true,
          blocked_reasons: [], warnings: ["heads up"], steps: [1, 2, 3],
          diff_lines: ["+ added", "- removed"],
        } as never}
      />
    );
    expect(screen.getByText("plan-1")).toBeTruthy();
    expect(screen.getByText("heads up")).toBeTruthy();
    expect(screen.getByText(/added/)).toBeTruthy();
  });
});

describe("ConfigApplyPanel", () => {
  it("renders the applied status + bytes written", () => {
    render(
      <ConfigApplyPanel
        result={{
          status: "applied", message: "ok", target_path: "/etc/x.yaml", backup_path: null,
          action: "write", bytes_written: 2048, blocked_reasons: [],
        } as never}
      />
    );
    expect(screen.getByText("Applied to disk")).toBeTruthy();
    expect(screen.getByText("2048")).toBeTruthy();
  });
});

describe("ConfigComparePanel", () => {
  it("compares two presets and surfaces a differing parameter", async () => {
    (api.explainPreset as unknown as ReturnType<typeof vi.fn>).mockImplementation((id: string) =>
      Promise.resolve({ id, composed: { gpu_util: id === "a" ? 0.9 : 0.8, model: "qwen" } })
    );
    render(<ConfigComparePanel presets={[{ id: "a" }, { id: "b" }] as never} />);
    fireEvent.click(screen.getByText("Compare"));
    await waitFor(() => expect(screen.getByText(/1 of 2 parameters differ/)).toBeTruthy());
    expect(screen.getByText("gpu_util")).toBeTruthy();
  });
});
