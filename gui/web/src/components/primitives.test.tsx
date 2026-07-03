// SPDX-License-Identifier: Apache-2.0
// Smoke tests for the shared presentational primitives that every panel is
// built from — if one of these throws or drops its content, the panels that
// compose them regress silently. We render each and assert the visible output.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CapChip,
  DoctorStat,
  InfoRows,
  KpiGrid,
  StatusBadge,
  StatusPill,
} from "./primitives";

describe("StatusBadge", () => {
  it("humanizes the status token", () => {
    const { container } = render(<StatusBadge status="in_progress" />);
    expect(screen.getByText("in progress")).toBeInTheDocument();
    expect(container.querySelector(".status-badge.in_progress")).not.toBeNull();
  });
});

describe("StatusPill", () => {
  it("renders children with the tone class", () => {
    const { container } = render(<StatusPill tone="success">Healthy</StatusPill>);
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(container.querySelector(".status-pill.success")).not.toBeNull();
  });
});

describe("InfoRows / KpiGrid", () => {
  it("renders label/value pairs", () => {
    render(<InfoRows rows={[["TPS", 195], ["Model", "35B"]]} />);
    expect(screen.getByText("TPS")).toBeInTheDocument();
    expect(screen.getByText("195")).toBeInTheDocument();
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByText("35B")).toBeInTheDocument();
  });

  it("KpiGrid renders each metric", () => {
    render(<KpiGrid rows={[["Latency", "12ms"]]} />);
    expect(screen.getByText("Latency")).toBeInTheDocument();
    expect(screen.getByText("12ms")).toBeInTheDocument();
  });
});

describe("CapChip", () => {
  it("reflects on/off state in the class", () => {
    const { container } = render(<CapChip on label="TurboQuant" />);
    expect(screen.getByText("TurboQuant")).toBeInTheDocument();
    expect(container.querySelector(".cap-chip.on")).not.toBeNull();
    const { container: off } = render(<CapChip on={false} label="MTP" />);
    expect(off.querySelector(".cap-chip.off")).not.toBeNull();
  });
});

describe("DoctorStat", () => {
  it("renders the value, label, and tone", () => {
    const { container } = render(<DoctorStat tone="ok" value={7} label="Passing" />);
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Passing")).toBeInTheDocument();
    expect(container.querySelector(".doctor-stat.tone-ok")).not.toBeNull();
  });
});
