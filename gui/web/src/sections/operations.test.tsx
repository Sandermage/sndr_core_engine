// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", () => ({
  api: { operations: vi.fn(), operationRun: vi.fn() },
}));
vi.mock("../components/toast", () => ({ toast: vi.fn() }));
import { api } from "../api";
import { OperationsConsole } from "./operations";

afterEach(cleanup);

const result = {
  apply_enabled: true,
  operations: [
    { id: "audit", group: "Registry audits", label: "Audit registry", description: "check upstream", command: "python -m sndr.audit", estimate: "~30s" },
  ],
};

describe("OperationsConsole", () => {
  it("renders operation groups + a live apply banner after load", async () => {
    (api.operations as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(result);
    render(<OperationsConsole onMonitor={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Audit registry")).toBeTruthy());
    expect(screen.getByText(/Apply enabled/)).toBeTruthy();
  });

  it("runs an operation and calls onMonitor with the job id", async () => {
    (api.operations as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(result);
    (api.operationRun as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ job_id: "job-9" });
    const onMonitor = vi.fn();
    render(<OperationsConsole onMonitor={onMonitor} />);
    await waitFor(() => expect(screen.getByText("Run")).toBeTruthy());
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(onMonitor).toHaveBeenCalledWith("job-9"));
  });
});
