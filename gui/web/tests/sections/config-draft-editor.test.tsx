// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ConfigDraftEditor } from "@/sections/config-draft-editor";

afterEach(cleanup);

describe("ConfigDraftEditor", () => {
  it("renders the param sections + a no-changes baseline state", () => {
    render(<ConfigDraftEditor selectedPreset="p27b" composed={{ max_model_len: 8192 }} runtimeTarget="docker" patchPolicy="safe" />);
    expect(screen.getByText("Sizing & memory")).toBeTruthy();
    expect(screen.getByText(/No changes vs composed baseline/)).toBeTruthy();
    // collapsible disclosure wires aria-controls
    const head = screen.getByRole("button", { name: /Sizing & memory/ });
    const controls = head.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    expect(document.getElementById(controls!)).not.toBeNull();
  });

  it("tracks an edit as a pending change with a friendly diff label", () => {
    render(<ConfigDraftEditor selectedPreset="p27b" composed={{ max_model_len: 8192, enforce_eager: false }} runtimeTarget="docker" patchPolicy="safe" />);
    const eager = screen.getByRole("button", { name: /Enforce eager/ });
    fireEvent.click(eager);
    expect(screen.getByText("Pending changes (1)")).toBeTruthy();
    expect(screen.getByText(/Enforce eager: false → true/)).toBeTruthy();
  });

  it("exposes the patch-policy segmented control with aria-pressed", () => {
    render(<ConfigDraftEditor selectedPreset="p" composed={{}} runtimeTarget="docker" patchPolicy="safe" />);
    expect(screen.getByRole("group", { name: "Patch policy" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "safe" }).getAttribute("aria-pressed")).toBe("true");
  });
});
