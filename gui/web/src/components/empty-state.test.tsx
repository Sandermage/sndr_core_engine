// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { EmptyState } from "./empty-state";

afterEach(cleanup);

describe("EmptyState", () => {
  it("renders title + message inside a status region", () => {
    render(<EmptyState title="Nothing here" message="Add an item to begin." />);
    const region = screen.getByRole("status");
    expect(region.textContent).toContain("Nothing here");
    expect(region.textContent).toContain("Add an item to begin.");
  });

  it("renders + fires the optional recovery action", () => {
    const onClick = vi.fn();
    render(<EmptyState title="Empty" action={{ label: "Reset", onClick }} />);
    fireEvent.click(screen.getByText("Reset"));
    expect(onClick).toHaveBeenCalled();
  });
});
