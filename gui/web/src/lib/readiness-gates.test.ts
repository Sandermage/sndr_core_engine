// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import type { ProductCapability } from "../api";
import { buildReadinessGates, countGates, targetStatus } from "./readiness-gates";

describe("targetStatus", () => {
  const cap = (status: string) => ({ status }) as unknown as ProductCapability;
  it("maps capability status to a gate status", () => {
    expect(targetStatus(undefined)).toBe("blocked");
    expect(targetStatus(cap("available"))).toBe("pass");
    expect(targetStatus(cap("render_only"))).toBe("warning");
    expect(targetStatus(cap("partial"))).toBe("warning");
    expect(targetStatus(cap("deferred"))).toBe("planned");
    expect(targetStatus(cap("something_else"))).toBe("blocked");
  });
});

describe("countGates", () => {
  it("tallies gate statuses", () => {
    const counts = countGates([
      { id: "a", label: "", detail: "", status: "pass", action: "" },
      { id: "b", label: "", detail: "", status: "pass", action: "" },
      { id: "c", label: "", detail: "", status: "warning", action: "" },
      { id: "d", label: "", detail: "", status: "blocked", action: "" },
    ]);
    expect(counts).toEqual({ pass: 2, warning: 1, blocked: 1, planned: 0 });
  });
});

describe("buildReadinessGates", () => {
  it("projects a null overview into the 7 canonical gates (catalog passes, rest warn/block)", () => {
    const gates = buildReadinessGates({
      overview: null,
      runtimeTarget: "a5000-2x",
      selectedPresetRecord: null,
      explain: null,
    });
    // Stable set + order the readiness panel renders.
    expect(gates.map((g) => g.id)).toEqual([
      "catalog",
      "preset-card",
      "runtime",
      "engine",
      "service-api",
      "evidence",
      "release-proof",
    ]);
    // No overview => no catalog load errors => catalog passes; runtime target
    // is unresolved => blocked; everything else is a soft warning.
    const counts = countGates(gates);
    expect(counts.pass).toBe(1);
    expect(counts.blocked).toBe(1);
    expect(counts.warning).toBe(5);
    expect(counts.planned).toBe(0);
  });
});
