// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", () => ({
  api: { apiTokens: vi.fn(), apiTokenCreate: vi.fn(), apiTokenRevoke: vi.fn(), alertsConfig: vi.fn(), alertsSetConfig: vi.fn(), alertsTest: vi.fn() },
  getApiToken: () => "",
  setApiToken: vi.fn(),
}));
vi.mock("../components/toast", () => ({ toast: vi.fn() }));
vi.mock("../components/dialogs", () => ({ ConfirmDialog: ({ title }: { title: string }) => <div role="dialog">{title}</div> }));
import { api } from "../api";
import { ApiTokenManager, AppearanceSettings, ApiTokenField } from "./settings-panels";

afterEach(cleanup);

describe("ApiTokenManager", () => {
  it("renders the unauthenticated hint when not enabled", () => {
    render(<ApiTokenManager enabled={false} />);
    expect(screen.getByText(/requires authentication/)).toBeTruthy();
  });

  it("lists tokens + creates one when enabled", async () => {
    (api.apiTokens as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ tokens: [{ id: "t1", label: "ci", prefix: "abcd", created_at: 1_700_000_000, last_used: null }] });
    (api.apiTokenCreate as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ token: "secret-xyz" });
    render(<ApiTokenManager enabled />);
    await waitFor(() => expect(screen.getByText("ci")).toBeTruthy());
    fireEvent.click(screen.getByText("Create token"));
    await waitFor(() => expect(api.apiTokenCreate).toHaveBeenCalled());
  });
});

describe("AppearanceSettings", () => {
  it("renders theme/density/accent groups + emits a change", () => {
    const onSettings = vi.fn();
    render(<AppearanceSettings settings={{ theme: "light", density: "comfortable", accent: "teal", detailMode: "engineer", showConnectionMap: true, autoRefresh: false } as never} onSettings={onSettings} />);
    expect(screen.getByText("Theme")).toBeTruthy();
    fireEvent.click(screen.getByText("Dark"));
    expect(onSettings).toHaveBeenCalledWith({ theme: "dark" });
  });
});

describe("ApiTokenField", () => {
  it("renders the access-token field", () => {
    render(<ApiTokenField />);
    expect(screen.getByText("Save token")).toBeTruthy();
  });
});
