// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { TabbedSection } from "./tabbed-section";

afterEach(cleanup);

const tabs = [
  { id: "a", label: "Alpha", render: () => <p>alpha body</p> },
  { id: "b", label: "Beta", render: () => <p>beta body</p> },
  { id: "c", label: "Gamma", render: () => <p>gamma body</p> },
];

describe("TabbedSection", () => {
  it("renders a WCAG tablist with the first tab selected + its panel", () => {
    render(<TabbedSection id="s" tabs={tabs} />);
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha.getAttribute("aria-selected")).toBe("true");
    expect(alpha.getAttribute("tabindex")).toBe("0");
    expect(screen.getByRole("tabpanel").textContent).toContain("alpha body");
  });

  it("switches tab on click", () => {
    render(<TabbedSection id="s" tabs={tabs} />);
    fireEvent.click(screen.getByRole("tab", { name: "Beta" }));
    expect(screen.getByRole("tabpanel").textContent).toContain("beta body");
  });

  it("navigates with ArrowRight / End / Home", () => {
    render(<TabbedSection id="s" tabs={tabs} />);
    const list = screen.getByRole("tablist");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByRole("tabpanel").textContent).toContain("beta body");
    fireEvent.keyDown(list, { key: "End" });
    expect(screen.getByRole("tabpanel").textContent).toContain("gamma body");
    fireEvent.keyDown(list, { key: "Home" });
    expect(screen.getByRole("tabpanel").textContent).toContain("alpha body");
  });

  it("supports controlled mode via activeTab + onTabChange", () => {
    const onTabChange = vi.fn();
    render(<TabbedSection id="s" tabs={tabs} activeTab="b" onTabChange={onTabChange} />);
    expect(screen.getByRole("tabpanel").textContent).toContain("beta body");
    fireEvent.click(screen.getByRole("tab", { name: "Gamma" }));
    expect(onTabChange).toHaveBeenCalledWith("c");
  });
});
