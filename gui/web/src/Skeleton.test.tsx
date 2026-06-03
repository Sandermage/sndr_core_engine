import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { Skeleton, SkeletonMetrics, SkeletonCards, SkeletonLines, SkeletonTable } from "./Skeleton";

afterEach(cleanup);

describe("Skeleton", () => {
  it("renders `count` blocks of the right variant", () => {
    const { container } = render(<Skeleton variant="card" count={3} />);
    const blocks = container.querySelectorAll(".skeleton.skel-card");
    expect(blocks).toHaveLength(3);
  });

  it("defaults to a single line block", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelectorAll(".skeleton.skel-line")).toHaveLength(1);
  });

  it("marks blocks aria-hidden (decorative)", () => {
    const { container } = render(<Skeleton count={2} />);
    container.querySelectorAll(".skeleton").forEach((el) => {
      expect(el.getAttribute("aria-hidden")).toBe("true");
    });
  });
});

describe("Skeleton grids", () => {
  it("SkeletonMetrics exposes a status role for screen readers", () => {
    const { container } = render(<SkeletonMetrics count={4} />);
    const grid = container.querySelector(".skel-grid.metrics");
    expect(grid?.getAttribute("role")).toBe("status");
    expect(container.querySelectorAll(".skel-metric")).toHaveLength(4);
  });

  it("SkeletonCards renders the requested cards", () => {
    const { container } = render(<SkeletonCards count={6} />);
    expect(container.querySelectorAll(".skel-grid.cards .skel-card")).toHaveLength(6);
  });

  it("SkeletonLines renders the requested lines", () => {
    const { container } = render(<SkeletonLines count={5} />);
    expect(container.querySelectorAll(".skel-grid .skel-line")).toHaveLength(5);
  });
});

describe("SkeletonTable", () => {
  it("renders a header row plus body rows with the right column count", () => {
    const { container } = render(<SkeletonTable rows={4} cols={6} />);
    const rows = container.querySelectorAll(".skel-table-row");
    expect(rows).toHaveLength(5); // 1 header + 4 body
    // Each row has `cols` cells and the requested grid template.
    rows.forEach((row) => {
      expect(row.querySelectorAll(".skel-line")).toHaveLength(6);
      expect((row as HTMLElement).style.gridTemplateColumns).toBe("repeat(6, 1fr)");
    });
  });
});
