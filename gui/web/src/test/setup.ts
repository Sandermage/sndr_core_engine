// SPDX-License-Identifier: Apache-2.0
// Vitest setup: register @testing-library/jest-dom matchers (.toBeInTheDocument
// etc.) and their type augmentation on vitest's `expect`, and auto-unmount React
// trees after every test so component smoke tests don't leak DOM between cases.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
