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

const SECTIONS = [
  "Overview", "Setup", "Fleet", "Hosts", "Models", "Configs", "Presets",
  "Planner", "Copilot", "Launch Plan", "Services", "Doctor", "Patches",
  "Benchmarks", "Evidence", "Clients", "Chat", "Reports", "Operations", "Advanced",
];

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

test("every section navigates and stays accessible", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.locator(".side-nav")).toBeVisible();

  for (const section of SECTIONS) {
    const button = page.locator(`.side-nav button:has-text("${section}")`).first();
    if ((await button.count()) === 0) continue;
    await button.click();
    await expect(page.locator(".main-shell")).toBeVisible();
    await page.waitForTimeout(150);
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
