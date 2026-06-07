// SPDX-License-Identifier: Apache-2.0
// Hermetic E2E + accessibility gate for CI. Unlike smoke/host_wiring/server_switch
// (which need the live daemon and run on the dev box), this spec mocks every
// /api/** call (see fixtures.ts) and runs against `vite preview` of the
// production bundle. It proves two things no unit test can:
//   1. the built bundle boots without a runtime/JS crash, and
//   2. the real, CSS-composed DOM is free of structural accessibility
//      violations across every navigable section.
//
// Scan policy: fail on critical/serious axe violations for structural rules
// (roles, names, landmarks, ARIA validity). color-contrast is excluded — theme
// colour tuning is tracked separately and would make the gate brittle across
// headless-render differences.
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockApi } from "./fixtures";

async function scan(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .disableRules(["color-contrast"])
    .analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  const report = serious
    .map((v) => `[${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node(s))`)
    .join("\n");
  expect(serious, report).toHaveLength(0);
}

test("production bundle boots and the shell renders without API", async ({ page }) => {
  await mockApi(page);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

  await page.goto("/");
  // Stable, always-sized landmarks: the sidebar chrome and its nav buttons
  // render regardless of data-load state (the main-shell can be momentarily
  // zero-height while async content fills in, so we don't gate on it here).
  await expect(page.locator(".sidebar")).toBeVisible();
  await expect(page.locator('.side-nav button:has-text("Overview")')).toBeVisible();

  expect(errors, errors.join("\n")).toHaveLength(0);
});

test("Overview is accessible (axe, real DOM)", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.locator('.side-nav button:has-text("Overview")')).toBeVisible();
  await scan(page);
});

test("every nav entry routes to real content and stays accessible", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.locator(".side-nav")).toBeVisible();

  // Drive the ACTUAL nav (no hardcoded list to drift): every button the sidebar
  // renders must route to a non-empty workspace — a button that goes nowhere
  // (unrouted section) would leave the content area blank. Also scans a11y.
  const labels = await page.locator(".side-nav button").allInnerTexts();
  expect(labels.length).toBeGreaterThan(10);

  for (const label of labels) {
    const button = page.locator(".side-nav button", { hasText: label.trim() }).first();
    await button.click();
    // Routing invariant: the clicked entry becomes active and routes to a real
    // panel — a workspace that shows either its section heading or (when a panel
    // chokes on the empty hermetic data) a graceful error boundary. A nav button
    // wired to an unrouted section would render neither — a blank workspace.
    await expect(button).toHaveClass(/active/);
    const workspace = page.locator(".main-shell .section-workspace").first();
    await expect(workspace).toBeVisible();
    await expect(workspace.locator(".section-heading, .error-boundary").first()).toBeVisible();
    await scan(page);
  }
});

test("no horizontal overflow at tablet width", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/");
  await page.waitForTimeout(400);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(overflow).toBe(false);
});
