// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "./empty-state";

describe("EmptyState", () => {
  it("renders title and message", () => {
    render(<EmptyState title="Nothing here" message="Add a preset to begin" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Add a preset to begin")).toBeInTheDocument();
    // role=status so screen readers announce the empty state
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the recovery action and fires onClick", async () => {
    const onClick = vi.fn();
    render(<EmptyState title="Empty" action={{ label: "Retry", onClick }} />);
    const button = screen.getByRole("button", { name: "Retry" });
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("omits the action button when no action is given", () => {
    render(<EmptyState title="Empty" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
