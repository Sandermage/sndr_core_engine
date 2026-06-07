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

// Type-complete-but-empty shapes (mirror the api.ts types) so panels that read
// required nested fields render their empty state instead of crashing.
const HOST_INVENTORY = {
  os: { system: "Linux", release: "6.0", distro: "ubuntu", arch: "x86_64" },
  python: { binary_path: "/usr/bin/python3", version: "3.12.0", implementation: "CPython", venv_active: false, pip_present: true, pip_version: "24.0" },
  docker: { installed: false, binary_path: null, version: null, daemon_running: false, server_version: null, nvidia_runtime_present: false, notes: "" },
  nvidia: { installed: false, driver_version: null, cuda_version: null, n_gpus: 0, gpu_names: [], gpu_total_vram_mib: [], notes: "" },
  vllm: { installed: false, version: null, location: null },
};

const ENVIRONMENT = {
  brand: "SNDR", package_name: "sndr", sndr_core_version: "0.0.0-ci",
  engine_name: "vLLM", engine_version: null, engine_installed: false,
  python_version: "3.12.0", os_name: "linux", machine: "x86_64",
  dependencies: [], tools: [],
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
  ["/api/v1/host/inventory", HOST_INVENTORY],
  ["/api/v1/doctor", { findings: [], summary: {}, categories: [], generated_for: "ci", warnings: [] }],
  ["/api/v1/environment", ENVIRONMENT],
  ["/api/v1/hosts", { hosts: [] }],
  ["/api/v1/events/recent", { events: [], latest_seq: 0 }],
  ["/api/v1/models/cache", { host: "local", total: 0, present_count: 0, models: [] }],
  ["/api/v1/memory/fit", { model_id: "", hardware_id: "", model_title: "", hardware_title: "", compatible: true, checks: [], vram: { model_min_mib: 0, rig_floor_mib: 0, headroom_mib: 0, n_gpus: 0 } }],
  ["/api/v1/calc/models", { models: {}, kv_dtypes: {} }],
  ["/api/v1/calc/kv", {
    arch: { name: "", num_layers: 0, num_kv_heads: 0, head_dim: 0, params_b: 0, weight_bits: 16, is_moe: false, active_params_b: null },
    kv_dtype: "fp16", overhead_mib: 0,
    rig: { tp: 1, gpu_count: 1, gpu_vram_mib: 0, util: 0.9 },
    result: { model: "", weights_per_gpu_mib: 0, kv_per_gpu_mib: 0, kv_total_mib: 0, overhead_mib: 0, total_per_gpu_mib: 0, budget_per_gpu_mib: 0, headroom_mib: 0, fits: true, max_context: 0, kv_bytes_per_token: 0, tp: 1, concurrency: 1, context: 0 },
    by_dtype: {}, by_tp: {}, curve: [],
    envelope: { contexts: [], concurrencies: [], grid: [] },
    recommendation: [], arch_advice: null,
  }],
  ["/api/v1/baselines/trend", { points: [], metric: "", scenario: "" }],
  ["/api/v1/baselines", { baselines: [] }],
  ["/api/v1/copilot/tools", { tools: [] }],
  ["/api/v1/services/plan", { plan_id: "", preset_id: "", action: "status", runtime_target: "docker", host: "", container_name: "", mutating: false, actionable: false, action_reason: "", steps: [], side_effects: [], gates: [], cli_mirror: [], rollback: "" }],
  ["/api/v1/containers/stats", { stats: {} }],
  ["/api/v1/system/df", { images: [], containers: [], volumes: [], build_cache: [], layers_size: 0 }],
  ["/api/v1/containers", { containers: [], source: "local" }],
  ["/api/v1/operations", { operations: [], apply_enabled: false }],
  ["/api/v1/caveats", { caveats: [], total: 0, triggered_count: 0, host_facts_available: false, facts_error: null }],
  ["/api/v1/config-keys", { keys: {}, total: 0, by_source: {} }],
  ["/api/v1/traces", { traces: [], categories: [], by_category: {}, total: 0 }],
  ["/api/v1/deploy/targets", { targets: [], host: HOST_INVENTORY }],
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
