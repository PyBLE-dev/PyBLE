// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { describe, expect, it } from "vitest";

import {
  type FirmwareReleaseDescriptor,
  isExactPublicBetaFirmwareRelease,
  releaseIncludesWaveshareLcd147b,
} from "@/lib/firmware-release";
import {
  currentPassedPublicFirmwareRelease,
  publicBetaFirmwareRelease,
} from "@/test/fixtures/firmware-release";

function releaseAtVersion(version: string): FirmwareReleaseDescriptor {
  const release = structuredClone(
    currentPassedPublicFirmwareRelease,
  ) as unknown as {
    version: string;
    releaseJson: { path: string };
    schemaPath: string;
    recoveryPath: string;
    profiles: Array<{ manifestPath: string; firmwarePath: string }>;
  };
  release.version = version;
  release.releaseJson.path = `/firmware/v${version}/release.json`;
  release.schemaPath = `/firmware/v${version}/release.schema.json`;
  release.recoveryPath = `/firmware/v${version}/RECOVERY.md`;
  for (const profile of release.profiles) {
    profile.manifestPath = profile.manifestPath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
    profile.firmwarePath = profile.firmwarePath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
  }
  return release as unknown as FirmwareReleaseDescriptor;
}

describe("qualified exact-board presentation", () => {
  it("keeps immutable v0.4.2 on its separate historical two-profile table", () => {
    expect(isExactPublicBetaFirmwareRelease(publicBetaFirmwareRelease)).toBe(
      true,
    );
    expect(
      isExactPublicBetaFirmwareRelease(
        currentPassedPublicFirmwareRelease as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);
  });

  it.each(["0.5.1", "0.5.1-rc.1", "0.5.1+build.1", "0.6.0", "1.0.0"])(
    "admits qualified public firmware %s",
    (version) => {
      expect(releaseIncludesWaveshareLcd147b(releaseAtVersion(version))).toBe(
        true,
      );
    },
  );

  it.each(["0.4.2", "0.4.9", "0.5.0", "0.5", "00.5.1", "0.5.1-01", "latest"])(
    "rejects older or non-canonical firmware %s",
    (version) => {
      expect(releaseIncludesWaveshareLcd147b(releaseAtVersion(version))).toBe(
        false,
      );
    },
  );

  it("rejects null, protected, pending, access-controlled, and malformed profile states", () => {
    expect(releaseIncludesWaveshareLcd147b(null)).toBe(false);

    const candidate = structuredClone(releaseAtVersion("0.5.1")) as unknown as {
      deployment: string;
      accessControlled: boolean;
      hilStatus: string;
    };
    candidate.deployment = "candidate";
    candidate.accessControlled = true;
    candidate.hilStatus = "pending";
    expect(
      releaseIncludesWaveshareLcd147b(
        candidate as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);

    const pending = structuredClone(releaseAtVersion("0.5.1")) as unknown as {
      hilStatus: string;
    };
    pending.hilStatus = "pending";
    expect(
      releaseIncludesWaveshareLcd147b(
        pending as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);

    const protectedPublic = structuredClone(
      releaseAtVersion("0.5.1"),
    ) as unknown as { accessControlled: boolean };
    protectedPublic.accessControlled = true;
    expect(
      releaseIncludesWaveshareLcd147b(
        protectedPublic as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);

    const missingProfile = structuredClone(
      releaseAtVersion("0.5.1"),
    ) as unknown as { profiles: unknown[] };
    missingProfile.profiles.pop();
    expect(
      releaseIncludesWaveshareLcd147b(
        missingProfile as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);
  });

  it("rejects aliasing, omission, and reordering of the exact third profile", () => {
    const exact = releaseAtVersion("0.5.1") as unknown as {
      profiles: Array<{
        id: string;
        manifestPath: string;
        firmwarePath: string;
      }>;
    };
    expect(
      releaseIncludesWaveshareLcd147b(
        exact as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(true);

    const aliased = structuredClone(exact);
    aliased.profiles[2]!.manifestPath = aliased.profiles[1]!.manifestPath;
    aliased.profiles[2]!.firmwarePath = aliased.profiles[1]!.firmwarePath;
    expect(
      releaseIncludesWaveshareLcd147b(
        aliased as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);

    const missing = structuredClone(exact);
    missing.profiles.pop();
    expect(
      releaseIncludesWaveshareLcd147b(
        missing as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);

    const reordered = structuredClone(exact);
    [reordered.profiles[1], reordered.profiles[2]] = [
      reordered.profiles[2]!,
      reordered.profiles[1]!,
    ];
    expect(
      releaseIncludesWaveshareLcd147b(
        reordered as unknown as FirmwareReleaseDescriptor,
      ),
    ).toBe(false);
  });
});
