// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { lsGet, lsRemove, lsSet } from "./safe-storage";

// jsdom's own localStorage is flaky under vitest (it no-ops on some origins),
// so we install a deterministic Map-backed fake as window.localStorage. This
// also makes the degradation spies portable: they target the fake's OWN
// methods rather than Storage.prototype.
function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => (map.has(key) ? (map.get(key) ?? null) : null),
    setItem: (key: string, value: string) => {
      map.set(key, String(value));
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
    clear: () => map.clear(),
    key: () => null,
    get length() {
      return map.size;
    },
  } as Storage;
}

let original: PropertyDescriptor | undefined;

beforeEach(() => {
  original = Object.getOwnPropertyDescriptor(window, "localStorage");
  Object.defineProperty(window, "localStorage", {
    value: memoryStorage(),
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  if (original) Object.defineProperty(window, "localStorage", original);
});

describe("safe-storage round trip", () => {
  it("sets, reads, and removes a key", () => {
    lsSet("k1", "v1");
    expect(lsGet("k1")).toBe("v1");
    lsRemove("k1");
    expect(lsGet("k1")).toBeNull();
  });
});

describe("safe-storage degradation (storage throws)", () => {
  it("lsGet returns null instead of throwing", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage blocked (private mode)");
    });
    expect(() => lsGet("anything")).not.toThrow();
    expect(lsGet("anything")).toBeNull();
  });
  it("lsSet swallows the error", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("over quota");
    });
    expect(() => lsSet("k", "v")).not.toThrow();
  });
  it("lsRemove swallows the error", () => {
    vi.spyOn(window.localStorage, "removeItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    expect(() => lsRemove("k")).not.toThrow();
  });
});
