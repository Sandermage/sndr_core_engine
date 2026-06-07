// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", () => ({ api: { recommendPresets: vi.fn() } }));
import { api } from "../api";
import { PresetRecommendPanel } from "./preset-recommend";

afterEach(cleanup);

const result = {
  total_matches: 1, total_candidates: 3,
  results: [{ id: "a5000-2x-27b", rank: 1, model: "qwen3.6-27b", hardware: "2× A5000", profile: "tq", card: { status: "available", primary_metric: { value: 124, kind: "TPS" } } }],
};

describe("PresetRecommendPanel", () => {
  it("ranks presets on mount + renders the results table with scope=col", async () => {
    (api.recommendPresets as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(result);
    const { container } = render(<PresetRecommendPanel hardwareOptions={["a5000-2x"]} workloadCounts={{ free_chat: 4 }} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/1 of 3 candidates match/)).toBeTruthy());
    expect(screen.getByRole("group", { name: "Workload" })).toBeTruthy();
    expect(container.querySelectorAll('th[scope="col"]').length).toBe(7);
  });

  it("selects a preset from the inspect action", async () => {
    (api.recommendPresets as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(result);
    const onSelect = vi.fn();
    render(<PresetRecommendPanel hardwareOptions={["a5000-2x"]} workloadCounts={{}} onSelect={onSelect} />);
    await waitFor(() => expect(screen.getByText("Inspect")).toBeTruthy());
    fireEvent.click(screen.getByText("Inspect"));
    expect(onSelect).toHaveBeenCalledWith("a5000-2x-27b");
  });

  it("shows an empty state when no presets match", async () => {
    (api.recommendPresets as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ total_matches: 0, total_candidates: 3, results: [] });
    render(<PresetRecommendPanel hardwareOptions={["a5000-2x"]} workloadCounts={{}} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("No presets match")).toBeTruthy());
  });
});
