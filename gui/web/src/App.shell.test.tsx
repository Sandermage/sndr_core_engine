// SPDX-License-Identifier: Apache-2.0
// Shell test: render the whole <App />, mock the daemon, and exercise the boot
// orchestration + SectionWorkspace tab routing in jsdom (under coverage). The
// hermetic Playwright spec proves the same against a real browser; this one
// drives the App-level state machine and section switching where v8 can measure
// it. Only the network `api` object is replaced — getApiBase/normalizeBaseUrl/
// hostLabel stay real so the shell wiring is genuinely exercised.
import { describe, it, expect, beforeAll, afterEach, vi, type Mock } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  const { makeApiMock } = await import("./test/api-fixtures");
  return { ...actual, api: makeApiMock(actual.api as unknown as Record<string, unknown>) };
});

// The mocked network object — same vi.fn instances the App calls (Proxy-cached).
import { api } from "./api";
const apiMock = api as unknown as Record<string, Mock>;

beforeAll(() => {
  // jsdom is missing a few browser APIs the shell touches on mount.
  if (typeof window.localStorage?.setItem !== "function") {
    const store = new Map<string, string>();
    const mem = {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      get length() { return store.size; },
    };
    Object.defineProperty(window, "localStorage", { value: mem, configurable: true });
  }
  if (!("EventSource" in globalThis)) {
    class FakeEventSource {
      onmessage: ((e: MessageEvent) => void) | null = null;
      onerror: ((e: Event) => void) | null = null;
      addEventListener() {}
      removeEventListener() {}
      close() {}
    }
    (globalThis as Record<string, unknown>).EventSource = FakeEventSource;
  }
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = vi.fn();
  // Canvas + observers: chart/terminal panels touch these on mount; jsdom has
  // no 2d/webgl context. Returning null lets such panels degrade (or fall to
  // their SectionErrorBoundary) instead of aborting the whole render.
  if (!HTMLCanvasElement.prototype.getContext) {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  }
  for (const name of ["ResizeObserver", "IntersectionObserver"]) {
    if (!(name in globalThis)) {
      (globalThis as Record<string, unknown>)[name] = class {
        observe() {} unobserve() {} disconnect() {} takeRecords() { return []; }
      };
    }
  }
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false, media: "", addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: () => false,
    }) as unknown as typeof window.matchMedia;
  }
});

afterEach(cleanup);

import App from "./App";

describe("App shell", () => {
  it("boots to the ready dashboard and renders the section nav", async () => {
    render(<App />);
    // The sidebar nav is static; the dashboard becomes ready once the mocked
    // boot fetches resolve. Wait for the API daemon card to leave "Connecting".
    expect(await screen.findByRole("navigation", { name: "SNDR sections" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Overview" })).toBeTruthy();
    await waitFor(() => expect(apiMock.overview).toHaveBeenCalled());
    await waitFor(() => expect(apiMock.launchPlan).toHaveBeenCalled());
  });

  it("routes to another section when its nav button is clicked", async () => {
    render(<App />);
    const patchesBtn = await screen.findByRole("button", { name: "Patches" });
    fireEvent.click(patchesBtn);
    // SectionWorkspace swaps content; the patches fetch fires on that route.
    await waitFor(() => expect(apiMock.patches).toHaveBeenCalled());
    expect(patchesBtn.className).toContain("active");
  });

  it("navigates every sidebar section without unmounting the shell", async () => {
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "SNDR sections" });
    const labels = within(nav).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? "");
    expect(labels.length).toBeGreaterThan(15);

    for (const label of labels) {
      // Re-query each iteration: a section render may swap subtrees.
      const liveNav = screen.getByRole("navigation", { name: "SNDR sections" });
      const button = within(liveNav).getByRole("button", { name: label });
      fireEvent.click(button);
      // Each route activates and runs its section code path. The shell must
      // stay mounted — a panel may fall back to its SectionErrorBoundary under
      // jsdom's missing canvas/webgl, but the nav landmark must never disappear.
      await waitFor(() => expect(button.className).toContain("active"));
      expect(screen.getByRole("navigation", { name: "SNDR sections" })).toBeTruthy();
    }
  });
});
