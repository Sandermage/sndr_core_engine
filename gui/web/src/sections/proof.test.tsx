// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ProofStatusPanel } from "./proof";

afterEach(cleanup);

const report = {
  available: true,
  total: 4,
  counts: { bench_with_baseline: 2, dead: 1, static_only: 1 },
  patches: [
    { patch_id: "P1", bucket: "bench_with_baseline", family: "attention", tier: "community", lifecycle: "stable", artefacts: ["a.json"] },
    { patch_id: "P2", bucket: "dead", family: "moe", tier: "community", lifecycle: "experimental", artefacts: [] },
  ],
};

describe("ProofStatusPanel", () => {
  it("renders a skeleton when report is null", () => {
    const { container } = render(<ProofStatusPanel report={null} />);
    expect(container.querySelector(".skeleton-lines, [class*=skeleton]")).not.toBeNull();
  });

  it("renders the unavailable state with reason", () => {
    render(<ProofStatusPanel report={{ available: false, reason: "not initialized", total: 0, counts: {}, patches: [] } as never} />);
    expect(screen.getByText("not initialized")).toBeTruthy();
  });

  it("renders buckets + per-patch drill-down for an available report", () => {
    render(<ProofStatusPanel report={report as never} />);
    // segment total + foot
    expect(screen.getByText(/2 patches indexed/)).toBeTruthy();
    // drill-down rows surface the patch ids
    expect(screen.getByText("P1")).toBeTruthy();
    expect(screen.getByText("P2")).toBeTruthy();
    // bucket distribution meaning text
    expect(screen.getByText("No artifact / dead reference")).toBeTruthy();
  });
});
