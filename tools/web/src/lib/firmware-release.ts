// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export const firmwareProfileTable = [
  {
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
    chipFamily: "ESP32",
    offset: 4096,
    flashSizeBytes: 4 * 1024 * 1024,
    flashFrequencyHz: 40_000_000,
    siliconRevision: { minimumFull: 0, maximumFull: 399 },
    psram: {
      required: false,
      sizeBytes: 0,
      type: "not-required",
    },
  },
  {
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8",
    chipFamily: "ESP32-S3",
    offset: 0,
    flashSizeBytes: 16 * 1024 * 1024,
    flashFrequencyHz: 80_000_000,
    siliconRevision: { minimumFull: 0, maximumFull: 99 },
    psram: {
      required: true,
      sizeBytes: 8 * 1024 * 1024,
      type: "octal",
    },
  },
] as const;

export const plannedFirmwareProfileTable = [
  {
    id: "esp32-c3-4mb",
    label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
    chipFamily: "ESP32-C3",
    offset: 0,
    flashSizeBytes: 4 * 1024 * 1024,
    flashFrequencyHz: 80_000_000,
    siliconRevision: { minimumFull: 3, maximumFull: 199 },
    psram: {
      required: false,
      sizeBytes: 0,
      type: "not-required",
    },
  },
] as const;

export type FirmwareProfileId = (typeof firmwareProfileTable)[number]["id"];
export type PlannedFirmwareProfileId =
  (typeof plannedFirmwareProfileTable)[number]["id"];
export type FirmwareDeployment = "public" | "candidate" | "public-beta";
export type FirmwareHilStatus = "pending" | "passed";

export const publicBetaFirmwareVersion = "0.4.2";
export const publicBetaReleaseJsonSha256 =
  "5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde";

export interface FirmwareProfileDescriptor {
  readonly id: FirmwareProfileId;
  readonly label: string;
  readonly chipFamily: string;
  readonly manifestPath: string;
  readonly firmwarePath: string;
  readonly offset: number;
  readonly siliconRevision: {
    readonly minimumFull: number;
    readonly maximumFull: number;
  };
  readonly flashSizeBytes: number;
  readonly psram: {
    readonly required: boolean;
    readonly sizeBytes: number;
    readonly type: string;
  };
}

export interface FirmwareReleaseDescriptor {
  readonly deployment: FirmwareDeployment;
  readonly accessControlled: boolean;
  readonly version: string;
  readonly builtAt: string;
  readonly hilStatus: FirmwareHilStatus;
  readonly releaseJson: {
    readonly path: string;
    readonly sha256: string;
  };
  readonly schemaPath: string;
  readonly recoveryPath: string;
  readonly profiles: readonly FirmwareProfileDescriptor[];
}

export interface VerifiedFirmwareProfile {
  readonly profileId: FirmwareProfileId;
  readonly chipFamily: string;
  readonly manifestPath: string;
  readonly manifestBuildCount: 1;
  readonly firmwarePath: string;
  readonly version: string;
}

export function isExactPublicBetaFirmwareRelease(
  value: unknown,
): value is FirmwareReleaseDescriptor {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const descriptor = value as Partial<FirmwareReleaseDescriptor>;
  const version = publicBetaFirmwareVersion;
  return (
    descriptor.deployment === "public-beta" &&
    descriptor.accessControlled === false &&
    descriptor.version === version &&
    descriptor.hilStatus === "pending" &&
    descriptor.releaseJson?.path === `/firmware/v${version}/release.json` &&
    descriptor.releaseJson?.sha256 === publicBetaReleaseJsonSha256 &&
    descriptor.schemaPath === `/firmware/v${version}/release.schema.json` &&
    descriptor.recoveryPath === `/firmware/v${version}/RECOVERY.md` &&
    hasExactFirmwareProfileDescriptors(version, descriptor.profiles)
  );
}

export function profileDescriptor(
  version: string,
  profileId: FirmwareProfileId,
): FirmwareProfileDescriptor {
  const profile = firmwareProfileTable.find(
    (candidate) => candidate.id === profileId,
  );
  if (!profile) {
    throw new Error(`Unsupported firmware profile: ${profileId}`);
  }
  const root = `/firmware/v${version}/${profileId}`;
  return {
    id: profileId,
    label: profile.label,
    chipFamily: profile.chipFamily,
    manifestPath: `${root}/manifest.json`,
    firmwarePath: `${root}/firmware.bin`,
    offset: profile.offset,
    siliconRevision: profile.siliconRevision,
    flashSizeBytes: profile.flashSizeBytes,
    psram: profile.psram,
  };
}

export function firmwareProfileDescriptors(
  version: string,
): readonly FirmwareProfileDescriptor[] {
  return firmwareProfileTable.map(({ id }) => profileDescriptor(version, id));
}

export function isFirmwareProfileId(value: string): value is FirmwareProfileId {
  return firmwareProfileTable.some(({ id }) => id === value);
}

function isExactProfileDescriptor(
  value: unknown,
  expected: FirmwareProfileDescriptor,
): value is FirmwareProfileDescriptor {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const actual = value as Partial<FirmwareProfileDescriptor>;
  return (
    actual.id === expected.id &&
    actual.label === expected.label &&
    actual.chipFamily === expected.chipFamily &&
    actual.manifestPath === expected.manifestPath &&
    actual.firmwarePath === expected.firmwarePath &&
    actual.offset === expected.offset &&
    actual.siliconRevision?.minimumFull ===
      expected.siliconRevision.minimumFull &&
    actual.siliconRevision?.maximumFull ===
      expected.siliconRevision.maximumFull &&
    actual.flashSizeBytes === expected.flashSizeBytes &&
    actual.psram?.required === expected.psram.required &&
    actual.psram?.sizeBytes === expected.psram.sizeBytes &&
    actual.psram?.type === expected.psram.type
  );
}

export function hasExactFirmwareProfileDescriptors(
  version: string,
  value: unknown,
): value is readonly FirmwareProfileDescriptor[] {
  if (!Array.isArray(value)) {
    return false;
  }
  const expected = firmwareProfileDescriptors(version);
  return (
    value.length === expected.length &&
    value.every((profile, index) => {
      const expectedProfile = expected[index];
      return (
        expectedProfile !== undefined &&
        isExactProfileDescriptor(profile, expectedProfile)
      );
    })
  );
}
