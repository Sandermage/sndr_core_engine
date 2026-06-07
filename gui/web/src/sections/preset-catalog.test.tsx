// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { PresetBaselineCell, PresetCatalogTable } from "./preset-catalog";

afterEach(cleanup);

const presets = [
  { id: "p-fast", model: "qwen3.6-27b", hardware: "2× A5000", profile: "tq", has_card: true, card: { status: "available", primary_metric: { value: 124, kind: "TPS" } } },
  { id: "p-pending", model: "qwen3.6-35b", hardware: "2× A5000", profile: "fp8", has_card: false, card: null },
] as never;

describe("PresetBaselineCell", () => {
  it("renders a measured value chip", () => {
    render(<PresetBaselineCell card={{ primary_metric: { value: 124, kind: "TPS" } }} />);
    expect(screen.getByText(/124 TPS/)).toBeTruthy();
  });
  it("renders a pending chip when no value", () => {
    render(<PresetBaselineCell card={{ primary_metric: { kind: "TPS" } }} />);
    expect(screen.getByText("pending")).toBeTruthy();
  });
});

describe("PresetCatalogTable", () => {
  it("renders rows + selects a preset on row-button click", () => {
    const onPreset = vi.fn();
    render(<PresetCatalogTable presets={presets} selectedPreset="" onPreset={onPreset} />);
    fireEvent.click(screen.getByText("p-fast"));
    expect(onPreset).toHaveBeenCalledWith("p-fast");
  });

  it("filters to bench-proven presets", () => {
    render(<PresetCatalogTable presets={presets} selectedPreset="" onPreset={vi.fn()} />);
    fireEvent.click(screen.getByText(/bench-proven/));
    expect(screen.getByText("p-fast")).toBeTruthy();
    expect(screen.queryByText("p-pending")).toBeNull();
  });

  it("shows an empty state with a clear-filters action when filters exclude all", () => {
    render(<PresetCatalogTable presets={presets} selectedPreset="" onPreset={vi.fn()} />);
    // bench-proven keeps only p-fast (status "available"); the "missing" status
    // chip then matches only p-pending -> 0 rows.
    fireEvent.click(screen.getByText(/bench-proven/));
    fireEvent.click(screen.getByText(/missing/));
    const status = screen.getByRole("status");
    expect(within(status).getByText("No presets for this filter")).toBeTruthy();
    expect(within(status).getByText("Clear filters")).toBeTruthy();
  });
});
