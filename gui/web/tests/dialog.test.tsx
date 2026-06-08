import { describe, it, expect, afterEach, beforeAll, vi } from "vitest";
import { useRef } from "react";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { useDialogFocus, useEscapeKey } from "@/dialog";

afterEach(cleanup);

// jsdom does no layout, so `offsetParent` is always null and the visibility
// filter in useDialogFocus would treat every control as hidden. Shim it to the
// parent for attached nodes so focus traversal can be exercised in tests.
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() { return this.parentNode; },
  });
});

function EscProbe({ onClose }: { onClose: () => void }) {
  useEscapeKey(onClose);
  return <div>dialog</div>;
}

describe("useEscapeKey", () => {
  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<EscProbe onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores other keys", () => {
    const onClose = vi.fn();
    render(<EscProbe onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyDown(window, { key: "a" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("detaches its listener on unmount", () => {
    const onClose = vi.fn();
    const { unmount } = render(<EscProbe onClose={onClose} />);
    unmount();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });
});

function TrapProbe() {
  const ref = useRef<HTMLDivElement>(null);
  useDialogFocus(ref);
  return (
    <div ref={ref} role="dialog">
      <button>first</button>
      <button>last</button>
    </div>
  );
}

describe("useDialogFocus", () => {
  it("focuses the first focusable element on open", () => {
    const { getByText } = render(<TrapProbe />);
    expect(document.activeElement).toBe(getByText("first"));
  });

  it("restores focus to the trigger on unmount", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { unmount } = render(<TrapProbe />);
    expect(document.activeElement).not.toBe(trigger); // trap moved focus inside
    unmount();
    expect(document.activeElement).toBe(trigger); // restored
    trigger.remove();
  });
});
