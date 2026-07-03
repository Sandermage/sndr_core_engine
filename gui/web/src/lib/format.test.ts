// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import {
  fmtParam,
  formatAppliesTo,
  formatTokens,
  formatVram,
  shortWorkload,
  targetTitle,
  totalVramGiB,
} from "./format";

describe("formatTokens", () => {
  it("compacts thousands and dashes zero", () => {
    expect(formatTokens(0)).toBe("-");
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1000)).toBe("1K");
    expect(formatTokens(1500)).toBe("2K"); // rounds
    expect(formatTokens(1499)).toBe("1K");
  });
});

describe("formatVram", () => {
  it("renders GB + MiB for positive MiB", () => {
    const out = formatVram(2048);
    expect(out).toContain("2.0 GB");
    expect(out).toContain("MiB");
  });
  it("coerces numeric strings", () => {
    expect(formatVram("4096")).toContain("4.0 GB");
  });
  it("dashes non-positive / invalid", () => {
    expect(formatVram(0)).toBe("-");
    expect(formatVram(-5)).toBe("-");
    expect(formatVram("abc")).toBe("-");
    expect(formatVram(null)).toBe("-");
  });
});

describe("fmtParam", () => {
  it("em-dashes empty-ish values", () => {
    expect(fmtParam(null)).toBe("—");
    expect(fmtParam(undefined)).toBe("—");
    expect(fmtParam("")).toBe("—");
  });
  it("locale-formats numbers and stringifies the rest", () => {
    expect(fmtParam(1234)).toBe("1,234");
    expect(fmtParam("raw")).toBe("raw");
    expect(fmtParam(true)).toBe("true");
  });
});

describe("shortWorkload", () => {
  it("maps known workloads to compact chips", () => {
    expect(shortWorkload("free_chat")).toBe("chat");
    expect(shortWorkload("tool_call.long")).toBe("tool+");
    expect(shortWorkload("structured_json.short")).toBe("json");
  });
  it("derives a short label for unknown workloads", () => {
    expect(shortWorkload("some_thing")).toBe("thing");
    expect(shortWorkload("plain")).toBe("plain");
  });
});

describe("totalVramGiB", () => {
  it("sums a per-GPU MiB array into whole GiB", () => {
    expect(totalVramGiB([24576, 24576])).toBe(48);
    expect(totalVramGiB([1024])).toBe(1);
  });
  it("returns 0 for an empty list", () => {
    expect(totalVramGiB([])).toBe(0);
  });
});

describe("targetTitle", () => {
  const targets = [
    { id: "a5000-2x", title: "A5000 ×2" },
    { id: "single", title: "Single GPU" },
  ];
  it("resolves an id to its title", () => {
    expect(targetTitle(targets, "single")).toBe("Single GPU");
  });
  it("falls back to the id when unknown", () => {
    expect(targetTitle(targets, "missing")).toBe("missing");
  });
});

describe("formatAppliesTo", () => {
  it("labels the special keys and humanizes the rest", () => {
    const rows = formatAppliesTo({
      is_turboquant: true,
      vllm_version_range: [">=0.23.0", "<0.24.0"],
      model_family: "qwen3",
    });
    expect(rows).toContainEqual(["TurboQuant models", "required"]);
    expect(rows).toContainEqual(["vLLM version", ">=0.23.0  <0.24.0"]);
    expect(rows).toContainEqual(["model family", "qwen3"]);
  });
  it("returns [] for non-object input", () => {
    expect(formatAppliesTo(null)).toEqual([]);
  });
});
