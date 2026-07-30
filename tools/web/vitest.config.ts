// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    env: {
      PYBLE_FLASH_SELECTION_FILE:
        "/__pyble_test_inherited_firmware_selection__",
      PYBLE_FIRMWARE_STAGED_ROOT:
        "/__pyble_test_inherited_firmware_staged_root__",
    },
    setupFiles: ["./src/test/setup.ts"],
    coverage: {
      reporter: ["text", "html"],
    },
  },
});
