import { defineConfig, devices } from "@playwright/test";

// Hermetic E2E config for CI — no live daemon. Runs ONLY e2e/hermetic.spec.ts
// against `vite preview` of the production build (started automatically below).
// The dev-box specs (smoke/host_wiring/server_switch/chat_rag) keep using the
// default playwright.config.ts, which assumes a running daemon + dev server.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /hermetic\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run preview -- --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
