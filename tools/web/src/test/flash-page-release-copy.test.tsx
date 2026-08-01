// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FlashPage from "@/app/flash/page";
import { passedPublicFirmwareRelease } from "@/test/fixtures/firmware-release";

describe("firmware installer release copy", () => {
  it("describes a qualified public selector as available", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-flash-qualified-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;

    try {
      await writeFile(
        selectionFile,
        JSON.stringify(passedPublicFirmwareRelease),
        "utf8",
      );
      render(<FlashPage />);

      expect(
        screen.getByText(/qualified v0\.4\.2 firmware is available/i),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/public install action remains unavailable/i),
      ).toBeNull();
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });
});
