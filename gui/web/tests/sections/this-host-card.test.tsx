// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThisHostCard } from "@/sections/this-host-card";

afterEach(cleanup);

const inventory = {
  os: { distro: "Ubuntu", system: "Linux", arch: "x86_64" },
  python: { version: "3.11.6", venv_active: true },
  docker: { installed: true, daemon_running: true, server_version: "27.0", nvidia_runtime_present: true },
  nvidia: { installed: true, n_gpus: 2, gpu_names: ["A5000", "A5000"], gpu_total_vram_mib: [24564, 24564], driver_version: "550", cuda_version: "12.4" },
  vllm: { installed: true, version: "0.20.2" },
} as never;

describe("ThisHostCard", () => {
  it("renders ellipses while inventory is loading", () => {
    const { container } = render(<ThisHostCard inventory={null} environment={null} apiBase="http://127.0.0.1:8765" />);
    expect(container.textContent).toContain("http://127.0.0.1:8765");
    expect(container.querySelectorAll("dd")[1].textContent).toBe("…");
  });

  it("renders inventory facts + capability chips when present", () => {
    const { container } = render(<ThisHostCard inventory={inventory} environment={{ sndr_core_version: "12.1" } as never} apiBase="http://127.0.0.1:8765" />);
    expect(screen.getByText("48 GiB · 24 GiB/GPU")).toBeTruthy();
    expect(screen.getByText("v12.1")).toBeTruthy();
    expect(container.querySelectorAll(".cap-chip.on").length).toBe(4);
  });
});
