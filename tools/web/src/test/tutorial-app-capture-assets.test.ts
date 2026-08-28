// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { basename, join } from "node:path";

import { describe, expect, it } from "vitest";

import { tutorialAppCaptures } from "@/lib/tutorial-app-captures";

const expectedCaptureIds = [
  "setupScanResults",
  "setupConnectedIdentity",
  "firstProgramEditorConsole",
  "filesMultiDeleteReview",
  "githubBranchChooser",
  "githubPrewriteReview",
  "examplesImportComplete",
  "blocksHelloWorkspace",
] as const;

const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const forbiddenMetadataChunks = new Set([
  "eXIf",
  "iTXt",
  "tEXt",
  "tIME",
  "zTXt",
]);

function pngChunkTypes(bytes: Buffer): string[] {
  const chunkTypes: string[] = [];
  let offset = pngSignature.length;

  while (offset + 12 <= bytes.length) {
    const dataLength = bytes.readUInt32BE(offset);
    const chunkEnd = offset + 12 + dataLength;
    expect(chunkEnd).toBeLessThanOrEqual(bytes.length);

    const chunkType = bytes.toString("ascii", offset + 4, offset + 8);
    chunkTypes.push(chunkType);
    offset = chunkEnd;

    if (chunkType === "IEND") {
      break;
    }
  }

  return chunkTypes;
}

describe("reviewed physical tutorial capture assets", () => {
  it("keeps the reviewed capture registry complete and unique", () => {
    expect(Object.keys(tutorialAppCaptures)).toEqual(expectedCaptureIds);
    expect(
      new Set(Object.values(tutorialAppCaptures).map(({ src }) => src)).size,
    ).toBe(expectedCaptureIds.length);
  });

  it.each(expectedCaptureIds)(
    "%s binds content-versioned, stripped PNG bytes to reviewed provenance",
    async (captureId) => {
      const capture = tutorialAppCaptures[captureId];
      const { review } = capture.provenance;

      if (review.status !== "reviewed") {
        throw new Error(`${captureId} has not completed derivative review`);
      }

      expect(review.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(basename(capture.src)).toContain(review.sha256.slice(0, 12));
      expect(capture.src).not.toContain("pending");
      expect(capture.provenance.rawCapture).toMatch(
        /production-release\.raw\.png$/,
      );
      expect(capture.provenance.rawCapture).not.toMatch(
        /debug|golden|integration/i,
      );
      expect(capture.provenance.processing).toMatch(
        /crop.*status.*navigation.*strip metadata.*not retouch/is,
      );

      const asset = await readFile(
        join(process.cwd(), "public", capture.src.slice(1)),
      );
      expect(asset.subarray(0, pngSignature.length)).toEqual(pngSignature);
      expect(asset.readUInt32BE(16)).toBe(capture.width);
      expect(asset.readUInt32BE(20)).toBe(capture.height);
      expect({ width: capture.width, height: capture.height }).toEqual({
        width: 2000,
        height: 1092,
      });
      expect(createHash("sha256").update(asset).digest("hex")).toBe(
        review.sha256,
      );

      const chunkTypes = pngChunkTypes(asset);
      expect(chunkTypes.at(0)).toBe("IHDR");
      expect(chunkTypes.at(-1)).toBe("IEND");
      expect(
        chunkTypes.filter((chunkType) =>
          forbiddenMetadataChunks.has(chunkType),
        ),
      ).toEqual([]);
    },
  );
});
