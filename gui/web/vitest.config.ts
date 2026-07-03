// SPDX-License-Identifier: Apache-2.0
// Vitest config for the SNDR Control Center web app. Kept separate from
// vite.config.ts so the production build config stays untouched; vitest loads
// this file in preference. jsdom gives the pure-lib helpers a `window`
// (safe-storage) and lets the presentational components render for smoke tests.
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    clearMocks: true,
    restoreMocks: true,
  },
});
