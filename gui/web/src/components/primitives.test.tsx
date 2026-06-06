// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { StatusBadge, StatusPill, InfoRows, CompactList, DoctorStat, CapChip } from "./primitives";

afterEach(cleanup);

describe("StatusBadge", () => {
  it("renders status with underscores as spaces + status class", () => {
    const { container } = render(<StatusBadge status="in_sync" />);
    const el = container.querySelector("span.status-badge");
    expect(el).not.toBeNull();
    expect(el!.className).toContain("in_sync");
    expect(el!.textContent).toBe("in sync");
  });
});

describe("StatusPill", () => {
  it("renders children with the default neutral tone", () => {
    const { container } = render(<StatusPill>hi</StatusPill>);
    const el = container.querySelector("span.status-pill");
    expect(el!.className).toContain("neutral");
    expect(el!.textContent).toBe("hi");
  });
  it("applies an explicit tone", () => {
    const { container } = render(<StatusPill tone="danger">x</StatusPill>);
    expect(container.querySelector("span.status-pill")!.className).toContain("danger");
  });
});

describe("InfoRows", () => {
  it("renders one row per [label, value]", () => {
    const { container } = render(<InfoRows rows={[["A", "1"], ["B", 2]]} />);
    expect(container.querySelectorAll(".info-rows > div").length).toBe(2);
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });
});

describe("CompactList", () => {
  it("renders rows when present", () => {
    const { container } = render(<CompactList rows={[["k", "v"]]} />);
    expect(container.querySelectorAll(".compact-list > div").length).toBe(1);
  });
  it("shows the empty message when no rows", () => {
    render(<CompactList rows={[]} />);
    expect(screen.getByText("No rows for this view.")).toBeTruthy();
  });
});

describe("DoctorStat", () => {
  it("renders value + label with a tone class", () => {
    const { container } = render(<DoctorStat tone="ok" value={7} label="Healthy" />);
    const el = container.querySelector(".doctor-stat");
    expect(el!.className).toContain("tone-ok");
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
  });
});

describe("CapChip", () => {
  it("renders an on-state chip", () => {
    const { container } = render(<CapChip on={true} label="GPU" />);
    expect(container.querySelector(".cap-chip.on")).not.toBeNull();
    expect(screen.getByText("GPU")).toBeTruthy();
  });
  it("renders an off-state chip", () => {
    const { container } = render(<CapChip on={false} label="Docker" />);
    expect(container.querySelector(".cap-chip.off")).not.toBeNull();
  });
});
