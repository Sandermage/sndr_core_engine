// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", () => ({ api: { hostProbe: vi.fn() } }));
vi.mock("../components/toast", () => ({ toast: vi.fn() }));
import { api } from "../api";
import { FleetHostCard, roleTone, tunnelCommand } from "./fleet-host-card";

afterEach(cleanup);

const profile = {
  id: "h1", label: "Prod A5000", host: "10.0.0.10", transport: "local", ssh_user: "", ssh_auth: "agent",
  ssh_key_path: "", ssh_port: 22, ssh_target: "", role: "production", hardware: "2× A5000", gpus: 2,
  port: 8765, engine_port: 8101, notes: "", tags: ["27b"], has_ssh_password: false, has_api_key: false,
} as never;

const cbs = { onEdit: vi.fn(), onDelete: vi.fn(), onChat: vi.fn(), onAddServer: vi.fn(), onRefresh: vi.fn(), onTerminal: vi.fn() };

describe("roleTone", () => {
  it("maps roles to tones", () => {
    expect(roleTone("production")).toBe("danger");
    expect(roleTone("staging")).toBe("warn");
    expect(roleTone("dev")).toBe("info");
    expect(roleTone("unknown")).toBe("muted");
  });
});

describe("tunnelCommand", () => {
  it("builds an SSH -L command for ssh transport", () => {
    expect(tunnelCommand({ transport: "ssh", ssh_target: "u@h", port: 8765 } as never)).toBe("ssh -L 8765:127.0.0.1:8765 u@h");
  });
  it("falls back to a local hint otherwise", () => {
    expect(tunnelCommand({ transport: "local", port: 8765 } as never)).toContain("# local");
  });
});

describe("FleetHostCard", () => {
  it("renders the host identity + role + tunnel line", () => {
    render(<FleetHostCard profile={profile} {...cbs} />);
    expect(screen.getByText("Prod A5000")).toBeTruthy();
    expect(screen.getByText("production")).toBeTruthy();
    expect(screen.getByText(/# local/)).toBeTruthy();
  });

  it("probes the engine and shows the result", async () => {
    (api.hostProbe as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ reachable: true, host: "10.0.0.10", port: 8101, base_url: "", version: "0.20.2", models: ["qwen"], latency_ms: 12, error: null });
    render(<FleetHostCard profile={profile} {...cbs} />);
    fireEvent.click(screen.getByText("Probe engine"));
    await waitFor(() => expect(screen.getByText("engine up")).toBeTruthy());
  });

  it("fires edit + delete from the footer", () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    render(<FleetHostCard profile={profile} {...cbs} onEdit={onEdit} onDelete={onDelete} />);
    fireEvent.click(screen.getByLabelText("Edit Prod A5000"));
    fireEvent.click(screen.getByLabelText("Delete Prod A5000"));
    expect(onEdit).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalledWith("h1");
  });
});
