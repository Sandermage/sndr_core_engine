// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", () => ({
  api: { patchOverrides: vi.fn().mockResolvedValue({ overrides: {} }), patchExplain: vi.fn().mockResolvedValue({ spec: {}, meta: {} }), setPatchOverride: vi.fn() },
}));
import { PatchInventoryControl } from "./patch-inventory";

afterEach(cleanup);

const patches = [
  { patch_id: "P94", title: "zero-alloc", family: "spec_decode", tier: "community", lifecycle: "stable", production_default: "applied", env_flag: "GENESIS_ENABLE_P94", apply_module: "sndr.p94", upstream_pr: 41043 },
  { patch_id: "PN26b", title: "sparse-V", family: "attention", tier: "community", lifecycle: "experimental", production_default: "opt-in", env_flag: "GENESIS_ENABLE_PN26B", apply_module: "sndr.pn26b", upstream_pr: null },
] as never;

describe("PatchInventoryControl", () => {
  it("renders family groups with accessible filters", async () => {
    render(<PatchInventoryControl patches={patches} />);
    expect(screen.getByLabelText("Filter patches")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Patch grouping" })).toBeTruthy();
    expect(screen.getByText(/2 matched · 2 families/)).toBeTruthy();
    // selected patch drives the explain panel (loads via mocked api)
    await waitFor(() => expect(screen.getAllByText("P94").length).toBeGreaterThan(0));
  });

  it("filters patches via the search box", async () => {
    render(<PatchInventoryControl patches={patches} />);
    fireEvent.change(screen.getByLabelText("Filter patches"), { target: { value: "sparse" } });
    expect(screen.getByText(/1 matched/)).toBeTruthy();
  });

  it("switches to the flat list view with scope=col headers", () => {
    const { container } = render(<PatchInventoryControl patches={patches} />);
    fireEvent.click(screen.getByRole("button", { name: "Flat list" }));
    expect(container.querySelectorAll('th[scope="col"]').length).toBe(6);
  });
});
