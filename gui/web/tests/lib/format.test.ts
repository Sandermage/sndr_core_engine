// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect } from "vitest";
import { formatAppliesTo, fmtParam, shortWorkload, formatTokens, formatVram, totalVramGiB } from "@/lib/format";

describe("formatAppliesTo", () => {
  it("humanizes keys and joins array values", () => {
    expect(formatAppliesTo({ model_class: ["a", "b"] })).toEqual([["model class", "a, b"]]);
  });
  it("special-cases is_turboquant + vllm_version_range", () => {
    expect(formatAppliesTo({ is_turboquant: true })).toEqual([["TurboQuant models", "required"]]);
    expect(formatAppliesTo({ vllm_version_range: [">=0.21", "<0.23"] })).toEqual([["vLLM version", ">=0.21  <0.23"]]);
  });
  it("non-object → []", () => {
    expect(formatAppliesTo(null)).toEqual([]);
  });
});

describe("fmtParam", () => {
  it("em-dash for empty-ish", () => {
    expect(fmtParam(null)).toBe("—");
    expect(fmtParam(undefined)).toBe("—");
    expect(fmtParam("")).toBe("—");
  });
  it("locale-formats numbers, stringifies else", () => {
    expect(fmtParam(1234567)).toBe("1,234,567");
    expect(fmtParam("ok")).toBe("ok");
  });
});

describe("shortWorkload", () => {
  it("maps known workloads", () => {
    expect(shortWorkload("free_chat")).toBe("chat");
    expect(shortWorkload("tool_call.long")).toBe("tool+");
  });
  it("derives a short label for unknowns", () => {
    expect(shortWorkload("some_custom_thing")).toBe("thing");
  });
});

describe("formatTokens", () => {
  it("compacts thousands, dash for 0", () => {
    expect(formatTokens(0)).toBe("-");
    expect(formatTokens(500)).toBe("500");
    expect(formatTokens(1500)).toBe("2K");
  });
});

describe("formatVram", () => {
  it("renders GB + MiB", () => {
    expect(formatVram(24564)).toBe("24.0 GB · 24,564 MiB");
  });
  it("dash for non-positive/invalid", () => {
    expect(formatVram(0)).toBe("-");
    expect(formatVram("x")).toBe("-");
    expect(formatVram(-5)).toBe("-");
  });
});

describe("totalVramGiB", () => {
  it("sums per-GPU MiB into whole GiB", () => {
    expect(totalVramGiB([24564, 24564])).toBe(48);
  });
  it("returns 0 for an empty list", () => {
    expect(totalVramGiB([])).toBe(0);
  });
});
