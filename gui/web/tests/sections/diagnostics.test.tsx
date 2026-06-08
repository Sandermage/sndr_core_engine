// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { caveats: vi.fn(), configKeys: vi.fn(), traces: vi.fn() },
}));
import { api } from "@/api";
import { CaveatsPanel, ConfigKeysPanel, TracesPanel } from "@/sections/diagnostics";

afterEach(cleanup);

describe("CaveatsPanel", () => {
  it("renders caveat rows + triggered count after fetch", async () => {
    (api.caveats as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      caveats: [{ id: "c1", severity: "warning", title: "Kernel issue", message: "msg", docs_url: null, triggered: true }],
      total: 1, triggered_count: 1, host_facts_available: true, facts_error: null,
    });
    render(<CaveatsPanel />);
    await waitFor(() => expect(screen.getByText("Kernel issue")).toBeTruthy());
    expect(screen.getByText(/triggered on this host/)).toBeTruthy();
    expect(screen.getByText("fires here")).toBeTruthy();
  });
});

describe("ConfigKeysPanel", () => {
  it("renders keys + a source filter chip", async () => {
    (api.configKeys as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      keys: { GENESIS_ENABLE_X: { source: "registry" } },
      total: 1, by_source: { registry: 1 },
    });
    render(<ConfigKeysPanel />);
    await waitFor(() => expect(screen.getByText("GENESIS_ENABLE_X")).toBeTruthy());
    expect(screen.getByText("registry (1)")).toBeTruthy();
  });
});

describe("TracesPanel", () => {
  it("renders a trace row with its container path", async () => {
    (api.traces as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      traces: [{ id: "boot", container_path: "/tmp/genesis_boot.log", patch_id: "(launcher)", enable_env: null, category: "boot", description: "boot log" }],
      categories: ["boot"], by_category: { boot: 1 }, total: 1,
    });
    render(<TracesPanel />);
    await waitFor(() => expect(screen.getByText("/tmp/genesis_boot.log")).toBeTruthy());
    expect(screen.getByText("boot log")).toBeTruthy();
  });
});
