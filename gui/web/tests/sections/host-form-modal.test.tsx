// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({ api: { hostUpsert: vi.fn(), sshCheck: vi.fn() } }));
vi.mock("@/components/toast", () => ({ toast: vi.fn() }));
vi.mock("@/dialog", () => ({
  useDialogFocus: () => {},
  useEscapeKey: () => {},
  closeOnBackdrop: (fn: () => void) => () => fn(),
}));
import { api } from "@/api";
import { HostFormModal } from "@/sections/host-form-modal";

afterEach(cleanup);

describe("HostFormModal", () => {
  it("renders an add dialog with an accessible name", () => {
    render(<HostFormModal initial={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Add host profile" })).toBeTruthy();
    // Save is disabled until label or host is provided.
    expect(screen.getByText("Add profile").closest("button")!.disabled).toBe(true);
  });

  it("upserts a host and fires onSaved + onClose", async () => {
    (api.hostUpsert as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "h1", host: "10.0.0.1" });
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<HostFormModal initial={null} onClose={onClose} onSaved={onSaved} />);
    fireEvent.change(screen.getByPlaceholderText("Prod A5000"), { target: { value: "Prod" } });
    fireEvent.click(screen.getByText("Add profile"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
    expect(api.hostUpsert).toHaveBeenCalled();
  });

  it("names the dialog for edit context", () => {
    render(<HostFormModal initial={{ label: "Prod A5000", host: "10.0.0.1", ssh_target: "", port: 8765, engine_port: 8000, ssh_user: "", ssh_auth: "agent", ssh_key_path: "", ssh_port: 22, role: "", hardware: "", gpus: 0, notes: "", tags: [] } as never} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: /Edit host profile Prod A5000/ })).toBeTruthy();
  });
});
