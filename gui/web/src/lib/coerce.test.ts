// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import { asNumber, asRecord, asStringArray, asText, countRecord } from "./coerce";

describe("asRecord", () => {
  it("passes plain objects through", () => {
    const obj = { a: 1 };
    expect(asRecord(obj)).toBe(obj);
  });
  it("rejects arrays, null, primitives -> {}", () => {
    expect(asRecord([1, 2])).toEqual({});
    expect(asRecord(null)).toEqual({});
    expect(asRecord(undefined)).toEqual({});
    expect(asRecord(42)).toEqual({});
    expect(asRecord("str")).toEqual({});
  });
});

describe("asText", () => {
  it("returns a non-empty trimmed string", () => {
    expect(asText("hello", "fb")).toBe("hello");
  });
  it("falls back on empty / whitespace-only / non-string", () => {
    expect(asText("", "fb")).toBe("fb");
    expect(asText("   ", "fb")).toBe("fb");
    expect(asText(123, "fb")).toBe("fb");
    expect(asText(null, "fb")).toBe("fb");
  });
});

describe("asNumber", () => {
  it("returns finite numbers, else 0", () => {
    expect(asNumber(3.14)).toBe(3.14);
    expect(asNumber(0)).toBe(0);
    expect(asNumber(NaN)).toBe(0);
    expect(asNumber(Infinity)).toBe(0);
    expect(asNumber("5")).toBe(0);
    expect(asNumber(null)).toBe(0);
  });
});

describe("asStringArray", () => {
  it("stringifies each element of an array", () => {
    expect(asStringArray([1, "a", true])).toEqual(["1", "a", "true"]);
  });
  it("returns [] for non-arrays", () => {
    expect(asStringArray("nope")).toEqual([]);
    expect(asStringArray(null)).toEqual([]);
    expect(asStringArray({ 0: "a" })).toEqual([]);
  });
});

describe("countRecord", () => {
  it("builds a frequency map", () => {
    expect(countRecord(["a", "b", "a", "a", "b"])).toEqual({ a: 3, b: 2 });
  });
  it("returns {} for an empty list", () => {
    expect(countRecord([])).toEqual({});
  });
});
