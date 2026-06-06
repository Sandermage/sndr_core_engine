// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { RecommendationRow } from "./recommendation-row";

afterEach(cleanup);

function renderRow(row: unknown, active = false, onSelect = vi.fn()) {
  return render(
    <table><tbody><RecommendationRow row={row as never} active={active} onSelect={onSelect} /></tbody></table>
  );
}

describe("RecommendationRow", () => {
  it("renders identity + routing family + risk from evidence visibility", () => {
    renderRow({
      id: "a5000-2x-27b", model: "qwen3.6-27b", profile: "tq",
      card: { routing_family: "qwen", mode: "balanced", status: "available", workload_allow: ["free_chat"], fallback_preset: "fb", evidence_visibility: "public" },
    });
    expect(screen.getByText("a5000-2x-27b")).toBeTruthy();
    expect(screen.getByText("qwen")).toBeTruthy();
    expect(screen.getByText("Low")).toBeTruthy();
  });

  it("fires onSelect when the row button is clicked", () => {
    const onSelect = vi.fn();
    renderRow({ id: "p1", model: "m", card: {} }, false, onSelect);
    fireEvent.click(screen.getByText("p1"));
    expect(onSelect).toHaveBeenCalled();
  });
});
