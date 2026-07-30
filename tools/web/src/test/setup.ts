// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// A protected release build legitimately exports these values while running
// the suite. Tests start from the public fail-closed state and opt in to an
// exact candidate pair themselves, so ambient build state cannot reclassify a
// public-page or no-firmware fixture.
delete process.env.PYBLE_FLASH_SELECTION_FILE;
delete process.env.PYBLE_FIRMWARE_STAGED_ROOT;

afterEach(() => {
  cleanup();
});
