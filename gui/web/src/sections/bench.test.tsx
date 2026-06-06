// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { BenchmarkBaselinePanel, EvidenceRows } from "./bench";

afterEach(cleanup);

describe("BenchmarkBaselinePanel", () => {
  it("renders the baseline hero metric + runtime rows", () => {
    render(
      <BenchmarkBaselinePanel
        card={{ primary_metric: { value: 124.2, kind: "TPS", measured_at: "2026-05-11", source: "bench_suite" } }}
        composed={{ model: "qwen3.6-27b", max_model_len: 8192, kv_cache_dtype: "fp8" }}
        record={null}
        selectedPreset="a5000-2x-27b"
      />
    );
    expect(screen.getByText("124.2")).toBeTruthy();
    expect(screen.getByText("TPS")).toBeTruthy();
    expect(screen.getByText("qwen3.6-27b")).toBeTruthy();
    expect(screen.getByText("8K")).toBeTruthy();
  });

  it("shows an em-dash when no baseline metric value", () => {
    render(<BenchmarkBaselinePanel card={{}} composed={{}} record={null} selectedPreset="" />);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.getByText("no baseline metric")).toBeTruthy();
  });
});

describe("EvidenceRows", () => {
  it("renders evidence refs with visibility badges", () => {
    render(<EvidenceRows card={{ evidence_refs: [{ type: "bench", path: "/ev/a.json", visibility: "public" }] }} />);
    expect(screen.getByText("bench")).toBeTruthy();
    expect(screen.getByText("/ev/a.json")).toBeTruthy();
  });

  it("renders an empty-state row when no refs", () => {
    render(<EvidenceRows card={{}} />);
    expect(screen.getByText("No evidence refs")).toBeTruthy();
  });
});
