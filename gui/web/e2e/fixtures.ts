// SPDX-License-Identifier: Apache-2.0
// Hermetic API fixtures for CI. The real Control Center talks to the read-only
// daemon (:8765); in CI there is no daemon, so we intercept every /api/** call
// and serve a minimal valid-shaped response. Fixture shapes live in the shared
// ../tests/test/fixtures-data module (also used by the jsdom shell test) so the
// two never drift; here we only map request URLs to those shapes.
import type { Page, Route } from "@playwright/test";
import { RESPONSES, URL_TABLE } from "../tests/test/fixtures-data";

/** Install a catch-all /api/** route on the page that serves the fixtures. */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", (route: Route) => {
    const pathname = new URL(route.request().url()).pathname;
    const hit = URL_TABLE.find(([suffix]) => pathname.includes(suffix));
    const body = hit ? RESPONSES[hit[1]] : {};
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body ?? {}),
    });
  });
}
