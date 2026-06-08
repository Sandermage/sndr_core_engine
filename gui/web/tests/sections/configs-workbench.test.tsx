// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { v2ConfigPreview: vi.fn(), v2ConfigPlan: vi.fn(), v2ConfigApply: vi.fn(), v2Layer: vi.fn(), v2LayerApply: vi.fn() },
}));
import { ConfigsSection } from "@/sections/configs-workbench";

afterEach(cleanup);

const base = {
  catalog: { models: [], hardware: [], profiles: [], presets: [] } as never,
  preview: null,
  selectedPreset: "",
  userPresets: null,
  onPreview: vi.fn(),
  onUserPresetsRefresh: vi.fn(),
};

describe("ConfigsSection", () => {
  it("renders the compose/edit top tabs and defaults to compose", () => {
    render(<ConfigsSection {...base} />);
    expect(screen.getByText("Compose")).toBeTruthy();
    expect(screen.getByText("Edit element")).toBeTruthy();
    expect(screen.getByText("Compose").closest("button")!.className).toContain("active");
  });

  it("switches to the edit-element tab", () => {
    render(<ConfigsSection {...base} />);
    fireEvent.click(screen.getByText("Edit element"));
    expect(screen.getByText("Edit element").closest("button")!.className).toContain("active");
  });
});
