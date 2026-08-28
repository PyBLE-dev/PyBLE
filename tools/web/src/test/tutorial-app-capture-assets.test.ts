// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { basename, join } from "node:path";

import { describe, expect, it } from "vitest";

import { tutorialAppCaptures } from "@/lib/tutorial-app-captures";

const expectedCaptureIds = [
  "setupFiveBoardScan",
  "identity5646Ready",
  "identity5646Chip",
  "identity8c9eReady",
  "identity8c9eChip",
  "identityc81aReady",
  "identityc81aChip",
  "identityda86Ready",
  "identityda86Chip",
  "identity3dcbReady",
  "identity3dcbChip",
  "firstProgramEditorConsole",
  "filesMultiDeleteReview",
  "githubBranchChooser",
  "githubPinnedSource",
  "githubTargetReview",
  "examplesImportComplete",
  "blocksHelloWorkspace",
] as const;

const identityDimensions = {
  identity5646Ready: { width: 400, height: 84 },
  identity5646Chip: { width: 512, height: 390 },
  identity8c9eReady: { width: 400, height: 84 },
  identity8c9eChip: { width: 512, height: 390 },
  identityc81aReady: { width: 400, height: 84 },
  identityc81aChip: { width: 512, height: 390 },
  identityda86Ready: { width: 400, height: 84 },
  identityda86Chip: { width: 512, height: 390 },
  identity3dcbReady: { width: 400, height: 84 },
  identity3dcbChip: { width: 512, height: 390 },
} as const;

type CaptureRecord = {
  src: string;
  alt: string;
  width: number;
  height: number;
  provenance: {
    rawCapture: string;
    processing: string;
    depictedState: string;
    review:
      | { status: "pending-derivative"; sha256: null }
      | { status: "reviewed"; sha256: string };
  };
};

const captures = tutorialAppCaptures as unknown as Record<
  string,
  CaptureRecord | undefined
>;
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
    if (chunkType === "IEND") break;
  }

  return chunkTypes;
}

describe("reviewed physical tutorial capture assets", () => {
  it("keeps the five-board capture registry complete and unique", () => {
    expect(Object.keys(tutorialAppCaptures)).toEqual(expectedCaptureIds);
    expect(
      new Set(Object.values(tutorialAppCaptures).map(({ src }) => src)).size,
    ).toBe(expectedCaptureIds.length);
  });

  it.each(expectedCaptureIds)(
    "%s binds content-versioned, stripped PNG bytes to reviewed provenance",
    async (captureId) => {
      const capture = captures[captureId];
      expect(capture).toBeDefined();
      if (!capture) return;

      const { review } = capture.provenance;
      expect(review.status).toBe("reviewed");
      if (review.status !== "reviewed") return;

      expect(review.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(basename(capture.src)).toContain(review.sha256.slice(0, 12));
      expect(capture.src).not.toContain("pending");
      expect(capture.provenance.rawCapture).toMatch(/\.raw\.png$/);
      expect(capture.provenance.rawCapture).not.toMatch(
        /debug|golden|integration|ipad/i,
      );
      expect(capture.provenance.processing).toMatch(
        /crop.*strip metadata.*not retouch/is,
      );

      const expectedDimensions =
        captureId in identityDimensions
          ? identityDimensions[captureId as keyof typeof identityDimensions]
          : { width: 2000, height: 1092 };
      expect({ width: capture.width, height: capture.height }).toEqual(
        expectedDimensions,
      );

      const asset = await readFile(
        join(process.cwd(), "public", capture.src.slice(1)),
      );
      expect(asset.subarray(0, pngSignature.length)).toEqual(pngSignature);
      expect(asset.readUInt32BE(16)).toBe(capture.width);
      expect(asset.readUInt32BE(20)).toBe(capture.height);
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

  it("keeps both S3 observations truthful and non-identifying", () => {
    expect(captures.identity5646Ready?.provenance.depictedState).toMatch(
      /5646.*0\.6\.0/is,
    );
    expect(captures.identityda86Ready?.provenance.depictedState).toMatch(
      /DA86.*0\.6\.0/is,
    );
    expect(captures.identity5646Chip?.provenance.depictedState).toMatch(
      /esp32-s3.*not.*profile/is,
    );
    expect(captures.identityda86Chip?.provenance.depictedState).toMatch(
      /esp32-s3.*not.*profile/is,
    );
  });
});
