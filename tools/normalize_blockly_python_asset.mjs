// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Preserve Blockly's generated Python byte-for-byte at runtime while keeping
// the JavaScript asset from being classified as an executable Python script by
// Apple's distribution analyzer.

import fs from "node:fs";
import process from "node:process";

const [sourcePath, destinationPath] = process.argv.slice(2);
if (!sourcePath || !destinationPath) {
  throw new Error(
    "usage: normalize_blockly_python_asset.mjs SOURCE DESTINATION",
  );
}

const source = fs.readFileSync(sourcePath, "utf8");
let replacementCount = 0;
const normalized = source.replace(
  /^([ \t]*)try:/gm,
  (_match, indentation) => {
    replacementCount += 1;
    return `${indentation}\${"try"}:`;
  },
);

if (replacementCount !== 5) {
  throw new Error(
    `expected exactly 5 multiline Python try: templates, found ${replacementCount}`,
  );
}
if (/^[ \t]*try:/m.test(normalized)) {
  throw new Error("raw multiline Python try: remained after normalization");
}

const restored = normalized.replace(
  /^([ \t]*)\$\{"try"\}:/gm,
  (_match, indentation) => `${indentation}try:`,
);
if (restored !== source) {
  throw new Error("normalization changed content beyond the guarded try: tokens");
}

fs.writeFileSync(destinationPath, normalized, { encoding: "utf8", mode: 0o644 });
