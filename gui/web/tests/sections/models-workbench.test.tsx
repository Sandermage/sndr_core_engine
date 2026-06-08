// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { itemBadges } from "@/sections/models-workbench";

afterEach(cleanup);

describe("itemBadges", () => {
  it("derives model badges from quantization / KV / patch count", () => {
    const badges = itemBadges({ kind: "model", fields: { quantization: "int4", kv_cache_dtype: "fp8", patch_count: 12 } } as never);
    const labels = badges.map((b) => b.label);
    expect(labels).toContain("int4");
    expect(labels).toContain("KV fp8");
    expect(labels.some((l) => l.includes("patches"))).toBe(true);
  });

  it("derives hardware badges (GPU count + context)", () => {
    const labels = itemBadges({ kind: "hardware", fields: { n_gpus: 2, max_model_len: 8192 } } as never).map((b) => b.label);
    expect(labels).toContain("2× GPU");
    expect(labels.some((l) => l.endsWith("k ctx"))).toBe(true);
  });

  it("skips auto KV cache and caps at three badges", () => {
    const badges = itemBadges({ kind: "model", fields: { quantization: "int4", kv_cache_dtype: "auto", patch_count: 12, dtype: "bf16" } } as never);
    expect(badges.length).toBeLessThanOrEqual(3);
    expect(badges.map((b) => b.label)).not.toContain("KV auto");
  });

  it("returns an empty list for an unknown kind", () => {
    expect(itemBadges({ kind: "other", fields: {} } as never)).toEqual([]);
  });
});
