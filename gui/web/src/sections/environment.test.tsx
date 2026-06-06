// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { HostInventoryPanel, DependencyStackPanel, EnvironmentPanel } from "./environment";

afterEach(cleanup);

const inventory = {
  os: { distro: "Ubuntu 22.04", system: "Linux", arch: "x86_64", release: "6.5.0" },
  python: { version: "3.11.6", implementation: "CPython", binary_path: "/usr/bin/python3", venv_active: true, pip_present: true, pip_version: "24.0" },
  docker: { installed: true, version: "27.0", daemon_running: true, server_version: "27.0", binary_path: "/usr/bin/docker", nvidia_runtime_present: true, notes: "" },
  nvidia: { installed: true, driver_version: "550.54", cuda_version: "12.4", n_gpus: 2, gpu_names: ["A5000", "A5000"], gpu_total_vram_mib: [24564, 24564], notes: "" },
  vllm: { installed: true, version: "0.20.2", location: "/opt/vllm" },
};

const env = {
  engine_name: "vLLM", engine_version: "0.20.2", brand: "SNDR", package_name: "sndr", sndr_core_version: "12.1",
  dependencies: [
    { name: "vllm", present: true, version: "0.20.2" },
    { name: "torch", present: true, version: "2.5.1" },
    { name: "transformers", present: false, version: null },
  ],
  tools: [{ name: "nvidia-smi", present: true }, { name: "git", present: false }],
};

describe("HostInventoryPanel", () => {
  it("renders a skeleton when inventory is null", () => {
    const { container } = render(<HostInventoryPanel inventory={null} environment={null} />);
    expect(container.querySelector("[class*=skeleton]")).not.toBeNull();
  });

  it("renders system + GPU facts and a can-serve readiness chip", () => {
    render(<HostInventoryPanel inventory={inventory as never} environment={env as never} />);
    expect(screen.getByText("Ubuntu 22.04")).toBeTruthy();
    // Two A5000 24GiB → 48 GiB total.
    expect(screen.getByText("48 GiB")).toBeTruthy();
    expect(screen.getByText("can serve")).toBeTruthy();
  });
});

describe("DependencyStackPanel", () => {
  it("renders a skeleton when env is null", () => {
    const { container } = render(<DependencyStackPanel env={null} />);
    expect(container.querySelector("[class*=skeleton]")).not.toBeNull();
  });

  it("flags a missing serving-critical lib in the verdict", () => {
    render(<DependencyStackPanel env={env as never} />);
    // transformers missing → verdict lists it.
    expect(screen.getByText(/Missing transformers/)).toBeTruthy();
  });
});

describe("EnvironmentPanel", () => {
  it("renders a skeleton when env is null", () => {
    const { container } = render(<EnvironmentPanel env={null} />);
    expect(container.querySelector("[class*=skeleton]")).not.toBeNull();
  });

  it("renders version badges + dependency rows", () => {
    render(<EnvironmentPanel env={{ ...env, python_version: "3.11.6", os_name: "Linux", machine: "x86_64" } as never} />);
    expect(screen.getByText("v12.1")).toBeTruthy();
    expect(screen.getByText("Linux / x86_64")).toBeTruthy();
    expect(screen.getByText("torch")).toBeTruthy();
  });
});
