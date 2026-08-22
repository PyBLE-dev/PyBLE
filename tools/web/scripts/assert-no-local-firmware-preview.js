// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { lstat } from "node:fs/promises";
import { resolve } from "node:path";

const previewRoot = resolve("public", ".pyble-local-preview");
const exists = await lstat(previewRoot).then(
  () => true,
  (error) => {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  },
);

if (
  exists ||
  process.env.PYBLE_LOCAL_FLASH_PREVIEW ||
  process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE
) {
  throw new Error(
    "Production web build refuses local preview flags or .pyble-local-preview artifacts",
  );
}
