// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect } from "vitest";
import { nextTheme, themeLabel, THEME_CYCLE, VALID_THEMES } from "./settings";

describe("theme cycle", () => {
  it("advances through the cycle and wraps around", () => {
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("carbon");
    expect(nextTheme("carbon")).toBe("lime");
    expect(nextTheme("lime")).toBe("light");
  });

  it("labels every theme in the cycle", () => {
    for (const theme of THEME_CYCLE) {
      expect(themeLabel(theme).length).toBeGreaterThan(0);
    }
  });

  it("VALID_THEMES contains exactly the cycle members", () => {
    expect(VALID_THEMES.size).toBe(THEME_CYCLE.length);
    for (const theme of THEME_CYCLE) expect(VALID_THEMES.has(theme)).toBe(true);
  });
});
