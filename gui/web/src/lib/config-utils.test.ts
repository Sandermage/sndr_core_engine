// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import { getIn, objToYaml, setIn, yamlScalar } from "./config-utils";

describe("getIn", () => {
  it("reads a dotted path", () => {
    expect(getIn({ a: { b: 1 } }, "a.b")).toBe(1);
  });
  it("returns undefined for a missing segment", () => {
    expect(getIn({ a: { b: 1 } }, "a.c")).toBeUndefined();
    expect(getIn({ a: null }, "a.b")).toBeUndefined();
    expect(getIn(null, "a")).toBeUndefined();
  });
});

describe("setIn", () => {
  it("immutably writes a nested value without mutating the source", () => {
    const src = { a: { b: 1 }, keep: "me" };
    const out = setIn(src, "a.b", 2);
    expect(out).toEqual({ a: { b: 2 }, keep: "me" });
    expect(src.a.b).toBe(1); // source untouched
    expect(out).not.toBe(src);
    expect(out.a).not.toBe(src.a);
  });
  it("creates intermediate objects for a deep path", () => {
    expect(setIn({}, "a.b.c", 5)).toEqual({ a: { b: { c: 5 } } });
  });
});

describe("yamlScalar", () => {
  it("renders primitives", () => {
    expect(yamlScalar(null)).toBe("null");
    expect(yamlScalar(undefined)).toBe("null");
    expect(yamlScalar(true)).toBe("true");
    expect(yamlScalar(false)).toBe("false");
    expect(yamlScalar(42)).toBe("42");
    expect(yamlScalar("plain")).toBe("plain");
  });
  it("quotes strings that need it", () => {
    expect(yamlScalar("a: b")).toBe('"a: b"');
    expect(yamlScalar(" leading")).toBe('" leading"');
  });
});

describe("objToYaml", () => {
  it("renders scalars", () => {
    expect(objToYaml({ a: 1, b: "x" })).toEqual(["a: 1", "b: x"]);
  });
  it("nests objects with 2-space indent", () => {
    expect(objToYaml({ a: { b: 2 } })).toEqual(["a:", "  b: 2"]);
  });
  it("renders list items", () => {
    expect(objToYaml({ list: [1, 2] })).toEqual(["list:", "  - 1", "  - 2"]);
  });
  it("renders empty collections inline", () => {
    expect(objToYaml({ e: [] })).toEqual(["e: []"]);
    expect(objToYaml({ o: {} })).toEqual(["o: {}"]);
  });
});
