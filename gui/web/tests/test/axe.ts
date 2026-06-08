// SPDX-License-Identifier: Apache-2.0
// Lightweight axe-core bridge for jsdom unit tests. We call axe.run directly
// rather than depend on a matcher library pinned to a specific vitest major —
// this stays compatible across vitest upgrades and keeps the assertion explicit.
import axe, { type RunOptions, type AxeResults } from "axe-core";
import { expect } from "vitest";

// jsdom has no layout engine, so colour-contrast and any rule that needs real
// box geometry produce false positives. We scope to the structural/semantic
// rules that genuinely run headless: roles, names, ARIA validity, labels.
const JSDOM_SAFE_OPTIONS: RunOptions = {
  rules: {
    "color-contrast": { enabled: false },
    "scrollable-region-focusable": { enabled: false },
  },
  resultTypes: ["violations"],
};

/** Run axe over a container and fail with a readable report on any violation. */
export async function expectNoA11yViolations(
  container: Element,
  options: RunOptions = {},
): Promise<void> {
  const results: AxeResults = await axe.run(container, { ...JSDOM_SAFE_OPTIONS, ...options });
  const summary = results.violations.map((v) => {
    const where = v.nodes.map((n) => n.target.join(" ")).join(", ");
    return `[${v.impact ?? "n/a"}] ${v.id}: ${v.help}\n    at: ${where}\n    ${v.helpUrl}`;
  });
  expect(results.violations, summary.join("\n\n")).toHaveLength(0);
}
