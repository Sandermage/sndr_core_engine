// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  getApiToken: () => "",
  normalizeBaseUrl: (v: string) => v.replace(/\/+$/, ""),
  hostLabel: (v: string) => v,
}));
import { ServerSwitcher, ConnectionMap } from "@/sections/connection-bar";

afterEach(cleanup);

describe("ServerSwitcher", () => {
  it("renders the active connection + opens the target menu", () => {
    render(
      <ServerSwitcher
        apiBase="http://127.0.0.1:8765"
        connectionTone="success"
        onSwitch={vi.fn()}
        hostProfiles={[]}
        onManageHosts={vi.fn()}
        onOpenHost={vi.fn()}
      />
    );
    // the switcher button is present
    const trigger = screen.getAllByRole("button")[0];
    expect(trigger).toBeTruthy();
    fireEvent.click(trigger);
    // "This host" is always a target
    expect(screen.getAllByText(/This host|Manage/i).length).toBeGreaterThan(0);
  });
});

describe("ConnectionMap", () => {
  it("renders the connection map nodes for the active runtime", () => {
    const { container } = render(
      <ConnectionMap runtimeMode="local" runtimeTarget="docker" selectedPreset="p27b" patchCount={12} apiBase="http://127.0.0.1:8765" />
    );
    expect(container.querySelector(".connection-map, [class*=connection]")).not.toBeNull();
  });
});
