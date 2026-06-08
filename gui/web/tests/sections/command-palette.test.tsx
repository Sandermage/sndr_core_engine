// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

vi.mock("@/dialog", () => ({
  useDialogFocus: () => {},
  closeOnBackdrop: (fn: () => void) => () => fn(),
}));
import { CommandPalette } from "@/sections/command-palette";

// jsdom does not implement scrollIntoView; the palette calls it to keep the
// highlighted row visible. Stub it so the component renders under test.
Element.prototype.scrollIntoView = vi.fn();

afterEach(cleanup);

const settings = { theme: "light", density: "comfortable" } as never;

function renderPalette(extra: Record<string, unknown> = {}) {
  return render(
    <CommandPalette
      onClose={vi.fn()}
      onSection={vi.fn()}
      onRefresh={vi.fn()}
      onShortcuts={vi.fn()}
      settings={settings}
      onSettings={vi.fn()}
      searchItems={[]}
      {...extra}
    />
  );
}

describe("CommandPalette", () => {
  it("exposes an accessible combobox + labelled listbox", () => {
    renderPalette();
    const input = screen.getByRole("combobox", { name: "Search commands and sections" });
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("listbox", { name: "Commands" })).toBeTruthy();
  });

  it("filters commands by query", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "doctor" } });
    expect(screen.getByText("Run Doctor View")).toBeTruthy();
    expect(screen.queryByText("Open Launch Plan")).toBeNull();
  });

  it("End jumps the active option to the last result", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "End" });
    const options = screen.getAllByRole("option");
    expect(options[options.length - 1].getAttribute("aria-selected")).toBe("true");
  });

  it("runs the first command on Enter and closes (non-keep commands)", () => {
    const onRefresh = vi.fn();
    const onClose = vi.fn();
    renderPalette({ onRefresh, onClose });
    const input = screen.getByRole("combobox");
    // Default highlight is the first command (Sync Catalog -> onRefresh).
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRefresh).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
