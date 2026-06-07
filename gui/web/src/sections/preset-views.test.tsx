// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("../api", () => ({ api: { v2ConfigPreview: vi.fn() } }));
import { PresetSummaryStrip, PresetSelectedView } from "./preset-views";

afterEach(cleanup);

const presets = [
  { id: "p1", model: "qwen3.6-27b", hardware: "2× A5000", has_card: true, card: { status: "available" } },
  { id: "p2", model: "qwen3.6-35b", hardware: "2× A5000", has_card: false, card: null },
] as never;

describe("PresetSummaryStrip", () => {
  it("renders preset/annotation counts + the selected id", () => {
    render(<PresetSummaryStrip presets={presets} selectedPreset="p1" />);
    expect(screen.getByText("Presets")).toBeTruthy();
    expect(screen.getByText("p1")).toBeTruthy();
  });
});

describe("PresetSelectedView", () => {
  it("renders the what-will-run summary for a selected preset", () => {
    render(
      <PresetSelectedView
        selectedPreset="a5000-2x-27b"
        record={{ model: "qwen3.6-27b", hardware: "2× A5000", profile: "tq" } as never}
        card={{ title: "27B TQ" }}
        composed={{ max_model_len: 8192, kv_cache_dtype: "fp8" }}
        explain={null}
        runtimeTargets={[{ id: "docker", title: "Docker", status: "available", required_tools: [], detail: "" }] as never}
        runtimeTarget="docker"
        patchPolicy="safe"
        onEdit={vi.fn()}
        onLaunch={vi.fn()}
        onConfigs={vi.fn()}
      />
    );
    expect(screen.getByText("a5000-2x-27b")).toBeTruthy();
    // targetTitle resolves docker -> Docker
    expect(screen.getAllByText(/Docker/).length).toBeGreaterThan(0);
  });
});
