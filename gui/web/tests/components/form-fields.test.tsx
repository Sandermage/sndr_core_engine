// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { TextField, NumberField, BoolField, SelectField } from "@/components/form-fields";

afterEach(cleanup);

describe("TextField", () => {
  it("emits the typed string", () => {
    const onChange = vi.fn();
    render(<TextField label="Name" value="a" onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue("a"), { target: { value: "ab" } });
    expect(onChange).toHaveBeenCalledWith("ab");
  });
});

describe("NumberField", () => {
  it("emits a numeric value", () => {
    const onChange = vi.fn();
    render(<NumberField label="N" value={1} onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue("1"), { target: { value: "5" } });
    expect(onChange).toHaveBeenCalledWith(5);
  });
});

describe("BoolField", () => {
  it("toggles via an aria-pressed button", () => {
    const onChange = vi.fn();
    render(<BoolField label="Eager" value={false} onChange={onChange} />);
    const btn = screen.getByRole("button", { name: /Eager/ });
    expect(btn.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(btn);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("SelectField", () => {
  it("renders options + emits the chosen value", () => {
    const onChange = vi.fn();
    render(<SelectField label="Mode" value="a" options={["a", "b"]} onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue("a"), { target: { value: "b" } });
    expect(onChange).toHaveBeenCalledWith("b");
  });
});
