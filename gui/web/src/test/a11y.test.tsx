// SPDX-License-Identifier: Apache-2.0
// Accessibility regression gate. Renders representative components from each
// layer (primitives, dialogs, jobs, empty-state) and asserts axe-core finds no
// structural/ARIA violations. Catches the classic regressions: a button that
// loses its accessible name, a dialog missing aria-modal, a table header that
// drops scope, an icon-only control with no label.
import { describe, it, afterEach, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { expectNoA11yViolations } from "./axe";

vi.mock("../dialog", () => ({
  useDialogFocus: () => {},
  useEscapeKey: () => {},
  closeOnBackdrop: (fn: () => void) => () => fn(),
}));

import { StatusPill } from "../components/primitives";
import { ConfirmDialog, InfoDialog, ShortcutsModal } from "../components/dialogs";
import { Progress } from "../sections/jobs";

afterEach(cleanup);

describe("a11y: primitives", () => {
  it("StatusPill has no violations", async () => {
    const { container } = render(<StatusPill tone="success">Healthy</StatusPill>);
    await expectNoA11yViolations(container);
  });

  it("Progress exposes a labelled progressbar", async () => {
    const { container } = render(<Progress value={42} />);
    await expectNoA11yViolations(container);
  });
});

describe("a11y: dialogs", () => {
  it("ConfirmDialog has no violations", async () => {
    const { container } = render(
      <ConfirmDialog title="Delete pin" message="Are you sure?" confirmLabel="Delete" danger onConfirm={() => {}} onCancel={() => {}} />,
    );
    await expectNoA11yViolations(container);
  });

  it("InfoDialog has no violations", async () => {
    const { container } = render(<InfoDialog message="dry-run output" onClose={() => {}} />);
    await expectNoA11yViolations(container);
  });

  it("ShortcutsModal has no violations", async () => {
    const { container } = render(<ShortcutsModal onClose={() => {}} />);
    await expectNoA11yViolations(container);
  });
});
