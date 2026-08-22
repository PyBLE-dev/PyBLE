// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const bundledParserPath = join(
  packageRoot,
  "node_modules",
  "vinext",
  "dist",
  "deps",
  ".pnpm",
  "image-size@2.0.2",
  "deps",
  "image-size",
  "dist",
  "index.js",
);

const hardeningEdits = [
  {
    advisory: "GHSA-w3rx-r6r6-pgpr",
    before:
      "\t\t\tconst imageHeader = readImageHeader(input, imageOffset);\n\t\t\tconst imageSize2 = getImageSize2(imageHeader[0]);",
    after:
      '\t\t\tconst imageHeader = readImageHeader(input, imageOffset);\n\t\t\tif (imageHeader[1] <= 0) throw new TypeError("Invalid ICNS, zero-length image entry");\n\t\t\tconst imageSize2 = getImageSize2(imageHeader[0]);',
  },
  {
    advisory: "GHSA-5p2g-fcmc-qvqq (HEIF)",
    before:
      '\t\t\tconst ispeBox = findBox(input, "ispe", currentOffset);\n\t\t\tif (!ispeBox) break;\n\t\t\tconst rawWidth = readUInt32BE(input, ispeBox.offset + 12);',
    after:
      '\t\t\tconst ispeBox = findBox(input, "ispe", currentOffset);\n\t\t\tif (!ispeBox) break;\n\t\t\tif (ispeBox.size <= 0) throw new TypeError("Invalid HEIF, zero-length ispe box");\n\t\t\tconst rawWidth = readUInt32BE(input, ispeBox.offset + 12);',
  },
  {
    advisory: "GHSA-5p2g-fcmc-qvqq (JXL)",
    before:
      '\t\tconst jxlpBox = findBox(input, "jxlp", offset);\n\t\tif (!jxlpBox) break;\n\t\tpartialStreams.push(input.slice(jxlpBox.offset + 12, jxlpBox.offset + jxlpBox.size));',
    after:
      '\t\tconst jxlpBox = findBox(input, "jxlp", offset);\n\t\tif (!jxlpBox) break;\n\t\tif (jxlpBox.size <= 0) throw new TypeError("Invalid JXL, zero-length jxlp box");\n\t\tpartialStreams.push(input.slice(jxlpBox.offset + 12, jxlpBox.offset + jxlpBox.size));',
  },
];

/**
 * @param {string} source
 * @returns {string}
 */
export function hardenBundledImageSize(source) {
  let hardened = source;
  for (const edit of hardeningEdits) {
    const hardenedOccurrences = hardened.split(edit.after).length - 1;
    const vulnerableOccurrences = hardened.split(edit.before).length - 1;
    if (hardenedOccurrences === 1 && vulnerableOccurrences === 0) {
      continue;
    }
    if (hardenedOccurrences !== 0 || vulnerableOccurrences !== 1) {
      throw new Error(
        `Cannot apply ${edit.advisory} hardening: found ${vulnerableOccurrences} vulnerable and ${hardenedOccurrences} hardened matches`,
      );
    }
    hardened = hardened.replace(edit.before, edit.after);
  }
  return hardened;
}

async function run() {
  const source = await readFile(bundledParserPath, "utf8");
  const hardened = hardenBundledImageSize(source);
  if (hardened !== source) {
    await writeFile(bundledParserPath, hardened, "utf8");
  }
}

const invokedPath = process.argv[1];
if (
  invokedPath &&
  import.meta.url === pathToFileURL(resolve(invokedPath)).href
) {
  run().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}
