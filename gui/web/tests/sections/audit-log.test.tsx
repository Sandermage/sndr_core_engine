// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { eventsRecent: vi.fn() },
}));
import { api } from "@/api";
import { AuditLogPanel } from "@/sections/audit-log";

afterEach(cleanup);

const events = [
  { seq: 1, ts: 1_700_000_000, kind: "auth", message: "token issued" },
  { seq: 2, ts: 1_700_000_100, kind: "job", message: "bench queued" },
];

describe("AuditLogPanel", () => {
  it("renders the most-recent-first event feed after load", async () => {
    (api.eventsRecent as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ events, last_seq: 2 });
    render(<AuditLogPanel />);
    await waitFor(() => expect(screen.getByText("token issued")).toBeTruthy());
    expect(screen.getByText("bench queued")).toBeTruthy();
    expect(screen.getByText(/2 recorded events/)).toBeTruthy();
  });

  it("filters events by kind/message substring", async () => {
    (api.eventsRecent as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ events, last_seq: 2 });
    render(<AuditLogPanel />);
    await waitFor(() => expect(screen.getByText("token issued")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/Filter by kind/), { target: { value: "bench" } });
    expect(screen.getByText("bench queued")).toBeTruthy();
    expect(screen.queryByText("token issued")).toBeNull();
  });
});
