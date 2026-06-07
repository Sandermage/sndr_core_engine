// SPDX-License-Identifier: Apache-2.0
// Regression guard for the boot white-screen: AlertsBell sits in the always-
// rendered topbar, so an unguarded `snap.counts.critical` on a malformed daemon
// payload used to throw and unmount the entire app. It must now degrade to zero.
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

const { alerts } = vi.hoisted(() => ({ alerts: vi.fn() }));
vi.mock("./api", () => ({ api: { alerts } }));

import { AlertsBell } from "./Alerts";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("AlertsBell robustness", () => {
  it("renders the empty state when the payload omits counts", async () => {
    // A partial/empty snapshot ({} from a degraded daemon) must not throw.
    alerts.mockResolvedValue({});
    render(<AlertsBell />);
    await waitFor(() => expect(screen.getByTitle("No active alerts")).toBeTruthy());
  });

  it("renders a badge for a well-formed snapshot", async () => {
    alerts.mockResolvedValue({ active: [], recent: [], counts: { critical: 2, warn: 1, info: 0 } });
    render(<AlertsBell />);
    await waitFor(() => expect(screen.getByTitle("3 active alerts")).toBeTruthy());
  });
});
