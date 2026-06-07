// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { RuntimeEndpoint, BenchmarkCard, EvidenceCard, PatchMatrix, EndpointRows } from "./rail-cards";

afterEach(cleanup);

describe("EndpointRows", () => {
  it("renders copyable endpoint rows derived from the host", () => {
    const { container } = render(<EndpointRows host="10.0.0.9" />);
    const inputs = Array.from(container.querySelectorAll("input")) as HTMLInputElement[];
    expect(inputs.some((i) => i.value === "http://10.0.0.9:8000/v1")).toBe(true);
    expect(screen.getByText("Health")).toBeTruthy();
  });
});

describe("RuntimeEndpoint", () => {
  it("renders default endpoint rows derived from the host", () => {
    const { container } = render(<RuntimeEndpoint host="10.0.0.5" />);
    const inputs = Array.from(container.querySelectorAll("input")) as HTMLInputElement[];
    expect(inputs.some((i) => i.value === "http://10.0.0.5:8000/v1")).toBe(true);
    expect(screen.getByText("Metrics")).toBeTruthy();
  });
});

describe("BenchmarkCard", () => {
  it("shows a metric value + fires onRun", () => {
    const onRun = vi.fn();
    render(<BenchmarkCard metricKind="TPS" metricValue={124} context={8192} visibility="public" onRun={onRun} />);
    expect(screen.getByText("124")).toBeTruthy();
    expect(screen.getByText("High")).toBeTruthy();
    fireEvent.click(screen.getByText("Run benchmark"));
    expect(onRun).toHaveBeenCalled();
  });
});

describe("EvidenceCard", () => {
  it("toggles the details expander", () => {
    render(<EvidenceCard visibility="private" evidenceCount={2} />);
    expect(screen.queryByText(/evidence references attached/)).toBeNull();
    fireEvent.click(screen.getByText("Show details"));
    expect(screen.getByText(/2 evidence references attached/)).toBeTruthy();
  });
});

describe("PatchMatrix", () => {
  it("renders policy rows + fires onExplain", () => {
    const onExplain = vi.fn();
    render(
      <PatchMatrix
        summary={{ production_default_counts: { applied: 40, marker: 5, "opt-in": 3, blocked: 1 } } as never}
        registryTotal={134}
        selectedCount={12}
        onExplain={onExplain}
      />
    );
    expect(screen.getByText("134 in registry")).toBeTruthy();
    expect(screen.getByText("Applied")).toBeTruthy();
    fireEvent.click(screen.getByText("Explain"));
    expect(onExplain).toHaveBeenCalled();
  });
});
