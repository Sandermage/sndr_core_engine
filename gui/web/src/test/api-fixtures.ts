// SPDX-License-Identifier: Apache-2.0
// jsdom shell-test API mock. Fixture shapes live in ./fixtures-data (shared with
// the Playwright E2E); this module only adapts them to a vitest mock object.
import { vi } from "vitest";
import { RESPONSES } from "./fixtures-data";

/** Boot/section responses keyed by api method name (shared source of truth). */
export const API_FIXTURES = RESPONSES;

/**
 * Build a mock `api` from the real one: the data-fetching methods named in
 * API_FIXTURES resolve to their fixture; every other member (synchronous URL
 * builders like oauthLoginUrl, helpers, and network methods only hit on user
 * action) keeps its real implementation. This preserves the sync-vs-async
 * contract — overriding everything with a Promise breaks `{api.oauthLoginUrl()}`
 * style direct renders.
 */
export function makeApiMock<T extends object>(realApi: T, overrides: Record<string, unknown> = {}): T {
  const cache = new Map<string, ReturnType<typeof vi.fn>>();
  // A Proxy delegates lazily: it never spreads realApi, so its getters (e.g.
  // the `baseUrl` accessor that reads localStorage) fire only on real access —
  // after the test's browser stubs are in place.
  return new Proxy(realApi, {
    get(target, prop, receiver) {
      if (typeof prop === "string") {
        if (prop in overrides) return overrides[prop];
        if (prop in API_FIXTURES) {
          if (!cache.has(prop)) cache.set(prop, vi.fn().mockResolvedValue(API_FIXTURES[prop]));
          return cache.get(prop);
        }
      }
      return Reflect.get(target, prop, receiver);
    },
  });
}
