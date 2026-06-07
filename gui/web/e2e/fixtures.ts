// SPDX-License-Identifier: Apache-2.0
// Hermetic API fixtures for CI. The real Control Center talks to the read-only
// daemon (:8765); in CI there is no daemon, so we intercept every /api/** call
// with a minimal valid-shaped response. The shapes mirror src/api.ts types just
// enough for the App boot path to reach the "ready" dashboard with empty data —
// which is exactly what we want to scan for accessibility against the real,
// CSS-composed DOM (something jsdom unit tests cannot do).
import type { Page, Route } from "@playwright/test";

const PLATFORM = {
  public_brand: "SNDR Control Center",
  package_name: "sndr",
  sndr_core_version: "0.0.0-ci",
  os_name: "linux",
  machine: "x86_64",
  python_version: "3.12.0",
  engine_installed: false,
};

const CAPABILITIES = {
  platform: PLATFORM,
  runtime_targets: [],
  features: [],
  warnings: [],
};

const CATALOG = {
  models_count: 0, hardware_count: 0, profiles_count: 0, presets_count: 0,
  preset_cards_count: 0, unannotated_presets_count: 0, preset_load_error_count: 0,
  status_counts: {}, workload_counts: {}, family_counts: {},
  default_presets: [], preset_load_errors: [],
};

const EMPTY_PATCH_SUMMARY = {
  tier_counts: {}, lifecycle_counts: {},
  production_default_counts: {}, implementation_status_counts: {},
};

// Path-suffix → JSON body. Matched against the request URL pathname; the first
// entry whose key the pathname includes wins, so order longest-first.
const FIXTURES: Array<[string, unknown]> = [
  ["/api/v1/overview", { capabilities: CAPABILITIES, catalog: CATALOG }],
  ["/api/v1/capabilities", CAPABILITIES],
  ["/api/v1/presets/recommend", { query: {}, results: [], total_matches: 0, total_candidates: 0 }],
  ["/api/v1/presets", { filters: {}, matched: 0, total: 0, presets: [], load_errors: [] }],
  ["/explain", { id: "", card: {}, composed: {}, fallback_diff: null }],
  ["/api/v1/patches/doctor", { registry_size: 0, issues: [], coverage: { total: 0, mapped: 0, unmapped: [], intentionally_unmapped: [] } }],
  ["/api/v1/patches/bundles", { bundles: [] }],
  ["/api/v1/patches/diff-upstream", { generated_at: 0, patches: [], summary: {} }],
  ["/api/v1/patches/overrides", { overrides: {} }],
  ["/api/v1/patches", { filters: {}, matched: 0, total: 0, patches: [], summary: EMPTY_PATCH_SUMMARY }],
  ["/api/v1/configs/v2/catalog", { models: [], hardware: [], profiles: [], presets: [] }],
  ["/api/v1/configs/v2/preview", { selection: {}, compatible: true, status: "ok", messages: [], composed: {}, draft_yaml: "" }],
  ["/api/v1/configs/v2/user-presets", { presets: [] }],
  ["/api/v1/launch/plan", { plan_id: "", preset_id: "", runtime_target: "docker", patch_policy: "", mode: "single", host: "", actionable: false, action_reason: "", summary: {}, gates: [], endpoints: [], artifacts: [], cli_mirror: [], events: [] }],
  ["/api/v1/proof/status", { generated_at: 0, sources: [], summary: {} }],
  ["/api/v1/doctor", { generated_at: 0, checks: [], summary: {} }],
  ["/api/v1/environment", { generated_at: 0, sections: [], summary: {} }],
  ["/api/v1/hosts", { hosts: [] }],
  ["/api/v1/events/recent", { events: [], latest_seq: 0 }],
  ["/api/v1/operations", { operations: [] }],
  ["/api/v1/caveats", { caveats: [] }],
  ["/api/v1/config-keys", { keys: [] }],
  ["/api/v1/traces", { traces: [] }],
  ["/api/v1/deploy/targets", { targets: [] }],
  ["/api/v1/jobs", { jobs: [] }],
  ["/api/v1/auth/status", { auth_required: false, apply_enabled: false, backends: [], oauth_providers: [], context: { in_container: false, system_user: "ci", pam_enabled: false }, user: null }],
  ["/api/v1/alerts", { active: [], recent: [], counts: { critical: 0, warn: 0, info: 0 } }],
];

/** Install a catch-all /api/** route on the page that serves the fixtures. */
export async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", (route: Route) => {
    const pathname = new URL(route.request().url()).pathname;
    const hit = FIXTURES.find(([suffix]) => pathname.includes(suffix));
    const body = hit ? hit[1] : {};
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}
