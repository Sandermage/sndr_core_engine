// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { CapabilityTable } from "@/components/capability-table";

afterEach(cleanup);

describe("CapabilityTable", () => {
  it("renders scope=col headers + a row per capability", () => {
    const { container } = render(
      <CapabilityTable
        rows={[
          { id: "service_lifecycle", title: "Service Lifecycle", status: "available", required_tools: ["docker"], detail: "plan/apply" },
          { id: "web_daemon", title: "Web Daemon", status: "deferred", required_tools: [], detail: "built-in only" },
        ] as never}
      />
    );
    expect(container.querySelectorAll('th[scope="col"]').length).toBe(4);
    expect(screen.getByText("Service Lifecycle")).toBeTruthy();
    expect(screen.getByText("docker")).toBeTruthy();
    expect(screen.getByText("built-in")).toBeTruthy();
  });
});
