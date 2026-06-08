// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { Step, Metric, PanelHeader, TabIntro, CodeTabs } from "@/components/shell-bits";

afterEach(cleanup);

describe("Step", () => {
  it("renders a static step, and a button with aria-current when clickable", () => {
    const onClick = vi.fn();
    const { rerender } = render(<Step number="1" title="Detect" detail="host" state="done" />);
    expect(screen.getByText("Detect")).toBeTruthy();
    rerender(<Step number="2" title="Launch" detail="go" state="active" active onClick={onClick} />);
    const btn = screen.getByRole("button", { name: /Launch/ });
    expect(btn.getAttribute("aria-current")).toBe("true");
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalled();
  });
});

describe("Metric + PanelHeader + TabIntro", () => {
  it("render their label/value/title content", () => {
    render(<><Metric icon={null} label="GPUs" value={2} /><PanelHeader label="Tab" title="Hosts" icon={null} /><TabIntro icon={null} title="Intro" text="what it does" /></>);
    expect(screen.getByText("GPUs")).toBeTruthy();
    expect(screen.getByText("Hosts")).toBeTruthy();
    expect(screen.getByText("what it does")).toBeTruthy();
  });
});

describe("CodeTabs", () => {
  it("renders a WCAG tablist + switches code view", () => {
    render(<CodeTabs tabs={[{ id: "a", label: "Alpha", lines: ["alpha"] }, { id: "b", label: "Beta", lines: ["beta"] }]} />);
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "Alpha" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "Beta" }));
    expect(screen.getByRole("tab", { name: "Beta" }).getAttribute("aria-selected")).toBe("true");
  });
});
