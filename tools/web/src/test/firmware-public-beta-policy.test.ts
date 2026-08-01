// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { describe, expect, it } from "vitest";

import { isExactPublicBetaFirmwareRelease } from "@/lib/firmware-release";
import { publicBetaFirmwareRelease } from "@/test/fixtures/firmware-release";

describe("exact public firmware beta policy", () => {
  it("accepts only the audited unrestricted pending v0.4.2 descriptor", () => {
    expect(isExactPublicBetaFirmwareRelease(publicBetaFirmwareRelease)).toBe(
      true,
    );

    for (const mutate of [
      (descriptor: Record<string, unknown>) => {
        descriptor.version = "0.4.1";
      },
      (descriptor: Record<string, unknown>) => {
        descriptor.hilStatus = "passed";
      },
      (descriptor: Record<string, unknown>) => {
        descriptor.accessControlled = true;
      },
      (descriptor: Record<string, unknown>) => {
        const releaseJson = descriptor.releaseJson as Record<string, unknown>;
        releaseJson.sha256 = "0".repeat(64);
      },
    ]) {
      const descriptor = structuredClone(
        publicBetaFirmwareRelease,
      ) as unknown as Record<string, unknown>;
      mutate(descriptor);
      expect(isExactPublicBetaFirmwareRelease(descriptor)).toBe(false);
    }
  });
});
