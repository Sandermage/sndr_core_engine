import { describe, it, expect, beforeEach } from "vitest";
import { sectionFromHash, recordIdFromHash, hashParam, buildHash } from "./route";

// jsdom gives us a real window.location whose hash we can drive.
function setHash(hash: string) {
  window.location.hash = hash;
}

describe("route: sectionFromHash", () => {
  beforeEach(() => setHash(""));

  it("returns null when there is no hash", () => {
    expect(sectionFromHash()).toBeNull();
  });

  it("parses a bare section", () => {
    setHash("#presets");
    expect(sectionFromHash()).toBe("presets");
  });

  it("tolerates a leading #/ and a ?query suffix", () => {
    setHash("#/containers?c=foo&src=local");
    expect(sectionFromHash()).toBe("containers");
  });

  it("rejects an unknown section (deep-link safety)", () => {
    setHash("#definitely-not-a-section");
    expect(sectionFromHash()).toBeNull();
  });
});

describe("route: recordIdFromHash / hashParam", () => {
  beforeEach(() => setHash(""));

  it("reads the preset id param", () => {
    setHash("#presets?id=prod-35b-multiconc");
    expect(recordIdFromHash()).toBe("prod-35b-multiconc");
  });

  it("decodes percent-encoded values", () => {
    setHash("#containers?c=" + encodeURIComponent("vllm/pn95 test"));
    expect(hashParam("c")).toBe("vllm/pn95 test");
  });

  it("returns null for an absent param", () => {
    setHash("#presets");
    expect(recordIdFromHash()).toBeNull();
    expect(hashParam("src")).toBeNull();
  });

  it("isolates section param namespaces (id vs c)", () => {
    setHash("#containers?c=foo");
    expect(recordIdFromHash()).toBeNull(); // containers use `c`, not `id`
    expect(hashParam("c")).toBe("foo");
  });
});

describe("route: buildHash", () => {
  it("builds a bare section with no params", () => {
    expect(buildHash("models")).toBe("models");
  });

  it("appends params and drops empty/nullish ones", () => {
    expect(buildHash("presets", { id: "p1" })).toBe("presets?id=p1");
    expect(buildHash("containers", { c: "x", src: null })).toBe("containers?c=x");
    expect(buildHash("containers", { c: "", src: "" })).toBe("containers");
  });

  it("encodes param values", () => {
    expect(buildHash("containers", { c: "a b/c" })).toBe("containers?c=a%20b%2Fc");
  });

  it("round-trips with the readers", () => {
    setHash("#" + buildHash("containers", { c: "vllm-pn95", src: "host-a5000" }));
    expect(sectionFromHash()).toBe("containers");
    expect(hashParam("c")).toBe("vllm-pn95");
    expect(hashParam("src")).toBe("host-a5000");
  });
});
