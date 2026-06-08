// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({ api: { v2Layer: vi.fn(), v2LayerApply: vi.fn() } }));
import { api } from "@/api";
import { LayerEditor } from "@/sections/layer-editor";

afterEach(cleanup);

describe("LayerEditor", () => {
  it("loads a layer definition and renders its source + a save action", async () => {
    (api.v2Layer as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      definition: { title: "Qwen 27B", capabilities: { kv_cache_dtype: "fp8" } },
      source: "builtin: a5000-2x-27b",
    });
    render(<LayerEditor kind="model" layerId="qwen3.6-27b" />);
    await waitFor(() => expect(screen.getByText("builtin: a5000-2x-27b")).toBeTruthy());
    expect(screen.getByText("Save to user dir")).toBeTruthy();
  });

  it("shows a placeholder when no layer is selected", () => {
    render(<LayerEditor kind="preset" layerId="" />);
    expect(screen.getByText(/Select a preset to edit/)).toBeTruthy();
  });

  it("saves an operator-local copy via v2LayerApply", async () => {
    (api.v2Layer as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ definition: { title: "X" }, source: "builtin" });
    (api.v2LayerApply as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "applied", target_path: "/user/x.yaml", message: "ok" });
    render(<LayerEditor kind="model" layerId="m1" />);
    await waitFor(() => expect(screen.getByText("Save to user dir")).toBeTruthy());
    fireEvent.click(screen.getByText("Save to user dir"));
    await waitFor(() => expect(api.v2LayerApply).toHaveBeenCalled());
  });
});
