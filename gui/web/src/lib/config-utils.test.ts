// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect } from "vitest";
import { getIn, setIn, yamlScalar, objToYaml } from "./config-utils";

describe("getIn", () => {
  it("reads a nested dotted path", () => {
    expect(getIn({ a: { b: { c: 7 } } }, "a.b.c")).toBe(7);
  });
  it("returns undefined when a segment is missing", () => {
    expect(getIn({ a: {} }, "a.b.c")).toBeUndefined();
    expect(getIn(null, "a.b")).toBeUndefined();
  });
});

describe("setIn", () => {
  it("immutably writes a nested path, cloning touched nodes", () => {
    const src = { a: { b: { c: 1 }, keep: 2 } };
    const out = setIn(src, "a.b.c", 9);
    expect(out.a.b.c).toBe(9);
    expect(src.a.b.c).toBe(1); // original untouched
    expect(out.a.keep).toBe(2);
    expect(out.a).not.toBe(src.a); // touched node cloned
  });
  it("creates missing intermediate objects", () => {
    expect(setIn({}, "x.y.z", 5)).toEqual({ x: { y: { z: 5 } } });
  });
});

describe("yamlScalar", () => {
  it("renders primitives", () => {
    expect(yamlScalar(null)).toBe("null");
    expect(yamlScalar(true)).toBe("true");
    expect(yamlScalar(42)).toBe("42");
    expect(yamlScalar("plain")).toBe("plain");
  });
  it("quotes values with special characters or surrounding space", () => {
    expect(yamlScalar("a: b")).toBe('"a: b"');
    expect(yamlScalar(" pad ")).toBe('" pad "');
  });
});

describe("objToYaml", () => {
  it("serializes nested objects with 2-space indent", () => {
    expect(objToYaml({ a: 1, b: { c: "x" } })).toEqual(["a: 1", "b:", "  c: x"]);
  });
  it("renders empty collections inline and arrays of scalars", () => {
    expect(objToYaml({ list: [], obj: {}, xs: [1, 2] })).toEqual(["list: []", "obj: {}", "xs:", "  - 1", "  - 2"]);
  });
  it("renders arrays of objects with a dash marker", () => {
    expect(objToYaml({ items: [{ k: 1 }] })).toEqual(["items:", "  -", "    k: 1"]);
  });
});
